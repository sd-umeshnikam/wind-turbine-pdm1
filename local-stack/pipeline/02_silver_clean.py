"""Silver: clean, dedup, conform, event-tag (local port of
data-platform/notebooks/silver/02_clean_conform.py - same logic, path-based Delta
tables instead of Unity Catalog, event_info read directly from the raw dataset
folder instead of a separate S3 reference path).

Usage: python 02_silver_clean.py --farm A [--source-timezone UTC]
"""
from __future__ import annotations

import argparse

from delta.tables import DeltaTable
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from common import (
    build_spark,
    bronze_path,
    delta_table_exists,
    raw_event_info_path,
    save_turbine_id_map_for_farm,
    silver_path,
)

VALID_STATUS_IDS = [0, 1, 2, 3, 4, 5]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--farm", required=True, choices=["A", "B", "C"])
    parser.add_argument("--source-timezone", default="UTC")
    args = parser.parse_args()
    farm = args.farm

    spark = build_spark(f"silver-clean-{farm}")
    try:
        bronze_df = spark.read.format("delta").load(bronze_path(farm))

        cleaned = (
            bronze_df.withColumn(
                "time_stamp_utc",
                F.to_utc_timestamp(F.to_timestamp("time_stamp"), args.source_timezone),
            )
            .withColumn("status_type_id", F.col("status_type_id").cast("int"))
            .filter(F.col("status_type_id").isin(VALID_STATUS_IDS))
            .filter(F.col("time_stamp_utc").isNotNull() & F.col("asset_id").isNotNull())
        )

        dedup_window = Window.partitionBy("asset_id", "time_stamp_utc").orderBy(
            F.col("_ingested_at").desc()
        )
        deduped = (
            cleaned.withColumn("_rn", F.row_number().over(dedup_window))
            .filter(F.col("_rn") == 1)
            .drop("_rn")
        )

        event_info = (
            spark.read.option("header", "true").csv(str(raw_event_info_path(farm)))
            .withColumn(
                "event_start_utc", F.to_utc_timestamp(F.to_timestamp("event_start"), args.source_timezone)
            )
            .withColumn(
                "event_end_utc", F.to_utc_timestamp(F.to_timestamp("event_end"), args.source_timezone)
            )
            .select("event_id", "event_label", "event_description", "event_start_utc", "event_end_utc")
        )

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

        out_path = silver_path(farm)
        if not delta_table_exists(spark, out_path):
            tagged.limit(0).write.format("delta").partitionBy("farm").save(out_path)

        target = DeltaTable.forPath(spark, out_path)
        (
            target.alias("t")
            .merge(tagged.alias("src"), "t.asset_id = src.asset_id AND t.time_stamp = src.time_stamp")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )

        final_df = spark.read.format("delta").load(out_path)
        row_count = final_df.count()

        distinct_asset_ids = [r["asset_id"] for r in final_df.select("asset_id").distinct().collect()]
        save_turbine_id_map_for_farm(farm, distinct_asset_ids)

        print(
            f"Silver conform complete for farm={farm}: {row_count:,} rows, "
            f"{len(distinct_asset_ids)} turbines -> {out_path}"
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
