"""Online scoring of the replayed stream with each farm's champion health model.

Per tick and farm: new rows are appended to a rolling 48 h buffer per turbine, the
champion bundle scores buffer + new rows (residuals -> sub-part scores -> detector ->
persistent alarm, exactly the evaluated pipeline), and the new rows' results are written
to the health_score hypertable: one row per sub-part plus a turbine-level row
(subcomponent_code = "turbine") carrying the detector score and the alarm flag. Health is
calibrated against the champion's normal-operation profile (see `champion`).

The champion is resolved through the MLflow registry alias and re-checked every minute,
so a promotion takes effect in the live stream without a restart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from wtpdm.db.models import AuditLog
from wtpdm.db.session import session_scope
from wtpdm.logging import get_logger
from wtpdm.realtime import champion
from wtpdm.realtime.champion import TURBINE, LoadedModel

log = get_logger("scorer")
HISTORY_ROWS = 288  # 48 h: warms the 6 h EWMA and the supervised detector's 24 h features
MODEL_CHECK_SECONDS = 60


@dataclass
class ScoredBatch:
    farm: str
    model: LoadedModel
    summary: pd.DataFrame  # every scored row (history + new), sorted by turbine, ts; `is_new`, `health`
    residual_z: pd.DataFrame  # aligned with summary


UPSERT_HEALTH = text(
    """
    INSERT INTO health_score (turbine_id, ts, subcomponent_code, health, residual_z,
                              anomaly_score, alarm, model_version)
    SELECT * FROM unnest(CAST(:t AS text[]), CAST(:ts AS timestamptz[]), CAST(:sub AS text[]),
                         CAST(:h AS float8[]), CAST(:z AS float8[]), CAST(:a AS float8[]),
                         CAST(:alarm AS boolean[]), CAST(:mv AS text[]))
    ON CONFLICT (turbine_id, ts, subcomponent_code) DO UPDATE SET
        health = EXCLUDED.health, residual_z = EXCLUDED.residual_z,
        anomaly_score = EXCLUDED.anomaly_score, alarm = EXCLUDED.alarm,
        model_version = EXCLUDED.model_version
    """
)


def _nan_to_none(values: np.ndarray) -> list[float | None]:
    return [None if np.isnan(v) else float(v) for v in values]


class OnlineScorer:
    def __init__(self, farm: str, engine: Engine, lake_root: Path):
        self.farm = farm
        self.engine = engine
        self.lake_root = lake_root
        self.model: LoadedModel | None = None
        self.profile: dict = {}
        self.buffers: dict[str, pd.DataFrame] = {}
        self._checked_at = 0.0

    def refresh_model(self) -> None:
        if time.monotonic() - self._checked_at < MODEL_CHECK_SECONDS:
            return
        self._checked_at = time.monotonic()
        version = champion.champion_version(self.farm)
        if version is None:
            if self.model is None:
                log.warning("no champion model; replay continues unscored", farm=self.farm)
            return
        if self.model is not None and self.model.version == version:
            return
        previous = self.model.label if self.model else None
        model = champion.load_champion(self.farm)
        if model is None:
            return
        self.profile = champion.load_profile(self.lake_root, self.farm, model)
        self.model = model
        log.info("champion loaded", farm=self.farm, model=model.label, previous=previous)
        with session_scope() as s:
            s.add(
                AuditLog(
                    actor="system:scorer",
                    action="model.serve",
                    entity="model",
                    entity_id=model.label,
                    details={"farm": self.farm, "previous": previous, "run_id": model.run_id},
                )
            )

    def _frame(self, rows: pd.DataFrame) -> pd.DataFrame:
        parts = []
        for turbine_id, new in rows.groupby("turbine_id", sort=False):
            buf = self.buffers.get(turbine_id)
            # The replay looped back to the start of the timeline: history no longer precedes it.
            if buf is not None and len(buf) and new["ts"].min() <= buf["ts"].max():
                buf = None
            if buf is not None:
                parts.append(buf.assign(is_new=False))
            parts.append(new.assign(is_new=True))
        frame = pd.concat(parts, ignore_index=True)
        return frame.sort_values(["turbine_id", "ts"], kind="stable").reset_index(drop=True)

    def process(self, rows: pd.DataFrame) -> ScoredBatch | None:
        self.refresh_model()
        frame = self._frame(rows)
        self.buffers = {
            t: g.drop(columns="is_new").tail(HISTORY_ROWS).reset_index(drop=True)
            for t, g in frame.groupby("turbine_id", sort=False)
        }
        if self.model is None:
            return None
        bundle = self.model.bundle
        scored = bundle.score(frame)
        summary = scored["summary"].assign(
            is_new=frame["is_new"].to_numpy(),
            health=champion.health(
                self.profile,
                TURBINE,
                scored["summary"]["turbine_score"],
                bundle.threshold if bundle.detector_name == "threshold_baseline" else None,
            ),
        )
        self._write(summary, scored["subcomponent_score"], self.model.label)
        return ScoredBatch(self.farm, self.model, summary, scored["residual_z"])

    def _write(self, summary: pd.DataFrame, subs: pd.DataFrame, model_label: str) -> None:
        new = summary["is_new"].to_numpy()
        cols: dict[str, list] = {k: [] for k in ("t", "ts", "sub", "h", "z", "a", "alarm", "mv")}

        def add(sub_code: str, scores, health, anomaly, alarm, mask):
            n = int(mask.sum())
            cols["t"] += summary.loc[mask, "turbine_id"].tolist()
            cols["ts"] += [t.to_pydatetime() for t in summary.loc[mask, "ts"]]
            cols["sub"] += [sub_code] * n
            cols["h"] += _nan_to_none(health[mask])
            cols["z"] += _nan_to_none(scores[mask])
            cols["a"] += _nan_to_none(anomaly[mask]) if anomaly is not None else [None] * n
            cols["alarm"] += alarm[mask].tolist() if alarm is not None else [None] * n
            cols["mv"] += [model_label] * n

        for sub in subs.columns.drop(["ts", "turbine_id"]):
            score = subs[sub].to_numpy(np.float64)
            health = champion.health(self.profile, sub, score)
            add(sub, score, health, None, None, new & ~np.isnan(score) & ~np.isnan(health))
        turbine = summary["turbine_score"].to_numpy(np.float64)
        add(
            TURBINE,
            turbine,
            summary["health"].to_numpy(np.float64),
            summary["detector_score"].to_numpy(np.float64),
            summary["alarm"].to_numpy(bool),
            new & ~np.isnan(turbine),
        )
        if cols["t"]:
            with self.engine.begin() as conn:
                conn.execute(UPSERT_HEALTH, cols)
