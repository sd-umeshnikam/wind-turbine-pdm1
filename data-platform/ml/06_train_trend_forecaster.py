# Databricks notebook source
# MAGIC %md
# MAGIC ## Trend forecaster: classical ETS on a per-component health index
# MAGIC Deliberately classical (statsmodels ETS), not deep learning: only ~44 labeled anomaly
# MAGIC events exist fleet-wide, nowhere near enough to train a sequence model per component.
# MAGIC Builds a simple health index (mean of z-scored rolling-24h sensor averages, inverted so
# MAGIC higher = healthier) per asset, fits one ETS model per asset, and registers each as a new
# MAGIC version of the shared `<component>_trend_forecaster_<env>` model, tagged with its asset_id.

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
import pandas as pd
import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from pyspark.sql import functions as F

mlflow.set_experiment(f"/Shared/wtb-pdm/{component}_trend_forecaster_{env}")
registered_model_name = f"{component}_trend_forecaster_{env}"

# COMMAND ----------

features_df = spark.table(f"{catalog}.gold.{component}_features")
avg_24h_cols = [c for c in features_df.columns if c.endswith("_avg_24h")]
assert avg_24h_cols, f"no *_avg_24h columns found for component={component}"

daily = (
    features_df
    .withColumn("day", F.date_trunc("day", "time_stamp"))
    .groupBy("asset_id", "day")
    .agg(*[F.avg(c).alias(c) for c in avg_24h_cols])
)
pdf_all = daily.toPandas()

# COMMAND ----------

def health_index(pdf: pd.DataFrame) -> pd.Series:
    # z-score each sensor's daily average, average across sensors, negate: higher score = healthier
    z = (pdf[avg_24h_cols] - pdf[avg_24h_cols].mean()) / pdf[avg_24h_cols].std(ddof=0).replace(0, np.nan)
    return -z.mean(axis=1)


# COMMAND ----------

MIN_DAYS_TO_FIT = 30

for asset_id, asset_pdf in pdf_all.groupby("asset_id"):
    asset_pdf = asset_pdf.sort_values("day").reset_index(drop=True)
    if len(asset_pdf) < MIN_DAYS_TO_FIT:
        continue

    series = health_index(asset_pdf).fillna(method="ffill").fillna(method="bfill")
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
            model,
            artifact_path="model",
            registered_model_name=registered_model_name,
        )

print(f"trained trend forecasters for component={component}, registered under {registered_model_name}")
