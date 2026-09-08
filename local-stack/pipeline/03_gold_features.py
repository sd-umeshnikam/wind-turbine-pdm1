"""Gold: component features, fault events, RUL labels (local port of
data-platform/notebooks/gold/03_features_and_labels.py - identical
COMPONENT_KEYWORDS/FAULT_CATEGORY_KEYWORDS/rolling-window logic, path-based Delta
tables instead of Unity Catalog, feature_description.csv read directly from the raw
dataset folder).

Usage: python 03_gold_features.py [--rul-horizon-hours 720]
"""
from __future__ import annotations

import argparse
from functools import reduce

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from common import (
    FARMS,
    build_spark,
    delta_table_exists,
    gold_path,
    raw_event_info_path,
    raw_feature_description_path,
    silver_path,
)

# component -> keywords matched (case-insensitive, substring) against feature_description.description
COMPONENT_KEYWORDS = {
    "gearbox": ["gear", "planetary bearing"],
    "hydraulics": ["hydraulic"],
    "pitch": ["pitch", "blade"],
    "generator": ["generator"],
    "transformer": ["transformer"],
    "rotor_brake": ["rotor brake", "brake"],
    "vibration": ["vibration"],
}

# gold.fault_events category keywords, matched against event_description; first match wins
FAULT_CATEGORY_KEYWORDS = [
    ("gearbox", ["gearbox", "gear box"]),
    ("hydraulic", ["hydraulic"]),
    ("pitch", ["pitch"]),
    ("generator", ["generator"]),
    ("transformer", ["transformer"]),
    ("converter", ["converter", "inverter"]),
    ("yaw", ["yaw"]),
    ("plc_communication", ["plc", "communication"]),
    ("rotor_brake", ["rotor brake", "brake"]),
    ("bearing", ["bearing", "lager"]),
]

ROLLING_WINDOWS_HOURS = [1, 6, 24]


def matching_base_sensors(spark, farm: str, keywords: list[str]) -> list[str]:
    fd = spark.read.option("header", "true").csv(str(raw_feature_description_path(farm)))
    pattern = "|".join(keywords)
    rows = (
        fd.filter(F.lower(F.col("description")).rlike(pattern))
        .select("sensor_name")
        .distinct()
        .collect()
    )
    return [r["sensor_name"] for r in rows]


def resolve_component_columns(spark, farm: str, component: str, available_columns: set) -> list[str]:
    base_names = matching_base_sensors(spark, farm, COMPONENT_KEYWORDS[component])
    resolved = []
    for base in base_names:
        avg_col = f"{base}_avg"
        if avg_col in available_columns:
            resolved.append(avg_col)
        elif base in available_columns:
            resolved.append(base)
    return sorted(set(resolved))


def build_component_features(spark, component: str) -> DataFrame | None:
    per_farm_frames = []
    for farm in FARMS:
        path = silver_path(farm)
        if not delta_table_exists(spark, path):
            continue
        silver_df = spark.read.format("delta").load(path)
        sensor_cols = resolve_component_columns(spark, farm, component, set(silver_df.columns))
        if not sensor_cols:
            continue

        base = silver_df.select(
            "farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", *sensor_cols
        )
        ts_seconds = F.col("time_stamp").cast("long")
        agg_exprs = []
        for hours in ROLLING_WINDOWS_HOURS:
            w = Window.partitionBy("asset_id").orderBy(ts_seconds).rangeBetween(-hours * 3600, 0)
            for c in sensor_cols:
                agg_exprs.append(F.avg(c).over(w).alias(f"{c}_avg_{hours}h"))
                agg_exprs.append(F.stddev(c).over(w).alias(f"{c}_std_{hours}h"))

        farm_features = base.select(
            "farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", *agg_exprs
        )
        per_farm_frames.append(farm_features)

    if not per_farm_frames:
        return None
    return reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), per_farm_frames)


