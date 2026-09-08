# Databricks notebook source
# MAGIC %md
# MAGIC ## RUL regressor: quantile regression (P10/P50/P90) per component
# MAGIC Trains three LightGBM quantile regressors (alpha 0.1/0.5/0.9) per component against
# MAGIC `gold.rul_labels` joined to that component's Gold features, predicting hours-to-failure.
# MAGIC Only ~44 labeled anomaly events exist fleet-wide, so this stays a single shared model per
# MAGIC component rather than per-asset models. Registered as `<component>_rul_p{10,50,90}_<env>`.

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
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_pinball_loss

mlflow.set_experiment(f"/Shared/wtb-pdm/{component}_rul_regressor_{env}")

# COMMAND ----------

features_df = spark.table(f"{catalog}.gold.{component}_features")
rul_labels = spark.table(f"{catalog}.gold.rul_labels")

labeled = features_df.join(rul_labels, on=["farm", "asset_id", "time_stamp", "event_id"], how="inner")
pdf = labeled.toPandas()

feature_cols = [
    c for c in pdf.columns
    if c not in {"farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", "hours_to_failure"}
]
pdf[feature_cols] = pdf[feature_cols].fillna(pdf[feature_cols].median(numeric_only=True))

X = pdf[feature_cols]
y = pdf["hours_to_failure"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# COMMAND ----------

QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}

with mlflow.start_run(run_name=f"{component}_rul_regressor") as run:
    mlflow.log_param("n_features", len(feature_cols))
    mlflow.log_param("n_train_rows", len(X_train))

    for name, alpha in QUANTILES.items():
        params = {
            "objective": "quantile",
            "alpha": alpha,
            "metric": "quantile",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_data_in_leaf": 20,
        }
        train_set = lgb.Dataset(X_train, label=y_train)
        valid_set = lgb.Dataset(X_test, label=y_test, reference=train_set)

        model = lgb.train(
            params,
            train_set,
            num_boost_round=200,
            valid_sets=[valid_set],
            callbacks=[lgb.early_stopping(stopping_rounds=20), lgb.log_evaluation(period=0)],
        )

        preds = model.predict(X_test)
        pinball = mean_pinball_loss(y_test, preds, alpha=alpha)
        mlflow.log_metric(f"pinball_loss_{name}", pinball)

        mlflow.lightgbm.log_model(
            model,
            artifact_path=f"model_{name}",
            registered_model_name=f"{component}_rul_{name}_{env}",
        )
        print(f"{name}: pinball_loss={pinball:.4f}")

print(f"run_id={run.info.run_id}")
