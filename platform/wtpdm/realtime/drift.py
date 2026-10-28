"""Drift monitor: is the live stream still the world the champion model was trained on?

Per farm, the recent replayed window (last `drift_window_days` of each turbine's data
time) is compared with a reference profile of the champion's training data:

metric            what                                          threshold  triggers retrain
psi_input         PSI of each operating condition vs training   0.25       no (seasonality)
out_of_support    share of condition values outside the         0.05       yes
                  training 0.5-99.5% range (normal behaviour
                  models extrapolate badly there)
residual_shift    median turbine score, recent / reference      1.5        yes
alert_rate        share of rows in alarm                        3x ref,    no (faults are
                                                                >= 1%      expected to raise it)

A 30-day window is naturally narrower than a training history of a year or more, so input
PSI flags seasonality as much as real change; it is reported for context, and only the
two metrics that indicate the model itself is no longer valid trigger a retrain.

The reference is the champion's normal-operation profile (`wtpdm.realtime.champion`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from wtpdm.db.models import DriftReport
from wtpdm.db.session import session_scope
from wtpdm.logging import get_logger
from wtpdm.realtime.champion import TURBINE, LoadedModel, load_profile, proportions

log = get_logger("drift")
MIN_RECENT_ROWS = 1000
PSI_THRESHOLD = 0.25
OUT_OF_SUPPORT_THRESHOLD = 0.05
RESIDUAL_SHIFT_THRESHOLD = 1.5
ALERT_RATE_FACTOR = 3.0
ALERT_RATE_FLOOR = 0.01
EPS = 1e-4


# ---------------------------------------------------------------- statistics


def psi(reference: dict, recent: np.ndarray) -> float:
    v = recent[~np.isnan(recent)]
    expected = np.asarray(reference["props"]) + EPS
    actual = proportions(v, np.asarray(reference["edges"])) + EPS
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def out_of_support(reference: dict, recent: np.ndarray) -> float:
    v = recent[~np.isnan(recent)]
    if not len(v):
        return 0.0
    return float(np.mean((v < reference["lo"]) | (v > reference["hi"])))


@dataclass
class DriftResult:
    metric: str
    feature: str | None
    value: float
    threshold: float
    breached: bool
    triggers_retrain: bool


def evaluate(
    reference: dict, conditions: dict[str, np.ndarray], scores: np.ndarray, alarms: np.ndarray
) -> list[DriftResult]:
    out = []
    for col, values in conditions.items():
        ref = reference["conditions"].get(col)
        if ref is None or not len(values):
            continue
        p = psi(ref, values)
        out.append(DriftResult("psi_input", col, round(p, 4), PSI_THRESHOLD, p > PSI_THRESHOLD, False))
        o = out_of_support(ref, values)
        out.append(
            DriftResult(
                "out_of_support",
                col,
                round(o, 4),
                OUT_OF_SUPPORT_THRESHOLD,
                o > OUT_OF_SUPPORT_THRESHOLD,
                True,
            )
        )
    s = scores[~np.isnan(scores)]
    if len(s):
        ratio = float(np.median(s)) / max(reference["turbine_score"]["median"], EPS)
        out.append(
            DriftResult(
                "residual_shift",
                "turbine_score",
                round(ratio, 4),
                RESIDUAL_SHIFT_THRESHOLD,
                ratio > RESIDUAL_SHIFT_THRESHOLD,
                True,
            )
        )
    if len(alarms):
        rate = float(np.mean(alarms))
        limit = max(ALERT_RATE_FACTOR * reference["alarm_rate"], ALERT_RATE_FLOOR)
        out.append(DriftResult("alert_rate", None, round(rate, 4), round(limit, 4), rate > limit, False))
    return out


# ---------------------------------------------------------------- live window

RECENT_CONDITIONS = text(
    """
    SELECT s.code, t.value
    FROM telemetry t
    JOIN replay_state r ON r.turbine_id = t.turbine_id
    JOIN sensor s ON s.id = t.sensor_id
    WHERE s.farm_id = :farm AND s.code = ANY(:codes)
      AND t.ts > r.cursor_ts - make_interval(days => :days) AND t.ts <= r.cursor_ts
    """
)

RECENT_SCORES = text(
    """
    SELECT h.residual_z, h.alarm
    FROM health_score h
    JOIN replay_state r ON r.turbine_id = h.turbine_id
    JOIN turbine tb ON tb.id = h.turbine_id
    WHERE tb.farm_id = :farm AND h.subcomponent_code = :row AND h.model_version = :mv
      AND h.ts > r.cursor_ts - make_interval(days => :days) AND h.ts <= r.cursor_ts
    """
)


def recent_window(engine: Engine, farm: str, model: LoadedModel, days: int):
    codes = {c.removesuffix("_avg"): c for c in model.bundle.conditions}
    with engine.connect() as conn:
        cond = pd.DataFrame(
            conn.execute(RECENT_CONDITIONS, {"farm": farm, "codes": list(codes), "days": days}).all(),
            columns=["code", "value"],
        )
        scores = pd.DataFrame(
            conn.execute(
                RECENT_SCORES, {"farm": farm, "row": TURBINE, "mv": model.label, "days": days}
            ).all(),
            columns=["score", "alarm"],
        )
    conditions = {
        codes[code]: g["value"].to_numpy(np.float64) for code, g in cond.groupby("code", sort=False)
    }
    return (
        conditions,
        scores["score"].to_numpy(np.float64),
        scores["alarm"].fillna(False).to_numpy(bool),
    )


def check_farm(
    engine: Engine, lake_root: Path, farm: str, model: LoadedModel, days: int
) -> list[DriftResult]:
    """Evaluate drift for one farm and persist the report rows. Returns [] when the live
    window is still too small to judge."""
    conditions, scores, alarms = recent_window(engine, farm, model, days)
    if len(scores) < MIN_RECENT_ROWS:
        log.info("drift check skipped: not enough live data yet", farm=farm, rows=len(scores))
        return []
    results = evaluate(load_profile(lake_root, farm, model), conditions, scores, alarms)
    with session_scope() as s:
        s.add_all(
            DriftReport(
                farm_id=farm,
                metric=r.metric,
                feature=r.feature,
                value=r.value,
                threshold=r.threshold,
                breached=r.breached,
            )
            for r in results
        )
    log.info(
        "drift checked",
        farm=farm,
        model=model.label,
        rows=len(scores),
        breached=[f"{r.metric}:{r.feature}" for r in results if r.breached],
    )
    return results
