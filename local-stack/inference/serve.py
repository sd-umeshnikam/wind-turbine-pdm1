"""Local substitute for Databricks Model Serving (see ADR-0002, ADR-0004).

Loads the real models 05_train_models.py trained (via the local MLflow registry)
and serves them in exactly the JSON shape `prediction-api`'s databricksClient.ts
already expects (`DatabricksServingResponse`) - prediction-api itself needs zero
code changes, only DATABRICKS_SERVING_URL/_TOKEN pointed at this server (any
non-empty token value works; this server doesn't check it, same trust model as a
single-user local demo behind the gateway's own network boundary).

Run: uvicorn serve:app --host 0.0.0.0 --port 8080
POST /invocations
Body: {"dataframe_records": [{"turbine_id": "A-3", "component": "gearbox"}]}
      (component omitted -> predicts for every component with a trained model)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import mlflow
import mlflow.pyfunc
import mlflow.statsmodels
import pandas as pd
from deltalake import DeltaTable
from fastapi import FastAPI
from mlflow.tracking import MlflowClient
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from common import gold_path, real_asset_id_for  # noqa: E402

ENV_LABEL = "local"
COMPONENTS = ["gearbox", "hydraulics", "pitch", "generator", "transformer", "rotor_brake", "vibration"]
METADATA_COLS = {"farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", "category"}
FORECAST_HORIZON_DAYS = 14

mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"))
client = MlflowClient()
app = FastAPI(title="wtb-pdm local inference")

_model_cache: dict[str, Optional[object]] = {}
_run_id_cache: dict[str, Optional[str]] = {}


class DataframeRecord(BaseModel):
    turbine_id: str
    component: Optional[str] = None


class InvocationRequest(BaseModel):
    dataframe_records: list[DataframeRecord]


def _latest_version(name: str):
    versions = client.get_latest_versions(name)
    return versions[0] if versions else None


def _first_pred(pred) -> float:
    """LightGBM regressors' pyfunc wrapper returns a plain numpy array from
    predict() (no .iloc), unlike the multiclass classifier's wrapper above, which
    returns something DataFrame/Series-like."""
    return float(pred.iloc[0]) if hasattr(pred, "iloc") else float(pred[0])


def get_model(name: str):
    """Lazily loads and caches a registered model by name; `None` (cached) if it
    was never trained/registered - e.g. a component with too few labeled rows to
    train an RUL regressor (see 05_train_models.py's skip conditions)."""
    if name not in _model_cache:
        version = _latest_version(name)
        if version is None:
            _model_cache[name] = None
            _run_id_cache[name] = None
        else:
            _model_cache[name] = mlflow.pyfunc.load_model(f"models:/{name}/{version.version}")
            _run_id_cache[name] = version.run_id
    return _model_cache[name]


def healthy_class_index(classifier_name: str) -> int:
    run_id = _run_id_cache.get(classifier_name)
    if not run_id:
        return 0
    run = client.get_run(run_id)
    return int(run.data.params.get("healthy_class_index", 0))


def latest_feature_row(component: str, farm: str, real_asset_id: str) -> Optional[pd.Series]:
    path = gold_path(f"{component}_features")
    if not Path(path).joinpath("_delta_log").exists():
        return None
    # Loading the whole table (gearbox alone is ~4.7M rows across all 3 farms)
    # just to find one asset's latest row ran this container out of memory.
    # "farm" is a partition column (see 03_gold_features.py's partitionBy), so
    # filtering on it prunes the other farms' files entirely instead of reading
    # them; the asset_id filter also gets pushed to the Parquet reader.
    df = DeltaTable(path).to_pandas(filters=[("farm", "=", farm), ("asset_id", "=", int(real_asset_id))])
    if df.empty:
        return None
    return df.sort_values("time_stamp").iloc[-1]


def feature_frame(row: pd.Series) -> pd.DataFrame:
    cols = [c for c in row.index if c not in METADATA_COLS]
    return pd.DataFrame([row[cols].to_dict()])


def find_trend_model_for_asset(component: str, real_asset_id: str):
    name = f"{component}_trend_forecaster_{ENV_LABEL}"
    try:
        versions = client.search_model_versions(f"name='{name}'")
    except Exception:
        return None
    for v in versions:
        run = client.get_run(v.run_id)
        if run.data.tags.get("asset_id") == str(real_asset_id):
            return mlflow.statsmodels.load_model(f"models:/{name}/{v.version}")
    return None


def build_forecast_series(component: str, real_asset_id: str) -> list[dict]:
    model = find_trend_model_for_asset(component, real_asset_id)
    if model is None:
        return []
    forecast = model.forecast(FORECAST_HORIZON_DAYS)
    now = datetime.now(timezone.utc)
    return [
        {"timestamp": (now + timedelta(days=i + 1)).isoformat(), "value": float(v)}
        for i, v in enumerate(forecast)
    ]


def predict_one(turbine_id: str, component: str) -> Optional[dict]:
    parsed = real_asset_id_for(turbine_id)
    if parsed is None:
        return None
    farm, real_asset_id = parsed

    row = latest_feature_row(component, farm, real_asset_id)
    if row is None:
        return None
    X = feature_frame(row)

    classifier_name = f"{component}_fault_classifier_{ENV_LABEL}"
    clf = get_model(classifier_name)
    p10_model = get_model(f"{component}_rul_p10_{ENV_LABEL}")
    p50_model = get_model(f"{component}_rul_p50_{ENV_LABEL}")
    p90_model = get_model(f"{component}_rul_p90_{ENV_LABEL}")
    if clf is None or p10_model is None or p50_model is None or p90_model is None:
        # Real gap, not fabricated: this component never had enough labeled data
        # to train one of these models locally (see 05_train_models.py's skip
        # logging) - omit it rather than inventing a number.
        return None

    proba = clf.predict(X)
    proba_row = proba.iloc[0].to_numpy() if hasattr(proba, "iloc") else proba[0]
    healthy_idx = healthy_class_index(classifier_name)
    fault_probability = float(1.0 - proba_row[healthy_idx])

    return {
        "turbine_id": turbine_id,
        "component": component,
        "fault_probability": round(fault_probability, 4),
        "rul_hours_p10": _first_pred(p10_model.predict(X)),
        "rul_hours_p50": _first_pred(p50_model.predict(X)),
        "rul_hours_p90": _first_pred(p90_model.predict(X)),
        "forecast_series": build_forecast_series(component, real_asset_id),
    }


@app.post("/invocations")
def invocations(req: InvocationRequest) -> dict:
    predictions = []
    for record in req.dataframe_records:
        components = [record.component] if record.component else COMPONENTS
        for component in components:
            result = predict_one(record.turbine_id, component)
            if result is not None:
                predictions.append(result)
    return {"predictions": predictions}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
