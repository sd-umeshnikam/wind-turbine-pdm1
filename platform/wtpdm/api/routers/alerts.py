"""Alert work queue: list/filter, detail with notes and audit trail, and the engineer
workflow open -> acknowledged -> resolved (plus assign and notes).

The alert engine updates the same rows (escalation, clear, re-occur), so every transition
locks the alert row first; a transition that is no longer valid returns 409.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from wtpdm.api import audit, schemas
from wtpdm.api.deps import db
from wtpdm.api.live import ACTIVE, pairs
from wtpdm.api.security import Principal, engineer, viewer
from wtpdm.db.models import Alert, AlertNote, AlertStatus, AppUser, AuditLog, Role, Severity, Turbine

router = APIRouter(prefix="/alerts", tags=["alerts"])

SORTS: dict[str, Any] = {
    "-opened_at": Alert.opened_at.desc(),
    "opened_at": Alert.opened_at.asc(),
    "-updated_at": Alert.updated_at.desc(),
    "-severity": Alert.severity.desc(),  # enum order: low < medium < high < critical
}


def _out(alert: Alert, farm_id: str | None = None) -> schemas.AlertOut:
    out = schemas.AlertOut.model_validate(alert)
    out.farm_id = farm_id or alert.turbine_id.split("-")[0]
    return out


def _locked(s: Session, alert_id: uuid.UUID) -> Alert:
    alert = s.scalars(select(Alert).where(Alert.id == alert_id).with_for_update()).first()
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No alert {alert_id}")
    return alert


def _require_status(alert: Alert, allowed: tuple[AlertStatus, ...], action: str) -> None:
    if alert.status not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Cannot {action} an alert that is {alert.status.value}"
        )


def _note(s: Session, alert: Alert, author: str, body: str) -> None:
    s.add(AlertNote(alert_id=alert.id, author=author, body=body))


def _detail(s: Session, alert: Alert) -> schemas.AlertDetail:
    s.flush()
    s.refresh(alert)
    trail = s.scalars(
        select(AuditLog)
        .where(AuditLog.entity == "alert", AuditLog.entity_id == str(alert.id))
        .order_by(AuditLog.ts, AuditLog.id)
    ).all()
    return schemas.AlertDetail(
        **_out(alert).model_dump(),
        notes=[schemas.NoteOut.model_validate(n) for n in alert.notes],
        audit=[schemas.AuditOut.model_validate(a) for a in trail],
    )


@router.get("", response_model=schemas.AlertPage)
def list_alerts(
    status_: list[AlertStatus] | None = Query(default=None, alias="status"),
    severity: list[Severity] | None = Query(default=None),
    farm: str | None = Query(default=None, pattern=r"^[ABC]$"),
    turbine: str | None = None,
    component: str | None = None,
    assignee: str | None = Query(default=None, description="Username, or `none` for unassigned"),
    active: bool | None = Query(default=None, description="true = open or acknowledged"),
    condition_active: bool | None = None,
    q: str | None = Query(default=None, max_length=100, description="Search title and message"),
    sort: Literal["-opened_at", "opened_at", "-updated_at", "-severity"] = "-opened_at",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    query = select(Alert, Turbine.farm_id).join(Turbine, Turbine.id == Alert.turbine_id)
    if status_:
        query = query.where(Alert.status.in_(status_))
    if active is not None:
        query = query.where(Alert.status.in_(ACTIVE) if active else Alert.status == AlertStatus.RESOLVED)
    if severity:
        query = query.where(Alert.severity.in_(severity))
    if farm:
        query = query.where(Turbine.farm_id == farm)
    if turbine:
        query = query.where(Alert.turbine_id == turbine)
    if component:
        query = query.where(Alert.component_code == component)
    if assignee == "none":
        query = query.where(Alert.assignee.is_(None))
    elif assignee:
        query = query.where(Alert.assignee == assignee)
    if condition_active is not None:
        query = query.where(Alert.condition_active == condition_active)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Alert.title.ilike(like), Alert.message.ilike(like)))
    total = s.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = s.execute(query.order_by(SORTS[sort], Alert.id).limit(limit).offset(offset)).all()
    return schemas.AlertPage(total=total, items=[_out(a, farm_id) for a, farm_id in rows])


@router.get("/summary", response_model=schemas.AlertSummary)
def summary(_: Principal = Depends(viewer), s: Session = Depends(db)):
    by_status = pairs(s.execute(select(Alert.status, func.count()).group_by(Alert.status)).all())
    active = select(Alert).where(Alert.status.in_(ACTIVE)).subquery()
    by_severity = pairs(s.execute(select(active.c.severity, func.count()).group_by(active.c.severity)).all())
    by_farm = pairs(
        s.execute(
            select(Turbine.farm_id, func.count())
            .join(active, active.c.turbine_id == Turbine.id)
            .group_by(Turbine.farm_id)
        ).all()
    )
    unassigned = s.scalar(select(func.count()).select_from(active).where(active.c.assignee.is_(None))) or 0
    return schemas.AlertSummary(
        by_status={st.value: by_status.get(st, 0) for st in AlertStatus},
        by_severity={sv.value: by_severity.get(sv, 0) for sv in Severity},
        by_farm=by_farm,
        unassigned=unassigned,
    )


@router.get("/{alert_id}", response_model=schemas.AlertDetail)
def get_alert(alert_id: uuid.UUID, _: Principal = Depends(viewer), s: Session = Depends(db)):
    alert = s.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No alert {alert_id}")
    return _detail(s, alert)


@router.post("/{alert_id}/acknowledge", response_model=schemas.AlertDetail)
def acknowledge(
    alert_id: uuid.UUID,
    body: schemas.AcknowledgeIn | None = None,
    user: Principal = Depends(engineer),
    s: Session = Depends(db),
):
    alert = _locked(s, alert_id)
    _require_status(alert, (AlertStatus.OPEN,), "acknowledge")
    alert.status, alert.acknowledged_by = AlertStatus.ACKNOWLEDGED, user.username
    if alert.assignee is None:
        alert.assignee = user.username  # whoever acknowledges owns it until reassigned
    if body and body.note:
        _note(s, alert, user.username, body.note)
    audit.record(s, user.username, "alert.acknowledge", "alert", str(alert.id), turbine=alert.turbine_id)
    return _detail(s, alert)


@router.post("/{alert_id}/assign", response_model=schemas.AlertDetail)
def assign(
    alert_id: uuid.UUID, body: schemas.AssignIn, user: Principal = Depends(engineer), s: Session = Depends(db)
):
    alert = _locked(s, alert_id)
    _require_status(alert, ACTIVE, "assign")
    if body.assignee is not None:
        owner = s.scalars(select(AppUser).where(AppUser.username == body.assignee)).first()
        if owner is None or not owner.is_active or owner.role == Role.VIEWER:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{body.assignee} is not an active engineer or admin"
            )
    previous, alert.assignee = alert.assignee, body.assignee
    audit.record(
        s,
        user.username,
        "alert.assign",
        "alert",
        str(alert.id),
        turbine=alert.turbine_id,
        previous=previous,
        assignee=body.assignee,
    )
    return _detail(s, alert)


@router.post("/{alert_id}/resolve", response_model=schemas.AlertDetail)
def resolve(
    alert_id: uuid.UUID,
    body: schemas.ResolveIn,
    user: Principal = Depends(engineer),
    s: Session = Depends(db),
):
    alert = _locked(s, alert_id)
    _require_status(alert, ACTIVE, "resolve")
    alert.status, alert.resolved_by, alert.resolved_at = (
        AlertStatus.RESOLVED,
        user.username,
        datetime.now(UTC),
    )
    _note(s, alert, user.username, f"Resolution: {body.resolution}")
    audit.record(
        s,
        user.username,
        "alert.resolve",
        "alert",
        str(alert.id),
        turbine=alert.turbine_id,
        condition_active=alert.condition_active,
    )
    return _detail(s, alert)


@router.post("/{alert_id}/notes", response_model=schemas.AlertDetail, status_code=status.HTTP_201_CREATED)
def add_note(
    alert_id: uuid.UUID, body: schemas.NoteIn, user: Principal = Depends(engineer), s: Session = Depends(db)
):
    alert = _locked(s, alert_id)
    _note(s, alert, user.username, body.body)
    audit.record(s, user.username, "alert.note", "alert", str(alert.id), turbine=alert.turbine_id)
    return _detail(s, alert)
