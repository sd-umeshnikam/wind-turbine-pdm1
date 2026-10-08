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
import gc
import os
import shutil
import sys
import tempfile

import mlflow
import mlflow.lightgbm
import mlflow.statsmodels
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import f1_score, classification_report, mean_pinball_loss
from sklearn.model_selection import train_test_split
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from pyspark.sql import DataFrame, functions as F

from common import build_spark, delta_table_exists, gold_path

COMPONENTS = [
    "gearbox", "hydraulics", "pitch", "generator", "transformer", "rotor_brake", "vibration",
]
ENV_LABEL = "local"
MIN_DAYS_TO_FIT_TREND = 30


def _free_memory(spark) -> None:
    """clearCache() alone (tried between components) wasn't enough - the run still
    died mid-component, in the 2nd of 3 per-farm write/read cycles inside a single
    _collect_to_pandas call, meaning JVM garbage (query plans, codegen classes)
    from earlier writes in the SAME session was still live when the next one
    started. clearCache() only evicts persisted tables, not general JVM garbage,
    so this also forces both GCs directly - called after every per-farm write and
    after every train_* call, not just between components."""
    spark.catalog.clearCache()
    gc.collect()
    spark.sparkContext._jvm.System.gc()


def _downcast_doubles(df: DataFrame) -> DataFrame:
    """double -> float halves toPandas() memory (gearbox_features alone is ~4.7M
    rows x 257 cols, ~10GB as float64 - overran this machine's RAM). LightGBM/ETS
    don't need float64 precision for sensor telemetry, so this only affects memory,
    not which rows/columns feed the model."""
    return df.select([
        F.col(c).cast("float") if t == "double" else F.col(c) for c, t in df.dtypes
    ])


MAX_COLLECT_ROWS = 2_000_000


