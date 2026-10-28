"""MLflow registry access for the API: registered versions with their evaluation metrics,
the comparison tables and model card each training run logged, and the serving champion
bundle (for on-demand expected values). Finished runs are immutable, so their metadata and
artifacts are cached per run id."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, status
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from wtpdm.ml.train import model_name
from wtpdm.realtime import champion as champion_mod
from wtpdm.realtime.champion import LoadedModel
from wtpdm.settings import get_settings

ARTIFACT_CACHE = Path("/tmp/wtpdm-api-artifacts")
CHAMPION_CHECK_SECONDS = 60
# Direction of each evaluation metric, for champion/challenger deltas.
HIGHER_IS_BETTER = {
    "care_style_score",
    "event_recall",
    "event_precision",
    "event_f1",
    "normal_accuracy",
    "earliness",
    "diagnosis_accuracy",
    "detected",
    "median_warning_hours",
}
LOWER_IS_BETTER = {"false_alarm_events", "false_alarm_days_per_turbine_year", "pre_onset_alarm_events"}


def client() -> MlflowClient:
    return MlflowClient(tracking_uri=get_settings().mlflow_tracking_uri)


def _clean(v):
    return None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


_runs: dict[str, dict] = {}


def _run(run_id: str) -> dict:
    if run_id in _runs:
        return _runs[run_id]
    run = client().get_run(run_id)
    out = {
        "run_id": run_id,
        "experiment_id": run.info.experiment_id,
        "status": run.info.status,
        "start_time": run.info.start_time,
        "end_time": run.info.end_time,
        "tags": {k: v for k, v in run.data.tags.items() if not k.startswith("mlflow.")},
        "params": dict(run.data.params),
        "metrics": {
            k.removeprefix("selected_"): v for k, v in run.data.metrics.items() if k.startswith("selected_")
        },
    }
    if run.info.status == "FINISHED":  # a running run may still change
        _runs[run_id] = out
    return out


def run_url(run: dict) -> str:
    base = get_settings().mlflow_ui_url.rstrip("/")
    return f"{base}/#/experiments/{run['experiment_id']}/runs/{run['run_id']}"


def versions(farm: str) -> list[dict]:
    name = model_name(farm)
    out = []
    for mv in client().search_model_versions(f"name='{name}'"):
        run = _run(mv.run_id)
        out.append(
            {
                "model": name,
                "farm": farm,
                "version": str(mv.version),
                "aliases": list(mv.aliases),
                "gate": mv.tags.get("gate"),
                "created_at": pd.Timestamp(mv.creation_timestamp, unit="ms", tz="UTC").isoformat(),
                "run_id": mv.run_id,
                "run_url": run_url(run),
                "trigger": run["tags"].get("trigger"),
                "actor": run["tags"].get("actor"),
                "data_version": run["tags"].get("data_version"),
                "selected_detector": run["tags"].get("selected_detector"),
                "metrics": run["metrics"],
            }
        )
    return sorted(out, key=lambda v: int(v["version"]), reverse=True)


def version(farm: str, ver: str) -> dict:
    match = next((v for v in versions(farm) if v["version"] == ver), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model_name(farm)} has no version {ver}")
    return match


def _artifact(run_id: str, path: str) -> Path:
    local = ARTIFACT_CACHE / run_id / path
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            client().download_artifacts(run_id, path, str(ARTIFACT_CACHE / run_id))  # keeps `path` below it
        except MlflowException as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} has no artifact {path}") from exc
    return local


def comparison(farm: str, ver: str) -> dict:
    """Everything the training run compared: detectors (CARE-style metrics), normal-
    behaviour regressors per sensor, per-component evaluation, RUL candidates."""
    v = version(farm, ver)
    run_id = v["run_id"]
    detectors = pd.read_csv(_artifact(run_id, "evaluation/detector_comparison.csv"))
    components = pd.read_csv(_artifact(run_id, "evaluation/component_evaluation.csv"))
    nbm = pd.read_csv(_artifact(run_id, "evaluation/nbm_comparison.csv"))
    rul = client().search_runs(
        [_run(run_id)["experiment_id"]],
        filter_string=f"tags.mlflow.parentRunId = '{run_id}' and tags.stage = 'rul'",
    )
    return {
        "model": v["model"],
        "version": ver,
        "selected_detector": v["selected_detector"],
        "detectors": _records(detectors),
        "components": _records(components),
        "nbm": _records(nbm),
        "rul": [
            {"candidate": r.data.tags.get("candidate"), "experimental": True, **r.data.metrics} for r in rul
        ],
    }


def card(farm: str, ver: str) -> str:
    return _artifact(version(farm, ver)["run_id"], "evaluation/model_card.md").read_text(encoding="utf-8")


def compare(farm: str, a: str, b: str) -> dict:
    """Metric-by-metric comparison of two versions; `delta` = b - a, `better` says which wins."""
    va, vb = version(farm, a), version(farm, b)
    rows = []
    for metric in sorted(set(va["metrics"]) | set(vb["metrics"])):
        x, y = va["metrics"].get(metric), vb["metrics"].get(metric)
        delta = round(y - x, 4) if x is not None and y is not None else None
        better = None
        if delta:
            if metric in HIGHER_IS_BETTER:
                better = b if delta > 0 else a
            elif metric in LOWER_IS_BETTER:
                better = b if delta < 0 else a
        rows.append({"metric": metric, "a": x, "b": y, "delta": delta, "better": better})
    return {"model": va["model"], "a": va, "b": vb, "metrics": rows}


# ---------------------------------------------------------------- serving champion

_lock = threading.Lock()
_champions: dict[str, tuple[float, LoadedModel]] = {}


def champion(farm: str) -> LoadedModel:
    """The farm's champion bundle, re-checked against the registry alias every minute."""
    with _lock:
        cached = _champions.get(farm)
        if cached and time.monotonic() - cached[0] < CHAMPION_CHECK_SECONDS:
            return cached[1]
        current = champion_mod.champion_version(farm)
        if current is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Farm {farm} has no champion model")
        if cached and cached[1].version == current:
            model = cached[1]
        else:
            loaded = champion_mod.load_champion(farm)
            if loaded is None:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Farm {farm} has no champion model")
            model = loaded
        _champions[farm] = (time.monotonic(), model)
        return model
