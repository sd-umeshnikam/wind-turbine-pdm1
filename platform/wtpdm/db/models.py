"""Relational model of the platform (PostgreSQL + TimescaleDB).

Three groups:
- Asset catalog: farm -> turbine, component -> subcomponent, sensor (per farm, with real
  description/unit, mapped to a subcomponent or marked as an operating condition).
- Operations: events (CARE event windows), telemetry and health_score (hypertables),
  alerts with a real workflow (open -> acknowledged -> resolved), notes, audit log.
- MLOps: model deployments (champion/challenger), drift reports, retrain jobs.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, REAL, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JsonType = JSON().with_variant(JSONB(), "postgresql")


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Persist enum VALUES ("monitored"), not member names ("MONITORED"), so SQL and
    other services can filter on the same strings the API returns."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- asset catalog


class Farm(Base):
    __tablename__ = "farm"
    id: Mapped[str] = mapped_column(String(8), primary_key=True)  # "A"
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    turbines: Mapped[list[Turbine]] = relationship(back_populates="farm")


class Turbine(Base):
    __tablename__ = "turbine"
    __table_args__ = (UniqueConstraint("farm_id", "asset_id"),)
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # "A-1"
    farm_id: Mapped[str] = mapped_column(ForeignKey("farm.id"))
    asset_id: Mapped[int] = mapped_column(Integer)  # id in the source dataset (repeats across farms)
    name: Mapped[str] = mapped_column(String(64))
    farm: Mapped[Farm] = relationship(back_populates="turbines")


class Component(Base):
    __tablename__ = "component"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)  # "gearbox"
    name: Mapped[str] = mapped_column(String(64))
    subcomponents: Mapped[list[Subcomponent]] = relationship(back_populates="component")


class Subcomponent(Base):
    __tablename__ = "subcomponent"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)  # "gearbox.hss_bearing"
    component_code: Mapped[str] = mapped_column(ForeignKey("component.code"))
    name: Mapped[str] = mapped_column(String(96))
    component: Mapped[Component] = relationship(back_populates="subcomponents")


class SensorRole(enum.StrEnum):
    MONITORED = "monitored"  # health of a subcomponent
    CONDITION = "condition"  # operating condition (wind, power, ambient...) used as NBM input
    OTHER = "other"


class Sensor(Base):
    __tablename__ = "sensor"
    __table_args__ = (UniqueConstraint("farm_id", "code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farm.id"))
    code: Mapped[str] = mapped_column(String(32))  # "sensor_11"
    description: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str | None] = mapped_column(String(24))
    statistics: Mapped[list[str]] = mapped_column(JsonType)  # ["average","min","max","std_dev"]
    is_angle: Mapped[bool] = mapped_column(Boolean, default=False)
    is_counter: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[SensorRole] = mapped_column(pg_enum(SensorRole, "sensor_role"))
    subcomponent_code: Mapped[str | None] = mapped_column(ForeignKey("subcomponent.code"))
    condition_kind: Mapped[str | None] = mapped_column(String(32))  # "power", "wind_speed", ...


# ---------------------------------------------------------------- operations


class EventLabel(enum.StrEnum):
    ANOMALY = "anomaly"
    NORMAL = "normal"


class Event(Base):
    """A CARE event window: one turbine's history leading into a labelled outcome."""

    __tablename__ = "event"
    __table_args__ = (UniqueConstraint("farm_id", "source_event_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farm.id"))
    source_event_id: Mapped[int] = mapped_column(Integer)
    turbine_id: Mapped[str] = mapped_column(ForeignKey("turbine.id"))
    label: Mapped[EventLabel] = mapped_column(pg_enum(EventLabel, "event_label"))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    component_code: Mapped[str | None] = mapped_column(ForeignKey("component.code"))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prediction_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_rows: Mapped[int] = mapped_column(Integer)


class Telemetry(Base):
    """Long-format SCADA readings (10-minute averages). TimescaleDB hypertable on ts."""

    __tablename__ = "telemetry"
    turbine_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    sensor_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[float] = mapped_column(REAL)


