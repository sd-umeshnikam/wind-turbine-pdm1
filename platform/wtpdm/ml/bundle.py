"""The deployable health model of one farm: all sub-part NBMs, residual normalisation,
the selected detector and its threshold - exactly what was evaluated, in one artifact.

Logged to MLflow as a pyfunc model; the online scorer loads it by registry alias.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from mlflow.pyfunc import PythonModel

from wtpdm.ml import detectors
from wtpdm.ml.health import component_scores, health_from_score, subpart_scores, top_drivers
from wtpdm.ml.nbm import TargetModel, residual_z


@dataclass
class HealthBundle:
    farm: str
    conditions: list[str]
    targets: dict[str, list[str]]
    descriptions: dict[str, str]
    units: dict[str, str | None]
    target_models: dict[str, TargetModel]
    detector_name: str
    detector_model: object | None
    threshold: float
    persistence_rows: int = detectors.PERSISTENCE_ROWS
    metrics: dict = field(default_factory=dict)

    def score(self, frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """Score rows of one or more turbines. `frame` needs ts, turbine_id, the condition
        and target columns, in time order per turbine (include ~24 h of history before the
        rows you care about so the smoothing and rolling features are warmed up)."""
        frame = frame.sort_values(["turbine_id", "ts"]).reset_index(drop=True)
        z = pd.DataFrame(
            {t: residual_z(m, frame, self.conditions) for t, m in self.target_models.items()},
            index=frame.index,
        )
        subs = subpart_scores(z, self.targets, frame["turbine_id"])
        comps = component_scores(subs)
        turbine = subs.max(axis=1)
        if self.detector_name == "threshold_baseline":
            det_score = turbine.to_numpy()
        elif self.detector_name == "isolation_forest":
            det_score = -self.detector_model.score_samples(subs.fillna(0.0).to_numpy())  # type: ignore[union-attr]
        else:
            feats = detectors.supervised_features(subs, frame["turbine_id"])
            det_score = self.detector_model.predict_proba(feats.to_numpy(np.float32))[:, 1]  # type: ignore[union-attr]
        alarm = detectors.persistent_alarm(
            det_score, self.threshold, frame["turbine_id"].to_numpy(), self.persistence_rows
        )
        summary = pd.DataFrame(
            {
                "ts": frame["ts"],
                "turbine_id": frame["turbine_id"],
                "turbine_score": turbine,
                "turbine_health": health_from_score(turbine),
                "detector_score": det_score,
                "alarm": alarm,
                # NaN while no sub-part has a score yet (smoothing warm-up)
                "worst_subcomponent": subs.fillna(-np.inf).idxmax(axis=1).where(subs.notna().any(axis=1)),
            }
        )
        return {
            "summary": summary,
            "subcomponent_score": subs.assign(ts=frame["ts"], turbine_id=frame["turbine_id"]),
            "component_score": comps.assign(ts=frame["ts"], turbine_id=frame["turbine_id"]),
            "residual_z": z.assign(ts=frame["ts"], turbine_id=frame["turbine_id"]),
        }

    def drivers(self, z_row: pd.Series, k: int = 3) -> list[dict]:
        return top_drivers(z_row.drop(labels=["ts", "turbine_id"], errors="ignore"), self.descriptions, k)


class HealthPyfunc(PythonModel):
    """MLflow wrapper: predict() returns the per-row summary frame."""

    def load_context(self, context):
        self.bundle: HealthBundle = joblib.load(context.artifacts["bundle"])

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        return self.bundle.score(model_input)["summary"]
