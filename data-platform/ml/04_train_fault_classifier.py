# Databricks notebook source
# MAGIC %md
# MAGIC ## Fault classifier: multi-class LightGBM per component
# MAGIC Trains one multi-class classifier per component (gearbox/hydraulics/pitch) against
# MAGIC that component's Gold feature table, labeled via `gold.fault_events` category. Rows with
# MAGIC no event overlap are labeled "healthy". Registered as `<component>_fault_classifier_<env>`.

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Target environment (dev/staging/uat)")
dbutils.widgets.text(
    "component", "gearbox",
    "Component (gearbox/hydraulics/pitch/generator/transformer/rotor_brake/vibration)",
)

env = dbutils.widgets.get("env")
component = dbutils.widgets.get("component")

catalog = env
assert component in {"gearbox", "hydraulics", "pitch", "generator", "transformer", "rotor_brake", "vibration"}

# COMMAND ----------

import mlflow
import lightgbm as lgb
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, classification_report
from pyspark.sql import functions as F

mlflow.set_experiment(f"/Shared/wtb-pdm/{component}_fault_classifier_{env}")

# COMMAND ----------

features_df = spark.table(f"{catalog}.gold.{component}_features")
fault_events = spark.table(f"{catalog}.gold.fault_events").select(
    F.col("farm").alias("fe_farm"), F.col("event_id").alias("fe_event_id"), "category"
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

# COMMAND ----------

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

# COMMAND ----------

params = {
    "objective": "multiclass",
    "num_class": len(label_names),
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 20,
}

with mlflow.start_run(run_name=f"{component}_fault_classifier") as run:
    mlflow.log_params(params)
    mlflow.log_param("n_features", len(feature_cols))
    mlflow.log_param("classes", label_names)

    train_set = lgb.Dataset(X_train, label=y_train)
    valid_set = lgb.Dataset(X_test, label=y_test, reference=train_set)

    model = lgb.train(
        params,
        train_set,
        num_boost_round=200,
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(stopping_rounds=20), lgb.log_evaluation(period=0)],
    )

    preds = model.predict(X_test).argmax(axis=1)
    macro_f1 = f1_score(y_test, preds, average="macro")
    mlflow.log_metric("macro_f1", macro_f1)
    print(classification_report(y_test, preds, target_names=label_names, zero_division=0))

    mlflow.lightgbm.log_model(
        model,
        artifact_path="model",
        registered_model_name=f"{component}_fault_classifier_{env}",
    )

print(f"run_id={run.info.run_id} macro_f1={macro_f1:.4f}")