class HealthScore(Base):
    """Online scoring output per turbine x subcomponent. TimescaleDB hypertable on ts."""

    __tablename__ = "health_score"
    turbine_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    subcomponent_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    health: Mapped[float] = mapped_column(Float)  # 0..100
    residual_z: Mapped[float | None] = mapped_column(Float)
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    fault_probability: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(64))
    alarm: Mapped[bool | None] = mapped_column(Boolean)  # turbine-level row only


class AlertStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Severity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    turbine_id: Mapped[str] = mapped_column(ForeignKey("turbine.id"), index=True)
    component_code: Mapped[str] = mapped_column(ForeignKey("component.code"))
    subcomponent_code: Mapped[str | None] = mapped_column(ForeignKey("subcomponent.code"))
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"))
    status: Mapped[AlertStatus] = mapped_column(
        pg_enum(AlertStatus, "alert_status"), default=AlertStatus.OPEN, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    drivers: Mapped[list[dict] | None] = mapped_column(JsonType)  # top contributing sensors
    model_version: Mapped[str | None] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    data_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # replay time of breach
    assignee: Mapped[str | None] = mapped_column(String(64))
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Return-to-normal does not close an alert: the engineer resolves it.
    condition_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_data_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last breach seen
    notes: Mapped[list[AlertNote]] = relationship(back_populates="alert", order_by="AlertNote.created_at")


class AlertNote(Base):
    __tablename__ = "alert_note"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert.id", ondelete="CASCADE"))
    author: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    alert: Mapped[Alert] = relationship(back_populates="notes")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(64))  # username or "system:<service>"
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JsonType)


class ReplayState(Base):
    """Cursor of the real-SCADA replay per turbine."""

    __tablename__ = "replay_state"
    turbine_id: Mapped[str] = mapped_column(ForeignKey("turbine.id"), primary_key=True)
    cursor_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="idle")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cycle: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source_event_id: Mapped[int | None] = mapped_column(Integer)  # CARE event of the current row
    operating_status: Mapped[int | None] = mapped_column(SmallInteger)  # 0 normal .. 5 other
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------- MLOps


class ModelDeployment(Base):
    """Which registered model version serves a farm x component, and why."""

    __tablename__ = "model_deployment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(16))
    alias: Mapped[str] = mapped_column(String(16))  # champion | challenger | retired
    farm_id: Mapped[str] = mapped_column(ForeignKey("farm.id"))
    # NULL = farm-level model (the health bundle covers every component of the farm)
    component_code: Mapped[str | None] = mapped_column(ForeignKey("component.code"))
    validation: Mapped[str] = mapped_column(String(32))  # validated | unvalidated | failed_gate
    metrics: Mapped[dict | None] = mapped_column(JsonType)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    promoted_by: Mapped[str] = mapped_column(String(64))


class DriftReport(Base):
    __tablename__ = "drift_report"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farm.id"))
    component_code: Mapped[str | None] = mapped_column(ForeignKey("component.code"))
    metric: Mapped[str] = mapped_column(String(32))  # psi_input | residual_shift | alert_rate
    feature: Mapped[str | None] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    breached: Mapped[bool] = mapped_column(Boolean)


class RetrainJob(Base):
    __tablename__ = "retrain_job"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16))  # schedule | drift | manual
    status: Mapped[str] = mapped_column(
        String(16), default="queued", index=True
    )  # queued|running|succeeded|failed
    requested_by: Mapped[str] = mapped_column(String(64))
    scope: Mapped[dict | None] = mapped_column(JsonType)  # {"farm": "C", "component": "pitch"}
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JsonType)  # mlflow run ids, comparison, promotion


class Role(enum.StrEnum):
    VIEWER = "viewer"
    ENGINEER = "engineer"
    ADMIN = "admin"


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(96))
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(pg_enum(Role, "user_role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
