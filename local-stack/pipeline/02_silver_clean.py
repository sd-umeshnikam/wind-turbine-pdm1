"""Silver: clean, dedup, conform, event-tag (local port of
data-platform/notebooks/silver/02_clean_conform.py - same logic, path-based Delta
tables instead of Unity Catalog, event_info read directly from the raw dataset
folder instead of a separate S3 reference path).

Usage: python 02_silver_clean.py --farm A [--source-timezone UTC]
"""
from __future__ import annotations

import argparse
import os

from delta.tables import DeltaTable
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from common import (
    build_spark,
    bronze_path,
    delta_table_exists,
    raw_event_info_path,
    raw_feature_description_path,
    save_turbine_id_map_for_farm,
    silver_path,
)

VALID_STATUS_IDS = [0, 1, 2, 3, 4, 5]

# Opt-in, LOCAL-ONLY memory/disk-constrained-machine workaround (Windows-native no-Docker
# hosting, see docs/WINDOWS_HOSTING_GUIDE.md) - NOT part of the shared pipeline logic, off by
# default, and never touches the Linux/Docker or cloud (data-platform/notebooks) path. Wide
# farms (e.g. Farm C: 960 bronze columns = ~240 raw sensors x 4 stats each) blow the local Spark
# driver's sort/shuffle memory and scratch-disk budget on a resource-constrained laptop long
# before the actual row count would. Setting this env var narrows bronze_df, before any
# cleaning/dedup/sort, down to only the columns 03_gold_features.py's resolve_component_columns
# will ever read: gold only ever selects the "<sensor>_avg" variant (falling back to the bare
# name) for sensors matching COMPONENT_KEYWORDS, so "_max"/"_min"/"_std" variants and any sensor
# matching no component are provably dead weight for every downstream script in this pipeline
# (03_gold_features.py, 04_sync_timescale.py - both apply the identical keyword-match themselves
# before reading a farm's silver table). Leave unset for full raw-fidelity silver tables.
LOCAL_NARROW_SILVER_COLUMNS = os.environ.get("LOCAL_NARROW_SILVER_COLUMNS", "") == "1"

# Same local-only, opt-in, off-by-default rationale as LOCAL_NARROW_SILVER_COLUMNS above - even
# with narrowed columns, sorting/shuffling a wide farm's full row count (e.g. Farm C: ~2.8M rows)
# in one pass can still exceed this machine's scratch-disk budget for the merge's shuffle spill.
# When set, this processes one asset_id (turbine) at a time through clean -> dedup -> tag -> merge
# and commits each as its own Delta transaction, so peak shuffle size is bounded by one turbine's
# row count (~1/22th of Farm C) instead of the whole farm at once. Slower wall-clock time (more,
# smaller Spark jobs instead of one big one), same final result (Delta commits are additive) -
# purely a peak-resource-vs-time tradeoff for a memory/disk-constrained machine.
LOCAL_CHUNK_SILVER_BY_ASSET = os.environ.get("LOCAL_CHUNK_SILVER_BY_ASSET", "") == "1"

# Same 7 categories/keywords as 03_gold_features.py's COMPONENT_KEYWORDS and
# 04_sync_timescale.py's COMPONENT_KEYWORDS (duplicated here rather than imported, matching the
# existing "no shared business logic between these standalone numbered scripts" pattern) -
# a sensor matching none of these is never read by any downstream script either way.
COMPONENT_KEYWORDS = {
    "gearbox": ["gear", "planetary bearing"],
    "hydraulics": ["hydraulic"],
    "pitch": ["pitch", "blade"],
    "generator": ["generator"],
    "transformer": ["transformer"],
    "rotor_brake": ["rotor brake", "brake"],
    "vibration": ["vibration"],
}

ALWAYS_KEEP_COLUMNS = [
    "time_stamp",
    "asset_id",
    "id",
    "train_test",
    "status_type_id",
    "_source_file",
    "_ingested_at",
    "farm",
]


