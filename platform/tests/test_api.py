"""Platform API against the live compose database, MLflow and lake (real data).

Every test runs inside one database transaction that is rolled back afterwards, so test
users, test alerts and the audit rows the API writes never reach the platform.
"""

import uuid

import mlflow
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api.app import app
from wtpdm.api.deps import db
from wtpdm.api.security import create_token, hash_password
from wtpdm.db.models import Alert, AlertStatus, AppUser, AuditLog, ReplayState, Role, Severity
from wtpdm.settings import get_settings

pytestmark = pytest.mark.integration
PASSWORD = "pytest-password-123"


@pytest.fixture
def session(db_engine):
    conn = db_engine.connect()
    outer = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

    def override():
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise

    app.dependency_overrides[db] = override
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    for role in Role:
        s.add(
            AppUser(
                username=f"pytest-{role.value}",
                display_name=f"Test {role.value}",
                password_hash=hash_password(PASSWORD),
                role=role,
                is_active=True,
            )
        )
    # Releases the savepoint only: the data stays in the outer transaction (rolled back at the
    # end) and survives requests whose errors roll back their own savepoint.
    s.commit()
    yield s
    app.dependency_overrides.clear()
    s.close()
    outer.rollback()
    conn.close()


@pytest.fixture
def client(session):
    return TestClient(app)


def auth(role: Role) -> dict:
    token, _ = create_token(f"pytest-{role.value}", role)
    return {"Authorization": f"Bearer {token}"}


VIEWER, ENGINEER, ADMIN = auth(Role.VIEWER), auth(Role.ENGINEER), auth(Role.ADMIN)


# ---------------------------------------------------------------- auth


