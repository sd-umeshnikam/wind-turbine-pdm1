"""The serving champion of a farm and its normal-operation profile.

The profile is built once per registered model version from the curated lake - the last
two weeks of every event file's training history, scored by that model - and cached in
the lake. It serves two purposes:
- health calibration: per sub-part and turbine score, the median and 99.5th percentile on
  normal operation (operating rows), so health reads the same on every farm (100 = typical, 50 = as unusual
  as the worst 0.5% of normal operation);
- the drift monitor's reference distributions (operating conditions, turbine score,
  alarm rate).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
import polars as pl
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from wtpdm import catalog
from wtpdm.logging import get_logger
from wtpdm.ml.bundle import HealthBundle
from wtpdm.ml.health import calibrated_health
from wtpdm.ml.train import model_name

log = get_logger("champion")
MODEL_CACHE = Path("/tmp/wtpdm-models")
PROFILE_FORMAT = 3
PROFILE_ROWS_PER_EVENT = 2016  # two weeks
TURBINE = "turbine"


@dataclass
class LoadedModel:
    name: str
    version: str
    run_id: str
    bundle: HealthBundle

    @property
    def label(self) -> str:
        return f"{self.name}/{self.version}"


def champion_version(farm: str) -> str | None:
    try:
        return str(MlflowClient().get_model_version_by_alias(model_name(farm), "champion").version)
    except MlflowException:
        return None


def load_champion(farm: str) -> LoadedModel | None:
    name = model_name(farm)
    try:
        mv = MlflowClient().get_model_version_by_alias(name, "champion")
    except MlflowException:
        return None
    dst = MODEL_CACHE / name / str(mv.version)
    dst.mkdir(parents=True, exist_ok=True)
    path = mlflow.artifacts.download_artifacts(
        artifact_uri=f"runs:/{mv.run_id}/model/artifacts/bundle.joblib", dst_path=str(dst)
    )
    return LoadedModel(name, str(mv.version), mv.run_id, joblib.load(path))


# ---------------------------------------------------------------- normal-operation profile


def proportions(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    # Open-ended outer bins: values beyond the reference range land in the first/last bin.
    idx = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, max(len(edges) - 2, 0))
    counts = np.bincount(idx, minlength=max(len(edges) - 1, 1))
    return counts / max(counts.sum(), 1)


def quantile_profile(values: np.ndarray, bins: int = 10) -> dict:
    v = values[~np.isnan(values)]
    edges = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)))
    return {
        "edges": edges.tolist(),
        "props": proportions(v, edges).tolist(),
        "lo": float(np.quantile(v, 0.005)),
        "hi": float(np.quantile(v, 0.995)),
        "median": float(np.median(v)),
    }


def profile_path(lake_root: Path, model: LoadedModel) -> Path:
    return lake_root / "reference" / f"{model.name}-v{model.version}.json"


def build_profile(lake_root: Path, farm: str, model: LoadedModel) -> dict:
    bundle = model.bundle
    targets = sorted({c for cols in bundle.targets.values() for c in cols})
    parts = []
    for event_id in catalog.events(lake_root, farm)["event_id"].to_list():
        path = catalog.curated_event_path(lake_root, farm, int(event_id))
        present = set(pl.read_parquet_schema(path))
        cols = [
            "ts",
            "turbine_id",
            "split",
            "operating",
            *[c for c in [*bundle.conditions, *targets] if c in present],
        ]
        parts.append(
            pl.read_parquet(path, columns=cols)
            .filter(pl.col("split") == "train")
            .tail(PROFILE_ROWS_PER_EVENT)
        )
    frame = (
        pl.concat(parts, how="diagonal_relaxed")
        .unique(subset=["turbine_id", "ts"], keep="first")
        .sort(["turbine_id", "ts"])
        .to_pandas(use_pyarrow_extension_array=False)
    )
    scored = bundle.score(frame)  # contiguous rows, so the smoothing runs as it does live
    # Score quantiles on operating rows only: the models and the alarm threshold were fit on
    # operating data, and downtime/service rows would inflate the "normal" range.
    operating = frame["operating"].to_numpy(bool)
    summary, subs = scored["summary"][operating], scored["subcomponent_score"][operating]
    profile = {
        "format": PROFILE_FORMAT,
        "model": model.label,
        "data_version": catalog.data_version(lake_root, farm),
        "rows": len(frame),
        "conditions": {c: quantile_profile(frame[c].to_numpy(np.float64)) for c in bundle.conditions},
        "turbine_score": quantile_profile(summary["turbine_score"].to_numpy(np.float64)),
        "subparts": {
            s: quantile_profile(subs[s].to_numpy(np.float64))
            for s in subs.columns.drop(["ts", "turbine_id"])
            if subs[s].notna().any()
        },
        "alarm_rate": float(scored["summary"]["alarm"].mean()),
    }
    path = profile_path(lake_root, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile))
    log.info("normal-operation profile built", farm=farm, model=model.label, rows=len(frame))
    return profile


def load_profile(lake_root: Path, farm: str, model: LoadedModel) -> dict:
    path = profile_path(lake_root, model)
    if path.exists():
        profile = json.loads(path.read_text())
        if profile.get("format") == PROFILE_FORMAT:
            return profile
    return build_profile(lake_root, farm, model)


def health(
    profile: dict, key: str, scores: np.ndarray | pd.Series, alarm_level: float | None = None
) -> np.ndarray:
    """Calibrated health of sub-part `key` (or TURBINE) scores; `alarm_level` overrides the
    profile's 99.5th percentile (the threshold-baseline detector alarms on the turbine score
    itself, so its threshold is the exact alarm level). A sub-part without a profile (never
    scored on normal data) gets NaN rather than an uncalibrated number."""
    ref = profile["turbine_score"] if key == TURBINE else profile["subparts"].get(key)
    if ref is None:
        return np.full(len(scores), np.nan)
    return calibrated_health(scores, ref["median"], alarm_level if alarm_level is not None else ref["hi"])
