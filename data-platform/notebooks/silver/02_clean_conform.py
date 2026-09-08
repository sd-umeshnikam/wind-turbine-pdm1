# Databricks notebook source
# MAGIC %md
# MAGIC ## Silver: clean, dedup, conform, event-tag
# MAGIC Reads `bronze.farm_<x>_raw`, normalizes timestamps to UTC, validates `status_type_id`,
# MAGIC dedups on `(asset_id, time_stamp)`, and left-joins each farm's `event_info` to tag rows
# MAGIC that fall inside a labeled event window. Farms stay in separate tables (`silver.farm_a`,
# MAGIC `silver.farm_b`, `silver.farm_c`) because column sets barely overlap across farms.

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Target environment (dev/staging/uat)")
dbutils.widgets.text("farm", "A", "Wind farm (A/B/C)")
dbutils.widgets.text("source_timezone", "UTC", "Timezone of raw time_stamp values")

env = dbutils.widgets.get("env")
farm = dbutils.widgets.get("farm").upper()
source_tz = dbutils.widgets.get("source_timezone")

assert env in {"dev", "staging", "uat"}, f"unexpected env: {env}"
assert farm in {"A", "B", "C"}, f"unexpected farm: {farm}"

# COMMAND ----------

catalog = env
bronze_table = f"{catalog}.bronze.farm_{farm.lower()}_raw"
silver_schema = "silver"
silver_table = f"{catalog}.{silver_schema}.farm_{farm.lower()}"

# event_info.csv is a small per-farm reference file landed alongside the turbine data,
# not streamed through Auto Loader like the high-volume SCADA files.
event_info_path = f"s3://{env}-wtb-bronze/farm={farm}/event_info/"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{silver_schema}")

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.window import Window

bronze_df = spark.table(bronze_table)

VALID_STATUS_IDS = {0, 1, 2, 3, 4, 5}

cleaned = (
    bronze_df
    # source time_stamp has no offset info; convert from the farm's recorded source timezone to UTC
    .withColumn(
        "time_stamp_utc",
        F.to_utc_timestamp(F.to_timestamp("time_stamp"), source_tz),
    )
    .withColumn("status_type_id", F.col("status_type_id").cast("int"))
    .filter(F.col("status_type_id").isin(list(VALID_STATUS_IDS)))
    .filter(F.col("time_stamp_utc").isNotNull() & F.col("asset_id").isNotNull())
)

# COMMAND ----------

# dedup on (asset_id, time_stamp): keep the most recently ingested row per key
dedup_window = Window.partitionBy("asset_id", "time_stamp_utc").orderBy(F.col("_ingested_at").desc())

deduped = (
    cleaned
    .withColumn("_rn", F.row_number().over(dedup_window))
    .filter(F.col("_rn") == 1)
    .drop("_rn")
)

# COMMAND ----------

event_info = (
    spark.read.option("header", "true").csv(event_info_path)
    .withColumn("event_start_utc", F.to_utc_timestamp(F.to_timestamp("event_start"), source_tz))
    .withColumn("event_end_utc", F.to_utc_timestamp(F.to_timestamp("event_end"), source_tz))
    .select(
        F.col("event_id"),
        F.col("event_label"),
        F.col("event_description"),
        "event_start_utc",
        "event_end_utc",
    )
)

# each row can only fall in one event window per farm, but the join is a range join
# (not equi-join), so broadcast the small event_info table to avoid a full shuffle join.
join_condition = (F.col("s.time_stamp_utc") >= F.col("e.event_start_utc")) & (
    F.col("s.time_stamp_utc") <= F.col("e.event_end_utc")
)

tagged = (
    deduped.alias("s")
    .join(F.broadcast(event_info).alias("e"), on=join_condition, how="left")
    .select(
        "s.*",
        F.col("e.event_id").alias("event_id"),
        F.col("e.event_label").alias("event_label"),
        F.col("e.event_description").alias("event_description"),
    )
    .drop("time_stamp")
    .withColumnRenamed("time_stamp_utc", "time_stamp")
)

# COMMAND ----------

from delta.tables import DeltaTable

if not spark.catalog.tableExists(silver_table):
    (
        tagged.limit(0).write.format("delta")
        .partitionBy("farm")
        .saveAsTable(silver_table)
    )

target = DeltaTable.forName(spark, silver_table)

# MERGE INTO on (asset_id, time_stamp): idempotent upsert so re-running a batch (or a late
# file) never creates duplicate rows, and a row's event tag can be refreshed if event_info changes.
(
    target.alias("t")
    .merge(
        tagged.alias("src"),
        "t.asset_id = src.asset_id AND t.time_stamp = src.time_stamp",
    )
    .whenMatchedUpdateAll()
    .whenNotMatchedInsertAll()
    .execute()
)

print(f"Silver conform complete for farm={farm}, env={env} -> {silver_table}")
