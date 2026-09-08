# Databricks notebook source
# MAGIC %md
# MAGIC ## Bronze: raw SCADA ingest
# MAGIC Streams each farm's raw per-turbine CSVs from `s3://<env>-wtb-bronze/farm=<farm>/turbine=<asset_id>/`
# MAGIC into an append-only Delta bronze table using Auto Loader. Schema-on-read: bronze keeps
# MAGIC every source column as-is (including farm-specific sensor columns) and lets Auto Loader
# MAGIC infer/evolve the schema, since Farm A/B/C column sets are not unified upstream.

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Target environment (dev/staging/uat)")
dbutils.widgets.text("farm", "A", "Wind farm (A/B/C)")

env = dbutils.widgets.get("env")
farm = dbutils.widgets.get("farm").upper()

assert env in {"dev", "staging", "uat"}, f"unexpected env: {env}"
assert farm in {"A", "B", "C"}, f"unexpected farm: {farm}"

# COMMAND ----------

catalog = env
bronze_schema = "bronze"
table_name = f"farm_{farm.lower()}_raw"

source_path = f"s3://{env}-wtb-bronze/farm={farm}/"
checkpoint_path = f"s3://{env}-wtb-bronze/_checkpoints/bronze/{table_name}/"
schema_location = f"s3://{env}-wtb-bronze/_schemas/bronze/{table_name}/"

spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{bronze_schema}")

# COMMAND ----------

from pyspark.sql import functions as F

raw_stream = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "csv")
    .option("cloudFiles.schemaLocation", schema_location)
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
    .option("header", "true")
    .option("cloudFiles.maxFilesPerTrigger", 1000)
    .load(source_path)
    # `turbine=<asset_id>` path segment is redundant with the `asset_id` column already present
    # in every row, but we keep it for lineage/debugging and as a partition-pruning hint.
    .withColumn("_source_file", F.input_file_name())
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("farm", F.lit(farm))
)

# COMMAND ----------

query = (
    raw_stream.writeStream.format("delta")
    .option("checkpointLocation", checkpoint_path)
    .option("mergeSchema", "true")
    .partitionBy("farm")
    .trigger(availableNow=True)
    .outputMode("append")
    .toTable(f"{catalog}.{bronze_schema}.{table_name}")
)

query.awaitTermination()

# COMMAND ----------

print(f"Bronze ingest complete for farm={farm}, env={env} -> {catalog}.{bronze_schema}.{table_name}")
