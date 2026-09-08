"""Trains real local models per component (local port of data-platform/ml/04, 05,
06 - same modeling choices, consolidated into one script, logged to a local MLflow
server instead of the Databricks-managed one):
  - Fault classifier: multi-class LightGBM (unchanged from ml/04)
  - RUL: LightGBM quantile regression, P10/P50/P90 (unchanged from ml/05)
  - Trend forecaster: per-asset statsmodels ETS on a z-scored health index
    (unchanged from ml/06)

Requires the local MLflow server running (see local-stack/docker-compose.yml's
comment / docs/LINUX_HOSTING_GUIDE.md) - set MLFLOW_TRACKING_URI, default
http://localhost:5000.

Usage: python 05_train_models.py [--component gearbox] (omit --component to train all)
"""
from __future__ import annotations

import argparse
import os

import mlflow
import mlflow.lightgbm
import mlflow.statsmodels
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import f1_score, classification_report, mean_pinball_loss
from sklearn.model_selection import train_test_split
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from pyspark.sql import functions as F

from common import build_spark, delta_table_exists, gold_path

COMPONENTS = [
    "gearbox", "hydraulics", "pitch", "generator", "transformer", "rotor_brake", "vibration",
]
ENV_LABEL = "local"
MIN_DAYS_TO_FIT_TREND = 30


def train_fault_classifier(spark, component: str) -> None:
    features_path = gold_path(f"{component}_features")
    events_path = gold_path("fault_events")
    if not delta_table_exists(spark, features_path) or not delta_table_exists(spark, events_path):
        print(f"[{component}] skip fault classifier - missing gold table(s)")
        return

    features_df = spark.read.format("delta").load(features_path)
    fault_events = (
        spark.read.format("delta")
        .load(events_path)
        .select(F.col("farm").alias("fe_farm"), F.col("event_id").alias("fe_event_id"), "category")
    )
    labeled = (
        features_df.join(
            fault_events,
            on=(features_df.farm == F.col("fe_farm")) & (features_df.event_id == F.col("fe_event_id")),
            how="left",
        )
        .withColumn("label", F.coalesce(F.col("category"), F.lit("healthy")))
        .drop("fe_farm", "fe_event_id", "category")
    )
    pdf = labeled.toPandas()
    if pdf["label"].nunique() < 2:
        print(f"[{component}] skip fault classifier - only one class present ({pdf['label'].unique()})")
        return

    feature_cols = [
        c for c in pdf.columns
        if c not in {"farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", "label"}
    ]
    pdf[feature_cols] = pdf[feature_cols].fillna(pdf[feature_cols].median(numeric_only=True))

    X = pdf[feature_cols]
    y = pdf["label"].astype("category")
    label_names = list(y.cat.categories)
    y_codes = y.cat.codes

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_codes, test_size=0.2, random_state=42, stratify=y_codes if y_codes.nunique() > 1 else None
    )

    params = {
        "objective": "multiclass",
        "num_class": len(label_names),
        "metric": "multi_logloss",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 20,
        "verbose": -1,
    }

    mlflow.set_experiment(f"wtb-pdm-{ENV_LABEL}/{component}_fault_classifier")
    with mlflow.start_run(run_name=f"{component}_fault_classifier"):
        mlflow.log_params(params)
        mlflow.log_param("n_features", len(feature_cols))
        mlflow.log_param("classes", label_names)
        # LightGBM's raw predict() returns per-class probabilities ordered by
        # label_names (alphabetical, since y is a pandas Categorical) - "healthy"
        # is not necessarily index 0. inference/serve.py needs this index to
        # compute fault_probability = 1 - P(healthy); logging it directly avoids
        # having it re-derive/parse the "classes" param string at serving time.
        mlflow.log_param("healthy_class_index", label_names.index("healthy"))

        train_set = lgb.Dataset(X_train, label=y_train)
        valid_set = lgb.Dataset(X_test, label=y_test, reference=train_set)
        model = lgb.train(
            params, train_set, num_boost_round=200, valid_sets=[valid_set],
            callbacks=[lgb.early_stopping(stopping_rounds=20), lgb.log_evaluation(period=0)],
        )

        preds = model.predict(X_test).argmax(axis=1)
        macro_f1 = f1_score(y_test, preds, average="macro")
        mlflow.log_metric("macro_f1", macro_f1)
        print(f"[{component}] fault classifier macro_f1={macro_f1:.4f}")
        print(classification_report(y_test, preds, target_names=label_names, zero_division=0))

        mlflow.lightgbm.log_model(
            model, artifact_path="model",
            registered_model_name=f"{component}_fault_classifier_{ENV_LABEL}",
        )


