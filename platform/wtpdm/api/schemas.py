"""Request and response models of the Platform API (the OpenAPI contract)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from wtpdm.db.models import AlertStatus, Role, Severity

# CARE status_type_id: what the turbine was doing at the replayed row.
OPERATING_STATUS = {
    0: "normal operation",
    1: "derated",
    2: "idling",
    3: "service",
    4: "downtime",
    5: "other",
}


class Schema(BaseModel):
    # Fields such as `model_version` are domain names, not pydantic internals.
    model_config = ConfigDict(protected_namespaces=())


class ORM(Schema):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


# ---------------------------------------------------------------- auth & users


class UserOut(ORM):
    username: str
    display_name: str
    role: Role
    is_active: bool
    last_seen_at: datetime | None = None
    created_at: datetime | None = None


class TokenOut(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreate(Schema):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=96)
    password: str = Field(min_length=12, max_length=128)
    role: Role = Role.VIEWER


class UserUpdate(Schema):
    display_name: str | None = Field(default=None, min_length=1, max_length=96)
    password: str | None = Field(default=None, min_length=12, max_length=128)
    role: Role | None = None
    is_active: bool | None = None


class DirectoryEntry(ORM):
    username: str
    display_name: str
    role: Role


# ---------------------------------------------------------------- fleet & turbines


class ReplayOut(Schema):
    cursor_ts: datetime | None
    cycle: int
    position: int
    total_rows: int
    progress: float  # share of the turbine's timeline replayed in this cycle
    source_event_id: int | None
    operating_status: int | None
    operating_status_label: str | None
    updated_at: datetime | None


class AlertBrief(ORM):
    id: uuid.UUID
    severity: Severity
    status: AlertStatus
    title: str
    component_code: str
    subcomponent_code: str | None
    condition_active: bool
    opened_at: datetime


class TurbineSummary(Schema):
    id: str
    farm_id: str
    name: str
    health: float | None  # calibrated turbine health 0-100 at the cursor
    alarm: bool | None
    worst_subcomponent: str | None
    components: dict[str, float]  # component -> worst sub-part health
    model_version: str | None
    replay: ReplayOut | None
    active_alert: AlertBrief | None


class FleetKpis(Schema):
    turbines: int
    reporting: int  # turbines with a health score at their cursor
    in_alarm: int
    mean_health: float | None
    active_alerts: dict[str, int]  # severity -> count
    unacknowledged: int


class FleetOut(Schema):
    kpis: FleetKpis
    turbines: list[TurbineSummary]
    replay_speed: float


class FarmOut(Schema):
    id: str
    name: str
    description: str | None
    turbines: int
    sensors: int
    events: dict[str, int]  # label -> count
    champion: str | None
    active_alerts: int


class SensorOut(ORM):
    code: str
    description: str
    unit: str | None
    role: str
    subcomponent_code: str | None
    condition_kind: str | None


class SubpartHealth(Schema):
    code: str
    name: str
    health: float | None
    residual_z: float | None
    ts: datetime | None
    sensors: list[SensorOut]


class ComponentHealth(Schema):
    code: str
    name: str
    health: float | None  # worst sub-part
    subparts: list[SubpartHealth]


class TurbineDetail(TurbineSummary):
    asset_id: int
    anomaly_score: float | None
    components_tree: list[ComponentHealth]


class SeriesPoint(Schema):
    ts: datetime
    avg: float | None
    min: float | None
    max: float | None


class HealthSeries(Schema):
    subcomponent: str
    name: str
    points: list[SeriesPoint]
    alarm_ts: list[datetime] = []  # turbine series only: buckets with an alarm


class SensorSeries(Schema):
    code: str
    description: str
    unit: str | None
    points: list[SeriesPoint]


class WindowOut(Schema):
    start: datetime
    end: datetime
    bucket_seconds: int


class HealthSeriesOut(Schema):
    turbine_id: str
    window: WindowOut
    series: list[HealthSeries]


class TelemetryOut(Schema):
    turbine_id: str
    window: WindowOut
    series: list[SensorSeries]


class ExpectedPoint(Schema):
    ts: datetime
    actual: float | None
    expected: float | None
    residual_z: float | None


class ExpectedOut(Schema):
    turbine_id: str
    sensor: SensorOut
    model_version: str
    nbm_candidate: str  # the regressor selected for this sensor
    window: WindowOut
    points: list[ExpectedPoint]


class EventOut(ORM):
    id: int
    farm_id: str
    source_event_id: int
    turbine_id: str
    label: str
    description: str | None
    category: str | None
    component_code: str | None
    window_start: datetime
    prediction_start: datetime
    event_start: datetime
    event_end: datetime
    n_rows: int


# ---------------------------------------------------------------- alerts


class NoteOut(ORM):
    id: int
    author: str
    body: str
    created_at: datetime


class AuditOut(ORM):
    id: int
    ts: datetime
    actor: str
    action: str
    entity: str
    entity_id: str | None
    details: dict[str, Any] | None


class AlertOut(ORM):
    id: uuid.UUID
    turbine_id: str
    farm_id: str | None = None
    component_code: str
    subcomponent_code: str | None
    severity: Severity
    status: AlertStatus
    title: str
    message: str
    drivers: list[dict[str, Any]] | None
    model_version: str | None
    opened_at: datetime
    updated_at: datetime
    data_ts: datetime | None
    last_data_ts: datetime | None
    condition_active: bool
    cleared_at: datetime | None
    assignee: str | None
    acknowledged_by: str | None
    resolved_by: str | None
    resolved_at: datetime | None


class AlertDetail(AlertOut):
    notes: list[NoteOut]
    audit: list[AuditOut]


class AlertPage(Schema):
    total: int
    items: list[AlertOut]


class AlertSummary(Schema):
    by_status: dict[str, int]
    by_severity: dict[str, int]  # active alerts only
    by_farm: dict[str, int]  # active alerts only
    unassigned: int


class NoteIn(Schema):
    body: str = Field(min_length=1, max_length=4000)


class AcknowledgeIn(Schema):
    note: str | None = Field(default=None, max_length=4000)


class AssignIn(Schema):
    assignee: str | None = Field(description="Username; null unassigns")


class ResolveIn(Schema):
    resolution: str = Field(min_length=3, max_length=4000, description="What was found and done")


# ---------------------------------------------------------------- MLOps


class RetrainIn(Schema):
    farm: str = Field(pattern=r"^[ABC]$")
    reason: str = Field(min_length=3, max_length=500)


class RetrainJobOut(ORM):
    id: int
    trigger: str
    status: str
    requested_by: str
    scope: dict[str, Any] | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None


class DriftRow(Schema):
    metric: str
    feature: str | None
    feature_description: str | None
    value: float
    threshold: float
    breached: bool
    triggers_retrain: bool


class DriftSnapshot(Schema):
    farm_id: str
    checked_at: datetime | None
    status: str  # ok | warning (informational breach) | drift (retrain trigger breached) | no_data
    rows: list[DriftRow]


class DeploymentOut(ORM):
    id: int
    model_name: str
    version: str
    alias: str
    farm_id: str
    validation: str
    metrics: dict[str, Any] | None
    promoted_at: datetime
    promoted_by: str
