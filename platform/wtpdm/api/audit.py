"""Audit trail entries written by API actions (same table the services write to)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from wtpdm.db.models import AuditLog


def record(s: Session, actor: str, action: str, entity: str, entity_id: str | None, **details: Any) -> None:
    s.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, details=details or None))