def resolve_needed_sensor_columns(spark, farm: str, available_columns: set) -> list[str]:
    """Union, across every COMPONENT_KEYWORDS category, of the columns
    03_gold_features.py's resolve_component_columns would ever select for this farm -
    "<sensor>_avg" preferred, falling back to the bare sensor name."""
    fd = spark.read.option("header", "true").csv(str(raw_feature_description_path(farm)))
    needed = set()
    for keywords in COMPONENT_KEYWORDS.values():
        pattern = "|".join(keywords)
        base_names = [
            r["sensor_name"]
            for r in fd.filter(F.lower(F.col("description")).rlike(pattern))
            .select("sensor_name")
            .distinct()
            .collect()
        ]
        for base in base_names:
            avg_col = f"{base}_avg"
            if avg_col in available_columns:
                needed.add(avg_col)
            elif base in available_columns:
                needed.add(base)
    return sorted(needed)


def build_event_info(spark, farm: str, source_timezone: str):
    return (
        spark.read.option("header", "true").csv(str(raw_event_info_path(farm)))
        .withColumn(
            "event_start_utc", F.to_utc_timestamp(F.to_timestamp("event_start"), source_timezone)
        )
        .withColumn(
            "event_end_utc", F.to_utc_timestamp(F.to_timestamp("event_end"), source_timezone)
        )
        .select("event_id", "event_label", "event_description", "event_start_utc", "event_end_utc")
    )


def clean_dedup_tag(bronze_batch_df, event_info, source_timezone: str):
    """The exact clean -> dedup -> event-tag chain, unchanged, applied to whatever
    bronze rows are handed in - the whole farm at once (default), or one asset_id's
    worth at a time (LOCAL_CHUNK_SILVER_BY_ASSET)."""
    cleaned = (
        bronze_batch_df.withColumn(
            "time_stamp_utc",
            F.to_utc_timestamp(F.to_timestamp("time_stamp"), source_timezone),
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

    join_condition = (F.col("s.time_stamp_utc") >= F.col("e.event_start_utc")) & (
        F.col("s.time_stamp_utc") <= F.col("e.event_end_utc")
    )
    return (
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


def merge_into_silver(spark, tagged, out_path: str):
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--farm", required=True, choices=["A", "B", "C"])
    parser.add_argument("--source-timezone", default="UTC")
    args = parser.parse_args()
    farm = args.farm

    spark = build_spark(f"silver-clean-{farm}")
    try:
        bronze_df = spark.read.format("delta").load(bronze_path(farm))

        if LOCAL_NARROW_SILVER_COLUMNS:
            before = len(bronze_df.columns)
            needed_sensors = resolve_needed_sensor_columns(spark, farm, set(bronze_df.columns))
            keep = [c for c in ALWAYS_KEEP_COLUMNS if c in bronze_df.columns] + needed_sensors
            bronze_df = bronze_df.select(*keep)
            print(
                f"LOCAL_NARROW_SILVER_COLUMNS=1: farm={farm} bronze_df narrowed from "
                f"{before} to {len(keep)} columns (only columns 03_gold_features.py/"
                f"04_sync_timescale.py ever read) - local resource-constrained workaround, "
                f"not the shared pipeline path"
            )

        event_info = build_event_info(spark, farm, args.source_timezone)
        out_path = silver_path(farm)

        if LOCAL_CHUNK_SILVER_BY_ASSET:
            asset_ids = [r["asset_id"] for r in bronze_df.select("asset_id").distinct().collect()]
            print(
                f"LOCAL_CHUNK_SILVER_BY_ASSET=1: farm={farm} processing {len(asset_ids)} turbines "
                f"one at a time (local resource-constrained workaround, not the shared pipeline path)"
            )
            for i, asset_id in enumerate(asset_ids, start=1):
                batch = bronze_df.filter(F.col("asset_id") == asset_id)
                tagged = clean_dedup_tag(batch, event_info, args.source_timezone)
                merge_into_silver(spark, tagged, out_path)
                print(f"  [{i}/{len(asset_ids)}] asset_id={asset_id} merged")
        else:
            tagged = clean_dedup_tag(bronze_df, event_info, args.source_timezone)
            merge_into_silver(spark, tagged, out_path)

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
