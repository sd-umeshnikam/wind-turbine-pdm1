"""Alert engine: turns the scorer's persistent alarms into a work queue.

Rules (all times are the turbine's data time):
- raise      an alarm (score above threshold for 2 h) on a turbine without an active
             (open or acknowledged) alert creates one. One active alert per turbine: the
             detector works at turbine level and sub-part attribution is a contributing
             signal, not a diagnosis, so per-component alerts would only duplicate it.
- severity   from calibrated turbine health (50 = alarm level, each halving one more step
             of the same size beyond it): >= 50 low (unusual combination, no single
             sub-part beyond its normal range), 25-50 medium, 10-25 high, < 10 critical;
             one level higher once the condition has persisted 48 h. It never drops while
             the alert is active.
- clear      hysteresis: the condition counts as returned to normal only after 6 h with
             the score below 90% of the threshold. Clearing does NOT close the alert: an
             engineer resolves it. A breach after clearing re-activates the same alert.
- cool-down  after an engineer resolves an alert, the same turbine raises a new one within
             24 h only if it is more severe than the resolved one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from wtpdm.db.models import Alert, AlertNote, AlertStatus, AuditLog, Component, Severity
from wtpdm.db.session import session_scope
from wtpdm.logging import get_logger
from wtpdm.realtime.scorer import ScoredBatch

log = get_logger("alerts")
ACTOR = "system:alert-engine"
CLEAR_ROWS = 36  # 6 h
CLEAR_RATIO = 0.9
ESCALATE_AFTER = timedelta(hours=48)
COOLDOWN = timedelta(hours=24)
SEVERITY_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
DETECTOR_LABEL = {
    "threshold_baseline": "Health-score threshold",
    "isolation_forest": "Isolation Forest",
    "supervised_lgbm": "Early-warning classifier",
}


def rank(severity: Severity) -> int:
    return SEVERITY_ORDER.index(severity)


def severity_for(health: float, active_for: timedelta) -> Severity:
    if health < 10:
        level = 3
    elif health < 25:
        level = 2
    elif health < 50:
        level = 1
    else:
        level = 0
    if active_for >= ESCALATE_AFTER:
        level = min(level + 1, 3)
    return SEVERITY_ORDER[level]


def condition_cleared(detector_scores: np.ndarray, threshold: float) -> bool:
    tail = detector_scores[-CLEAR_ROWS:]
    return len(tail) >= CLEAR_ROWS and bool(np.all(np.nan_to_num(tail, nan=np.inf) < CLEAR_RATIO * threshold))


def _ts(value) -> datetime:
    return pd.Timestamp(value).to_pydatetime()


class AlertEngine:
    def __init__(self) -> None:
        self._component_names: dict[str, str] | None = None

    def component_name(self, s, code: str) -> str:
        if self._component_names is None:
            self._component_names = {c.code: c.name for c in s.scalars(select(Component))}
        return self._component_names.get(code, code)

    def process(self, batch: ScoredBatch) -> None:
        summary = batch.summary
        turbines = summary.loc[summary["is_new"], "turbine_id"].unique().tolist()
        if not turbines:
            return
        threshold = batch.model.bundle.threshold
        with session_scope() as s:
            active = {
                a.turbine_id: a
                for a in s.scalars(
                    select(Alert).where(
                        Alert.turbine_id.in_(turbines),
                        Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                    )
                )
            }
            for turbine_id in turbines:
                rows = summary[summary["turbine_id"] == turbine_id]
                new = rows[rows["is_new"]]
                alert = active.get(turbine_id)
                if new["alarm"].any():
                    self._on_alarm(s, batch, turbine_id, rows, new, alert)
                elif (
                    alert is not None
                    and alert.condition_active
                    and condition_cleared(rows["detector_score"].to_numpy(np.float64), threshold)
                ):
                    self._on_clear(s, alert, new)

    # ---------------------------------------------------------------- transitions

    def _on_alarm(self, s, batch: ScoredBatch, turbine_id: str, rows, new, alert: Alert | None) -> None:
        bundle = batch.model.bundle
        alarm_rows = new[new["alarm"]]
        last = alarm_rows.iloc[-1]
        last_ts = _ts(last["ts"])
        health = float(np.nanmin(alarm_rows["health"]))
        drivers = bundle.drivers(batch.residual_z.loc[last.name])
        worst = last["worst_subcomponent"] if isinstance(last["worst_subcomponent"], str) else None

        if alert is None:
            first_ts = _ts(alarm_rows.iloc[0]["ts"])
            severity = severity_for(health, timedelta(0))
            if worst is None or self._cooling_down(s, turbine_id, first_ts, severity):
                return
            component = worst.split(".")[0]
            name = self.component_name(s, component)
            detector = DETECTOR_LABEL.get(bundle.detector_name, bundle.detector_name)
            signals = ", ".join(f"{d['description']} (z {d['z']:+.1f})" for d in drivers)
            alert = Alert(
                turbine_id=turbine_id,
                component_code=component,
                subcomponent_code=worst,
                severity=severity,
                status=AlertStatus.OPEN,
                title=f"{name}: abnormal behaviour on {turbine_id}",
                message=(
                    f"Turbine health {health:.0f}/100. {detector}"
                    f" score {float(last['detector_score']):.3g} has stayed above its alarm threshold"
                    f" {bundle.threshold:.3g} for at least 2 h. Largest deviations from expected"
                    f" behaviour: {signals}. Sub-part attribution is a contributing signal, not a"
                    " confirmed diagnosis."
                ),
                drivers=drivers,
                model_version=batch.model.label,
                data_ts=first_ts,
                last_data_ts=last_ts,
                condition_active=True,
            )
            s.add(alert)
            s.flush()
            self._audit(s, "alert.raise", alert, {"severity": severity.value, "health": round(health, 1)})
            log.info("alert raised", turbine=turbine_id, severity=severity.value, component=component)
            return

        alert.last_data_ts = last_ts
        if not alert.condition_active:
            alert.condition_active, alert.cleared_at = True, None
            self._note(s, alert, f"Condition re-occurred at data time {last_ts:%Y-%m-%d %H:%M}.")
            self._audit(s, "alert.reoccur", alert, {})
        active_for = max(last_ts - _ts(alert.data_ts), timedelta(0)) if alert.data_ts else timedelta(0)
        severity = severity_for(health, active_for)
        if rank(severity) > rank(alert.severity):
            old = alert.severity
            alert.severity, alert.drivers = severity, drivers
            self._note(
                s,
                alert,
                f"Escalated {old.value} -> {severity.value}: health {health:.0f}/100,"
                f" condition active for {active_for.total_seconds() / 3600:.0f} h.",
            )
            self._audit(s, "alert.escalate", alert, {"from": old.value, "to": severity.value})
            log.info("alert escalated", turbine=turbine_id, severity=severity.value)

    def _on_clear(self, s, alert: Alert, new) -> None:
        alert.condition_active, alert.cleared_at = False, datetime.now(UTC)
        self._note(
            s,
            alert,
            f"Condition returned to normal at data time {_ts(new['ts'].iloc[-1]):%Y-%m-%d %H:%M}"
            f" ({CLEAR_ROWS // 6} h below {CLEAR_RATIO:.0%} of the alarm threshold)."
            " The alert stays open until an engineer resolves it.",
        )
        self._audit(s, "alert.clear", alert, {})

    def _cooling_down(self, s, turbine_id: str, breach_ts: datetime, severity: Severity) -> bool:
        recent = s.scalars(
            select(Alert)
            .where(Alert.turbine_id == turbine_id, Alert.status == AlertStatus.RESOLVED)
            .order_by(Alert.resolved_at.desc())
            .limit(1)
        ).first()
        if recent is None or recent.last_data_ts is None:
            return False
        # abs(): the replay loops, so data time can restart before the resolved alert.
        within = abs(breach_ts - recent.last_data_ts) < COOLDOWN
        return within and rank(severity) <= rank(recent.severity)

    @staticmethod
    def _note(s, alert: Alert, body: str) -> None:
        s.add(AlertNote(alert_id=alert.id, author=ACTOR, body=body))

    @staticmethod
    def _audit(s, action: str, alert: Alert, details: dict) -> None:
        s.add(
            AuditLog(
                actor=ACTOR,
                action=action,
                entity="alert",
                entity_id=str(alert.id),
                details={"turbine": alert.turbine_id, **details},
            )
        )