def _collect_to_pandas(df: DataFrame) -> pd.DataFrame:
    """toPandas() collects via py4j's JVM<->Python socket, which buffers the whole
    Arrow result in the JVM and then copies it again across the socket - for
    gearbox_features (~4.7M rows x 257 cols) that doubled peak memory right at the
    worst moment and crashed the JVM (OSError: truncated message body) even after
    _downcast_doubles halved the row size. Writing to local Parquet and reading it
    back with pyarrow sidesteps that socket transfer entirely.

    Writing all 3 farms in one query still crashed the JVM even after that fix and
    after raising driver memory well past what a single farm needs - isolating just
    farm C (the largest, ~61% of gearbox_features' rows) to its own write succeeded
    cleanly every time, so whatever accumulates does so across farms within one
    query, not from data volume alone. Splitting into one independent write per
    farm and concatenating in pandas afterward sidesteps that without changing the
    combined result callers see - same rows, same columns, same pooled dataset.

    Stopping the JVM before the pandas/LightGBM phase (see below) recovered some
    headroom but pure pandas/LightGBM training on the full 4.7M-row table still
    peaked at ~12GB on its own - genuine data volume, not overhead left to trim.
    Capping at MAX_COLLECT_ROWS via a random sample keeps peak memory well under
    this machine's ceiling; for gradient-boosted trees a multi-million-row random
    sample is typically close to as good as the full table."""
    spark = df.sparkSession
    tmp_dir = tempfile.mkdtemp(prefix="collect_")
    try:
        total = df.count()
        if total > MAX_COLLECT_ROWS:
            df = df.sample(fraction=MAX_COLLECT_ROWS / total, seed=42)
        farms = [row["farm"] for row in df.select("farm").distinct().collect()]
        if not farms:
            # empty join result (e.g. gearbox's RUL labels matched zero feature
            # rows) - pd.concat([]) raises ValueError, so short-circuit with an
            # empty frame of the right shape instead of writing/reading nothing.
            result = _downcast_doubles(df).limit(0).toPandas()
        else:
            frames = []
            for farm in farms:
                farm_dir = os.path.join(tmp_dir, f"farm={farm}")
                _downcast_doubles(df.filter(F.col("farm") == farm)).write.mode("overwrite").parquet(farm_dir)
                frames.append(pd.read_parquet(farm_dir))
                _free_memory(spark)
            result = pd.concat(frames, ignore_index=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # PySpark's JVM is a *separate OS process* from this Python driver - capping
    # spark.driver.memory only bounds the JVM's own heap, and none of that heap is
    # released back to the OS just because clearCache()/System.gc() ran (the JVM
    # keeps committed memory for its own future use). So even after collection
    # finished cleanly (confirmed via docker stats staying under ~4GB), the JVM
    # was still sitting on several GB when LightGBM/pandas then needed several GB
    # more in this SAME container - together that's what exceeded the ceiling,
    # not either process alone. Every caller of this function is done with Spark
    # by the time it returns, so stopping the session here hands the JVM's entire
    # footprint back to the OS before the memory-heavy pandas/LightGBM/statsmodels
    # work starts. main() rebuilds a fresh session before the next call needs one.
    spark.stop()
    return result


def train_fault_classifier(spark, component: str) -> None:
    features_path = gold_path(f"{component}_features")
    events_path = gold_path("fault_events")
    if not delta_table_exists(spark, features_path) or not delta_table_exists(spark, events_path):
        print(f"[{component}] skip fault classifier - missing gold table(s)")
        return

    features_df = spark.read.format("delta").load(features_path)
    # event_id is scoped per-asset, not globally unique per farm (matches
    # 03_gold_features.py's RUL-labeling join, which also keys on asset_id for
    # the same reason) - joining on (farm, event_id) alone lets fault_events'
    # per-asset duplicates fan out every matching feature row once per asset that
    # happens to reuse that event_id number (e.g. farm=C event_id=67 had 53,563
    # gearbox rows x 7 duplicate fault_events rows = ~375K exploded rows for one
    # event), which is what actually blew up toPandas()'s memory, not row/column
    # volume alone.
    fault_events = (
        spark.read.format("delta")
        .load(events_path)
        .select(
            F.col("farm").alias("fe_farm"),
            F.col("asset_id").alias("fe_asset_id"),
            F.col("event_id").alias("fe_event_id"),
            "category",
        )
    )
    labeled = (
        features_df.join(
            fault_events,
            on=(features_df.farm == F.col("fe_farm"))
            & (features_df.asset_id == F.col("fe_asset_id"))
            & (features_df.event_id == F.col("fe_event_id")),
            how="left",
        )
        .withColumn("label", F.coalesce(F.col("category"), F.lit("healthy")))
        .drop("fe_farm", "fe_asset_id", "fe_event_id", "category")
    )
    pdf = _collect_to_pandas(labeled)
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
    # gearbox alone is 4.7M rows x 257 cols (~5GB as float32) - pdf, X, X_train,
    # X_test, and LightGBM's own Dataset copy all being alive at once is what
    # actually crashed this (climbed past 12GB and got OOM-killed), not anything
    # on the Spark side, which was already confirmed to complete comfortably under
    # 4GB on its own. Dropping each large object once its last use has passed
    # keeps peak memory closer to one copy of the data instead of three or four.
    del pdf, y
    gc.collect()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_codes, test_size=0.2, random_state=42, stratify=y_codes if y_codes.nunique() > 1 else None
    )
    del X
    gc.collect()

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
        # lgb.Dataset defaults to free_raw_data=True, so train_set/valid_set have
        # already dropped their own reference to X_train/X_test's data by this
        # point - only this function's own X_train variable is still holding it.
        del X_train
        gc.collect()

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

    # rul_labels.event_id is the *upcoming* failure a pre-event reading precedes
    # (see 03_gold_features.py's RUL section: built only from silver rows where
    # event_id IS NULL, then labeled with the next anomaly's event_id) - it's not
    # the same thing as features_df's own event_id, which stays NULL for exactly
    # these pre-event rows. Joining on event_id as if they were the same column
    # required NULL = <upcoming event id>, which never matches, so every
    # component's RUL regressor silently "trained" on zero rows. Drop
    # features_df's (meaningless, always-null-here) event_id before joining so
    # rul_labels' actual event_id - the one worth keeping - survives unambiguous.
    features_df = spark.read.format("delta").load(features_path).drop("event_id")
    rul_labels = spark.read.format("delta").load(rul_path)
    labeled = features_df.join(rul_labels, on=["farm", "asset_id", "time_stamp"], how="inner")
    pdf = _collect_to_pandas(labeled)
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
    del pdf
    gc.collect()

    if len(X) < 10:
        print(f"[{component}] skip RUL regressor - only {len(X)} labeled rows, too few to split")
        return
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    del X, y
    gc.collect()

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
        # asset_id alone isn't a safe grouping key (raw asset_id values aren't
        # globally unique across farms - see common.py's turbine_id_map comment),
        # matching why every join elsewhere in this file scopes by farm too. Also
        # gives _collect_to_pandas the "farm" column its per-farm split needs.
        .groupBy("farm", "asset_id", "day")
        .agg(*[F.avg(c).alias(c) for c in avg_24h_cols])
    )
    pdf_all = _collect_to_pandas(daily)

    def health_index(pdf: pd.DataFrame) -> pd.Series:
        z = (pdf[avg_24h_cols] - pdf[avg_24h_cols].mean()) / pdf[avg_24h_cols].std(ddof=0).replace(0, np.nan)
        return -z.mean(axis=1)

    registered_model_name = f"{component}_trend_forecaster_{ENV_LABEL}"
    mlflow.set_experiment(f"wtb-pdm-{ENV_LABEL}/{component}_trend_forecaster")
    trained_any = False

    # groups by (farm, asset_id): raw asset_id values aren't globally unique across
    # farms, so grouping by asset_id alone could merge two different turbines'
    # time series into one health index.
    for (farm, asset_id), asset_pdf in pdf_all.groupby(["farm", "asset_id"]):
        asset_pdf = asset_pdf.sort_values("day").reset_index(drop=True)
        if len(asset_pdf) < MIN_DAYS_TO_FIT_TREND:
            continue
        series = health_index(asset_pdf).ffill().bfill()
        if series.isna().all():
            continue

        with mlflow.start_run(run_name=f"{component}_{farm}_{asset_id}_trend"):
            mlflow.set_tag("farm", str(farm))
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
    # Buffered stdout meant every OOM-kill during this file's memory debugging lost
    # whatever print() output hadn't been flushed yet, making it look like crashes
    # happened earlier than they really did. Line-buffering keeps the log honest.
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=COMPONENTS, default=None)
    args = parser.parse_args()

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"))

    def run_step(step_fn, component: str) -> None:
        # build_spark() uses getOrCreate(), which hands back the existing session
        # (JVM and all) if one is still alive rather than starting a fresh one - so
        # every step needs its session stopped before the next one is built, not
        # just eventually at the end of main(). _collect_to_pandas already stops
        # its own session right before the memory-heavy pandas/LightGBM/statsmodels
        # work starts (the case that actually matters for peak memory); this
        # try/finally is the safety net for steps that skip/return before ever
        # reaching _collect_to_pandas (e.g. a missing gold table).
        spark = build_spark("train-models")
        try:
            step_fn(spark, component)
        finally:
            spark.stop()

    components = [args.component] if args.component else COMPONENTS
    for component in components:
        print(f"=== {component} ===")
        run_step(train_fault_classifier, component)
        run_step(train_rul_regressor, component)
        run_step(train_trend_forecaster, component)


if __name__ == "__main__":
    main()