def train_rul_regressor(spark, component: str) -> None:
    features_path = gold_path(f"{component}_features")
    rul_path = gold_path("rul_labels")
    if not delta_table_exists(spark, features_path) or not delta_table_exists(spark, rul_path):
        print(f"[{component}] skip RUL regressor - missing gold table(s)")
        return

    features_df = spark.read.format("delta").load(features_path)
    rul_labels = spark.read.format("delta").load(rul_path)
    labeled = features_df.join(rul_labels, on=["farm", "asset_id", "time_stamp", "event_id"], how="inner")
    pdf = labeled.toPandas()
    if pdf.empty:
        print(f"[{component}] skip RUL regressor - no rows after join (no pre-event window for this component)")
        return

    feature_cols = [
        c for c in pdf.columns
        if c not in {"farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", "hours_to_failure"}
    ]
    pdf[feature_cols] = pdf[feature_cols].fillna(pdf[feature_cols].median(numeric_only=True))
    X = pdf[feature_cols]
    y = pdf["hours_to_failure"]

    if len(X) < 10:
        print(f"[{component}] skip RUL regressor - only {len(X)} labeled rows, too few to split")
        return
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    mlflow.set_experiment(f"wtb-pdm-{ENV_LABEL}/{component}_rul_regressor")
    with mlflow.start_run(run_name=f"{component}_rul_regressor"):
        mlflow.log_param("n_features", len(feature_cols))
        mlflow.log_param("n_train_rows", len(X_train))

        for name, alpha in {"p10": 0.1, "p50": 0.5, "p90": 0.9}.items():
            params = {
                "objective": "quantile", "alpha": alpha, "metric": "quantile",
                "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 20, "verbose": -1,
            }
            train_set = lgb.Dataset(X_train, label=y_train)
            valid_set = lgb.Dataset(X_test, label=y_test, reference=train_set)
            model = lgb.train(
                params, train_set, num_boost_round=200, valid_sets=[valid_set],
                callbacks=[lgb.early_stopping(stopping_rounds=20), lgb.log_evaluation(period=0)],
            )
            preds = model.predict(X_test)
            pinball = mean_pinball_loss(y_test, preds, alpha=alpha)
            mlflow.log_metric(f"pinball_loss_{name}", pinball)
            mlflow.lightgbm.log_model(
                model, artifact_path=f"model_{name}",
                registered_model_name=f"{component}_rul_{name}_{ENV_LABEL}",
            )
            print(f"[{component}] RUL {name}: pinball_loss={pinball:.4f}")


def train_trend_forecaster(spark, component: str) -> None:
    features_path = gold_path(f"{component}_features")
    if not delta_table_exists(spark, features_path):
        print(f"[{component}] skip trend forecaster - missing gold table")
        return

    features_df = spark.read.format("delta").load(features_path)
    avg_24h_cols = [c for c in features_df.columns if c.endswith("_avg_24h")]
    if not avg_24h_cols:
        print(f"[{component}] skip trend forecaster - no *_avg_24h columns")
        return

    daily = (
        features_df.withColumn("day", F.date_trunc("day", "time_stamp"))
        .groupBy("asset_id", "day")
        .agg(*[F.avg(c).alias(c) for c in avg_24h_cols])
    )
    pdf_all = daily.toPandas()

    def health_index(pdf: pd.DataFrame) -> pd.Series:
        z = (pdf[avg_24h_cols] - pdf[avg_24h_cols].mean()) / pdf[avg_24h_cols].std(ddof=0).replace(0, np.nan)
        return -z.mean(axis=1)

    registered_model_name = f"{component}_trend_forecaster_{ENV_LABEL}"
    mlflow.set_experiment(f"wtb-pdm-{ENV_LABEL}/{component}_trend_forecaster")
    trained_any = False

    for asset_id, asset_pdf in pdf_all.groupby("asset_id"):
        asset_pdf = asset_pdf.sort_values("day").reset_index(drop=True)
        if len(asset_pdf) < MIN_DAYS_TO_FIT_TREND:
            continue
        series = health_index(asset_pdf).ffill().bfill()
        if series.isna().all():
            continue

        with mlflow.start_run(run_name=f"{component}_{asset_id}_trend"):
            mlflow.set_tag("asset_id", str(asset_id))
            mlflow.set_tag("component", component)
            mlflow.log_param("n_days", len(series))

            model = ExponentialSmoothing(
                series, trend="add", damped_trend=True, seasonal=None, initialization_method="estimated"
            ).fit()
            fitted = model.fittedvalues
            resid_rmse = float(np.sqrt(np.mean((series - fitted) ** 2)))
            mlflow.log_metric("fit_rmse", resid_rmse)
            forecast_14d = model.forecast(14)
            mlflow.log_metric("forecast_day14_health_index", float(forecast_14d.iloc[-1]))
            mlflow.statsmodels.log_model(
                model, artifact_path="model", registered_model_name=registered_model_name,
            )
            trained_any = True

    if trained_any:
        print(f"[{component}] trend forecasters trained, registered under {registered_model_name}")
    else:
        print(f"[{component}] skip trend forecaster - no asset had >= {MIN_DAYS_TO_FIT_TREND} days of data")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=COMPONENTS, default=None)
    args = parser.parse_args()

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"))

    spark = build_spark("train-models")
    try:
        components = [args.component] if args.component else COMPONENTS
        for component in components:
            print(f"=== {component} ===")
            train_fault_classifier(spark, component)
            train_rul_regressor(spark, component)
            train_trend_forecaster(spark, component)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
