"""Syncs a real, bounded slice of Silver sensor readings into TimescaleDB, for
telemetry-api's local (`TELEMETRY_BACKEND=postgres`) backend to query.

SCOPE, stated plainly: this does NOT copy every sensor at full history into
Timescale - Farm C alone has ~240 relevant sensor columns across ~3.2M silver
rows, which melted to long format is not a sensible size for a single-box local
demo. Instead, per farm, it syncs only:
  - the sensor columns already resolved as relevant by the Gold layer's
    COMPONENT_KEYWORDS matching (same logic as 03_gold_features.py, duplicated
    here rather than imported - these are standalone numbered scripts, not a
    shared module, matching the "no shared business logic" pattern already used
    across services/*)
  - each event's own `train_test == 'prediction'` window (the same bounded
    lead-up-through-fault slice eda/scripts/04_degradation_trends.py already
    uses) rather than a turbine's entire history

This is real data, not synthetic - just deliberately scoped to a demo-appropriate
size. See docs/LINUX_HOSTING_GUIDE.md for the full rationale.

Usage: python 04_sync_timescale.py
Requires TIMESCALE_URL env var (see local-stack/docker-compose.yml).
"""
from __future__ import annotations

import os

import psycopg2
import psycopg2.extras
from pyspark.sql import functions as F

from common import (
    FARMS,
    build_spark,
    delta_table_exists,
    raw_feature_description_path,
    silver_path,
    turbine_id_for,
)

COMPONENT_KEYWORDS = {
    "gearbox": ["gear", "planetary bearing"],
    "hydraulics": ["hydraulic"],
    "pitch": ["pitch", "blade"],
    "generator": ["generator"],
    "transformer": ["transformer"],
    "rotor_brake": ["rotor brake", "brake"],
    "vibration": ["vibration"],
}


def matching_base_sensors(spark, farm: str, keywords: list[str]) -> list[str]:
    fd = spark.read.option("header", "true").csv(str(raw_feature_description_path(farm)))
    pattern = "|".join(keywords)
    rows = (
        fd.filter(F.lower(F.col("description")).rlike(pattern)).select("sensor_name").distinct().collect()
    )
    return [r["sensor_name"] for r in rows]


def resolve_relevant_columns(spark, farm: str, available_columns: set) -> list[str]:
    resolved = set()
    for keywords in COMPONENT_KEYWORDS.values():
        for base in matching_base_sensors(spark, farm, keywords):
            avg_col = f"{base}_avg"
            if avg_col in available_columns:
                resolved.add(avg_col)
            elif base in available_columns:
                resolved.add(base)
    return sorted(resolved)


def get_conn():
    url = os.environ.get("TIMESCALE_URL")
    if not url:
        raise SystemExit("TIMESCALE_URL is not set - see local-stack/docker-compose.yml")
    return psycopg2.connect(url)


def main() -> None:
    spark = build_spark("sync-timescale")
    conn = get_conn()
    total_rows = 0
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE sensor_readings")
        conn.commit()

        for farm in FARMS:
            path = silver_path(farm)
            if not delta_table_exists(spark, path):
                print(f"skipping farm={farm} - no silver table yet (run 02_silver_clean.py first)")
                continue

            silver_df = spark.read.format("delta").load(path)
            sensor_cols = resolve_relevant_columns(spark, farm, set(silver_df.columns))
            if not sensor_cols:
                print(f"skipping farm={farm} - no relevant sensors resolved")
                continue

            # Bounded slice: only rows inside an event's own `prediction` window,
            # same convention as eda/scripts/04_degradation_trends.py.
            bounded = silver_df.filter(F.col("train_test") == "prediction").select(
                "asset_id", "time_stamp", *sensor_cols
            )
            pdf = bounded.toPandas()
            if pdf.empty:
                continue

            records = []
            for row in pdf.itertuples(index=False):
                turbine_id = turbine_id_for(farm, row.asset_id)
                timestamp = row.time_stamp
                for col in sensor_cols:
                    value = getattr(row, col)
                    if value is None:
                        continue
                    sensor_name = col[:-4] if col.endswith("_avg") else col
                    records.append((turbine_id, timestamp, sensor_name, float(value), ""))

            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO sensor_readings (turbine_id, time, sensor, value, unit) VALUES %s",
                    records,
                    page_size=5000,
                )
            conn.commit()
            total_rows += len(records)
            print(f"farm={farm}: synced {len(records):,} readings ({len(sensor_cols)} sensors)")

        print(f"Sync complete: {total_rows:,} rows in sensor_readings")
    finally:
        conn.close()
        spark.stop()


if __name__ == "__main__":
    main()
