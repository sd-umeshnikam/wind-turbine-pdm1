from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from wtpdm.api import models_service, timewindow
from wtpdm.api.security import (
    ALGORITHM,
    Principal,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from wtpdm.db.models import Role

CURSOR = datetime(2019, 1, 8, 18, 10, tzinfo=UTC)


def test_bucket_is_a_whole_number_of_rows():
    assert timewindow.bucket_for(timedelta(days=7), 500) == timedelta(minutes=30)  # 1008 rows -> 3 per bucket
    assert timewindow.bucket_for(timedelta(hours=2), 500) == timedelta(minutes=10)  # never below one row


def test_window_is_anchored_on_and_clipped_to_the_cursor():
    w = timewindow.resolve(CURSOR, None, None, 500)
    assert w.end == CURSOR and w.start == CURSOR - timewindow.DEFAULT_SPAN
    # Rows after the cursor are left over from the previous replay cycle: never returned.
    later = timewindow.resolve(CURSOR, CURSOR - timedelta(days=1), CURSOR + timedelta(days=3), 100)
    assert later.end == CURSOR


def test_window_reads_naive_timestamps_as_utc():
    w = timewindow.resolve(CURSOR, datetime(2019, 1, 1), None, 100)
    assert w.start == datetime(2019, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [
        (CURSOR, None, 422),  # empty window
        (CURSOR - timedelta(days=500), None, 422),  # too long
    ],
)
def test_window_rejects_bad_ranges(start, end, code):
    with pytest.raises(HTTPException) as exc:
        timewindow.resolve(CURSOR, start, end, 100)
    assert exc.value.status_code == code


def test_window_before_replay_start_is_a_conflict():
    with pytest.raises(HTTPException) as exc:
        timewindow.resolve(None, None, None, 100)
    assert exc.value.status_code == 409


def test_password_hash_roundtrip_and_unknown_user():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)  # unknown user: checked against a dummy hash


def test_token_roundtrip_and_rejections():
    token, ttl = create_token("ops.engineer", Role.ENGINEER)
    claims = decode_token(token)
    assert claims["sub"] == "ops.engineer" and claims["role"] == "engineer" and ttl > 0

    expired, _ = create_token("ops.engineer", Role.ENGINEER, ttl=timedelta(seconds=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(expired)
    forged = jwt.encode(
        {"sub": "x", "iss": "wtpdm", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "another-secret-that-is-long-enough-000000",
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(forged)


def test_roles_are_ordered():
    engineer = Principal("e", "E", Role.ENGINEER)
    assert engineer.has(Role.VIEWER) and engineer.has(Role.ENGINEER) and not engineer.has(Role.ADMIN)


def test_version_comparison_knows_metric_direction(monkeypatch):
    versions = {
        "1": {
            "model": "m",
            "metrics": {"care_style_score": 0.60, "false_alarm_events": 3, "anomaly_events": 11},
        },
        "2": {
            "model": "m",
            "metrics": {"care_style_score": 0.65, "false_alarm_events": 4, "anomaly_events": 11},
        },
    }
    monkeypatch.setattr(models_service, "version", lambda farm, v: versions[v])
    rows = {r["metric"]: r for r in models_service.compare("A", "1", "2")["metrics"]}
    assert rows["care_style_score"]["better"] == "2"  # higher is better
    assert rows["false_alarm_events"]["better"] == "1"  # lower is better
    assert rows["anomaly_events"]["better"] is None  # a count of the evaluation set, not a quality