def test_liveness_needs_no_token_but_data_does(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/fleet").status_code == 401
    assert client.get("/api/fleet", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_login_issues_a_token_and_audits_failures(client, session):
    bad = client.post("/api/auth/token", data={"username": "pytest-viewer", "password": "wrong"})
    assert bad.status_code == 401
    assert session.scalars(
        select(AuditLog).where(AuditLog.action == "auth.login_failed", AuditLog.actor == "pytest-viewer")
    ).first()
    ok = client.post("/api/auth/token", data={"username": "pytest-viewer", "password": PASSWORD})
    assert ok.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"})
    assert me.json()["role"] == "viewer"


def test_deactivated_user_is_rejected_immediately(client, session):
    user = session.scalars(select(AppUser).where(AppUser.username == "pytest-engineer")).one()
    user.is_active = False
    session.commit()
    assert client.get("/api/fleet", headers=ENGINEER).status_code == 401


def test_user_administration_is_admin_only(client):
    assert client.get("/api/users", headers=ENGINEER).status_code == 403
    body = {"username": "pytest-new", "display_name": "New", "password": PASSWORD, "role": "engineer"}
    assert client.post("/api/users", json=body, headers=ADMIN).status_code == 201
    assert client.post("/api/users", json=body, headers=ADMIN).status_code == 409
    demote_self = client.patch("/api/users/pytest-admin", json={"role": "viewer"}, headers=ADMIN)
    assert demote_self.status_code == 409


# ---------------------------------------------------------------- fleet & turbines


def test_fleet_covers_every_replayed_turbine(client, session):
    r = client.get("/api/fleet", headers=VIEWER)
    assert r.status_code == 200
    body = r.json()
    replaying = len(session.scalars(select(ReplayState)).all())
    assert body["kpis"]["turbines"] == len(body["turbines"]) >= replaying > 0
    assert {t["farm_id"] for t in body["turbines"]} <= {"A", "B", "C"}
    for t in body["turbines"]:
        assert t["health"] is None or 0 <= t["health"] <= 100


def _reporting_turbine(client) -> dict:
    turbines = [
        t for t in client.get("/api/fleet", headers=VIEWER).json()["turbines"] if t["health"] is not None
    ]
    if not turbines:
        pytest.skip("no turbine has a health score yet (is the worker running?)")
    return turbines[0]


def test_turbine_detail_tree_and_trends(client):
    t = _reporting_turbine(client)
    detail = client.get(f"/api/turbines/{t['id']}", headers=VIEWER).json()
    assert detail["components_tree"], "every farm monitors at least one component"
    subparts = [sp for c in detail["components_tree"] for sp in c["subparts"]]
    assert any(sp["sensors"] for sp in subparts)

    trend = client.get(f"/api/turbines/{t['id']}/health", params={"points": 200}, headers=VIEWER).json()
    assert trend["window"]["end"].startswith(t["replay"]["cursor_ts"][:16])
    assert trend["window"]["bucket_seconds"] % 600 == 0
    turbine_series = next(s for s in trend["series"] if s["subcomponent"] == "turbine")
    assert 0 < len(turbine_series["points"]) <= 200

    sensor = next(sp["sensors"][0] for sp in subparts if sp["sensors"])
    tel = client.get(
        f"/api/turbines/{t['id']}/telemetry",
        params={"sensors": sensor["code"], "points": 100},
        headers=VIEWER,
    ).json()
    assert tel["series"][0]["unit"] == sensor["unit"] and len(tel["series"][0]["points"]) <= 100


def test_expected_vs_actual_uses_the_champion_nbm(client):
    t = _reporting_turbine(client)
    detail = client.get(f"/api/turbines/{t['id']}", headers=VIEWER).json()
    scored = [sp for c in detail["components_tree"] for sp in c["subparts"] if sp["health"] is not None]
    sensors = [x["code"] for sp in scored for x in sp["sensors"]]
    for code in sensors:  # the first sensor that kept an NBM in training
        r = client.get(f"/api/turbines/{t['id']}/expected", params={"sensor": code}, headers=VIEWER)
        if r.status_code == 200:
            body = r.json()
            assert body["nbm_candidate"] in {"ridge_poly2", "lightgbm", "mlp"}
            assert any(p["expected"] is not None and p["actual"] is not None for p in body["points"])
            return
        assert r.status_code == 422
    pytest.fail("no sensor of a scored sub-part has an expected-value model")


def test_unknown_inputs_are_rejected(client):
    assert client.get("/api/turbines/Z-99", headers=VIEWER).status_code == 404
    t = _reporting_turbine(client)
    r = client.get(f"/api/turbines/{t['id']}/telemetry", params={"sensors": "nope"}, headers=VIEWER)
    assert r.status_code == 422


# ---------------------------------------------------------------- alerts workflow


@pytest.fixture
def alert(session) -> Alert:
    turbine = session.scalars(select(ReplayState.turbine_id)).first()
    a = Alert(
        turbine_id=turbine,
        component_code="gearbox",
        subcomponent_code=None,
        severity=Severity.HIGH,
        status=AlertStatus.OPEN,
        title="pytest alert",
        message="pytest workflow check",
        condition_active=True,
    )
    session.add(a)
    session.commit()
    return a


def test_alert_workflow_with_audit_trail(client, alert):
    url = f"/api/alerts/{alert.id}"
    assert client.post(f"{url}/acknowledge", headers=VIEWER).status_code == 403
    ack = client.post(f"{url}/acknowledge", json={"note": "looking at it"}, headers=ENGINEER)
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged" and ack.json()["assignee"] == "pytest-engineer"
    assert client.post(f"{url}/acknowledge", headers=ENGINEER).status_code == 409

    assert (
        client.post(f"{url}/assign", json={"assignee": "pytest-viewer"}, headers=ENGINEER).status_code == 422
    )
    assert (
        client.post(f"{url}/assign", json={"assignee": "pytest-admin"}, headers=ENGINEER).json()["assignee"]
        == "pytest-admin"
    )
    assert client.post(f"{url}/notes", json={"body": "oil sample taken"}, headers=ENGINEER).status_code == 201

    assert client.post(f"{url}/resolve", json={"resolution": "x"}, headers=ENGINEER).status_code == 422
    done = client.post(f"{url}/resolve", json={"resolution": "filter replaced"}, headers=ENGINEER).json()
    assert done["status"] == "resolved" and done["resolved_by"] == "pytest-engineer"
    assert [n["body"] for n in done["notes"]] == [
        "looking at it",
        "oil sample taken",
        "Resolution: filter replaced",
    ]
    assert [a["action"] for a in done["audit"]] == [
        "alert.acknowledge",
        "alert.assign",
        "alert.note",
        "alert.resolve",
    ]
    assert client.post(f"{url}/resolve", json={"resolution": "again"}, headers=ENGINEER).status_code == 409


def test_alert_list_filters_and_summary(client, alert):
    page = client.get(
        "/api/alerts", params={"turbine": alert.turbine_id, "q": "pytest", "active": True}, headers=VIEWER
    ).json()
    assert [a["id"] for a in page["items"]] == [str(alert.id)] and page["total"] == 1
    assert page["items"][0]["farm_id"] == alert.turbine_id.split("-")[0]
    summary = client.get("/api/alerts/summary", headers=VIEWER).json()
    assert summary["by_status"]["open"] >= 1 and summary["by_severity"]["high"] >= 1
    assert client.get(f"/api/alerts/{uuid.uuid4()}", headers=VIEWER).status_code == 404


# ---------------------------------------------------------------- MLOps & data


def test_models_registry_comparison_and_card(client):
    models = client.get("/api/models", headers=VIEWER).json()
    assert {m["farm"] for m in models} == {"A", "B", "C"}
    for m in models:
        assert any("champion" in v["aliases"] for v in m["versions"]), m["farm"]
    champion = next(v for v in models[0]["versions"] if "champion" in v["aliases"])
    comp = client.get(f"/api/models/A/versions/{champion['version']}/comparison", headers=VIEWER).json()
    assert {"threshold_baseline", "isolation_forest"} <= {d["detector"] for d in comp["detectors"]}
    assert comp["nbm"] and comp["components"]
    card = client.get(f"/api/models/A/versions/{champion['version']}/card", headers=VIEWER)
    assert card.status_code == 200 and card.text.startswith("#")


def test_retrain_and_approval_are_admin_only(client):
    body = {"farm": "A", "reason": "pytest"}
    assert client.post("/api/retrain/jobs", json=body, headers=ENGINEER).status_code == 403
    assert client.post("/api/retrain/jobs", json={**body, "farm": "D"}, headers=ADMIN).status_code == 422
    assert client.post("/api/models/A/versions/1/approve", headers=ENGINEER).status_code == 403
    schedule = client.get("/api/retrain/schedule", headers=VIEWER).json()
    assert schedule["next_run"] and schedule["promotion_gate"]["min_care_score_improvement"] > 0


def test_drift_and_data_catalog(client):
    drift = client.get("/api/drift", headers=VIEWER).json()
    assert {d["farm_id"] for d in drift} == {"A", "B", "C"}
    assert all(d["status"] in {"ok", "warning", "drift", "no_data"} for d in drift)
    events = client.get("/api/data/events", headers=VIEWER).json()
    assert len(events) == 95
    quality = client.get("/api/data/quality", params={"farm": "A"}, headers=VIEWER).json()
    assert quality["sensors"] and all(r["description"] for r in quality["sensors"])
    coverage = client.get("/api/data/coverage", headers=VIEWER).json()
    assert set(coverage["matrix"]) == {"A", "B", "C"}
    assert client.get("/api/audit", headers=VIEWER).status_code == 403


def test_stream_requires_a_token(client):
    assert client.get("/api/stream").status_code == 401


def test_openapi_documents_every_area(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    for prefix in ("/api/fleet", "/api/turbines", "/api/alerts", "/api/models", "/api/drift", "/api/retrain"):
        assert any(p.startswith(prefix) for p in paths), prefix
