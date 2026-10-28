"""Server-sent events for live consoles.

Event types:
- `hello`  once, on connect
- `fleet`  every few seconds: each turbine's health, alarm, cursor and active alert
- `alert`, `model`, `retrain`, `user` ...: every audit-log entry as it is written (alert
  raised/escalated/acknowledged, model registered/promoted, retrain requested/finished),
  named after its entity; login events go to admins only
- `drift`  when a drift check completes: the per-farm status

Browsers' EventSource cannot send headers, so the token may also come as `access_token`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from wtpdm.api import live, schemas
from wtpdm.api.deps import db
from wtpdm.api.routers.mlops import drift_snapshot, feature_names
from wtpdm.api.security import Principal, oauth2, principal_from_token
from wtpdm.db.models import AuditLog, DriftReport, Farm, Role
from wtpdm.db.session import session_scope

router = APIRouter(tags=["stream"])
POLL_SECONDS = 2.0
FLEET_SECONDS = 10.0
MAX_EVENTS_PER_POLL = 200
ENTITY_EVENT = {"retrain_job": "retrain"}


def _json(payload) -> str:
    return json.dumps(payload, default=str)


def _audit_since(after: int, include_auth: bool) -> list[AuditLog]:
    with session_scope() as s:
        q = select(AuditLog).where(AuditLog.id > after)
        if not include_auth:
            q = q.where(~AuditLog.action.startswith("auth."))
        return list(s.scalars(q.order_by(AuditLog.id).limit(MAX_EVENTS_PER_POLL)))


def _last_audit_id() -> int:
    with session_scope() as s:
        return s.scalar(select(func.max(AuditLog.id))) or 0


def _last_drift() -> datetime | None:
    with session_scope() as s:
        return s.scalar(select(func.max(DriftReport.ts)))


def _drift() -> list[dict]:
    with session_scope() as s:
        names = feature_names(s)
        return [
            {"farm_id": f, "status": snap.status, "checked_at": snap.checked_at}
            for f in s.scalars(select(Farm.id).order_by(Farm.id))
            for snap in [drift_snapshot(s, f, names)]
        ]


def _fleet() -> list[dict]:
    with session_scope() as s:
        return [
            {
                "id": t.id,
                "health": t.health,
                "alarm": t.alarm,
                "cursor_ts": t.replay.cursor_ts if t.replay else None,
                "cycle": t.replay.cycle if t.replay else None,
                "worst_subcomponent": t.worst_subcomponent,
                "alert": {
                    "id": t.active_alert.id,
                    "severity": t.active_alert.severity.value,
                    "status": t.active_alert.status.value,
                }
                if t.active_alert
                else None,
            }
            for t in live.fleet(s)
        ]


async def events(request: Request, user: Principal):
    include_auth = user.has(Role.ADMIN)
    cursor = await run_in_threadpool(_last_audit_id)
    drift_seen = await run_in_threadpool(_last_drift)
    yield {
        "event": "hello",
        "data": _json({"user": user.username, "audit_cursor": cursor, "server_time": datetime.now(UTC)}),
    }
    next_fleet = 0.0
    loop = asyncio.get_running_loop()
    while not await request.is_disconnected():
        if loop.time() >= next_fleet:
            yield {"event": "fleet", "data": _json(await run_in_threadpool(_fleet))}
            next_fleet = loop.time() + FLEET_SECONDS
        for row in await run_in_threadpool(_audit_since, cursor, include_auth):
            cursor = row.id
            yield {
                "event": ENTITY_EVENT.get(row.entity, row.entity),
                "id": str(row.id),
                "data": _json(schemas.AuditOut.model_validate(row).model_dump()),
            }
        drift_now = await run_in_threadpool(_last_drift)
        if drift_now != drift_seen:
            drift_seen = drift_now
            yield {"event": "drift", "data": _json(await run_in_threadpool(_drift))}
        await asyncio.sleep(POLL_SECONDS)


@router.get("/stream", summary="Live updates (server-sent events)")
def stream(
    request: Request,
    access_token: str | None = Query(default=None, description="For EventSource clients"),
    header_token: str | None = Depends(oauth2),
    s: Session = Depends(db),
):
    user = principal_from_token(header_token or access_token, s)
    return EventSourceResponse(events(request, user), ping=15)