def classify_fault_category(description_col):
    expr = F.lit("other")
    for category, keywords in reversed(FAULT_CATEGORY_KEYWORDS):
        pattern = "|".join(keywords)
        expr = F.when(F.lower(description_col).rlike(pattern), F.lit(category)).otherwise(expr)
    return expr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rul-horizon-hours", type=int, default=720)
    args = parser.parse_args()

    spark = build_spark("gold-features")
    try:
        # --- component feature tables ---
        for component in COMPONENT_KEYWORDS:
            features_df = build_component_features(spark, component)
            if features_df is None:
                print(f"skipped {component}_features - no farm matched this component's sensors")
                continue
            out_path = gold_path(f"{component}_features")
            features_df.write.format("delta").mode("overwrite").option(
                "overwriteSchema", "true"
            ).partitionBy("farm").save(out_path)
            print(f"wrote {out_path}")

        # --- fault_events ---
        fault_event_frames = []
        for farm in FARMS:
            event_info_file = raw_event_info_path(farm)
            if not event_info_file.exists():
                continue
            event_info = spark.read.option("header", "true").csv(str(event_info_file))
            farm_events = (
                event_info.filter(F.col("event_label") == "anomaly")
                .withColumn("farm", F.lit(farm))
                .withColumn("category", classify_fault_category(F.col("event_description")))
                .withColumn("event_start", F.to_utc_timestamp(F.to_timestamp("event_start"), "UTC"))
                .withColumn("event_end", F.to_utc_timestamp(F.to_timestamp("event_end"), "UTC"))
                .select("farm", "event_id", "category", "event_start", "event_end", "event_description")
            )
            fault_event_frames.append(farm_events)

        if fault_event_frames:
            fault_events_df = reduce(lambda a, b: a.unionByName(b), fault_event_frames)
            asset_lookup_frames = []
            for farm in FARMS:
                path = silver_path(farm)
                if delta_table_exists(spark, path):
                    asset_lookup_frames.append(
                        spark.read.format("delta")
                        .load(path)
                        .filter(F.col("event_id").isNotNull())
                        .select("farm", "event_id", "asset_id")
                        .distinct()
                    )
            asset_lookup = reduce(lambda a, b: a.unionByName(b), asset_lookup_frames)
            fault_events_df = fault_events_df.join(asset_lookup, on=["farm", "event_id"], how="left")

            fault_events_path = gold_path("fault_events")
            fault_events_df.write.format("delta").mode("overwrite").option(
                "overwriteSchema", "true"
            ).save(fault_events_path)
            print(f"wrote {fault_events_path}")

        # --- rul_labels ---
        rul_frames = []
        for farm in FARMS:
            path = silver_path(farm)
            if not delta_table_exists(spark, path):
                continue
            silver_df = spark.read.format("delta").load(path)

            anomaly_events = (
                spark.read.format("delta")
                .load(gold_path("fault_events"))
                .filter(F.col("farm") == farm)
                .select(
                    F.col("event_id").alias("fe_event_id"),
                    F.col("asset_id").alias("fe_asset_id"),
                    F.col("event_start").alias("fe_event_start"),
                )
            )

            candidate = (
                silver_df.filter(F.col("event_id").isNull())
                .join(
                    F.broadcast(anomaly_events),
                    on=(F.col("asset_id") == F.col("fe_asset_id"))
                    & (F.col("time_stamp") < F.col("fe_event_start")),
                    how="inner",
                )
                .withColumn(
                    "hours_to_failure",
                    (F.col("fe_event_start").cast("long") - F.col("time_stamp").cast("long")) / 3600.0,
                )
                .filter(F.col("hours_to_failure") <= args.rul_horizon_hours)
            )

            nearest_window = Window.partitionBy("asset_id", "time_stamp").orderBy("hours_to_failure")
            pre_event = (
                candidate.withColumn("_rn", F.row_number().over(nearest_window))
                .filter(F.col("_rn") == 1)
                .select(
                    F.lit(farm).alias("farm"),
                    "asset_id",
                    "time_stamp",
                    F.col("fe_event_id").alias("event_id"),
                    "hours_to_failure",
                )
            )
            rul_frames.append(pre_event)

        if rul_frames:
            rul_labels_df = reduce(lambda a, b: a.unionByName(b), rul_frames)
            rul_path = gold_path("rul_labels")
            rul_labels_df.write.format("delta").mode("overwrite").option(
                "overwriteSchema", "true"
            ).partitionBy("farm").save(rul_path)
            print(f"wrote {rul_path}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
