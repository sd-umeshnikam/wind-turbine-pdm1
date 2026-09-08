"""Bronze: raw SCADA ingest (local port of data-platform/notebooks/bronze/01_ingest_raw.py).

Batch equivalent of Auto Loader: reads every `datasets/*.csv` file for one farm
directly from the raw dataset folder in one pass (confirmed schema-consistent
across files per farm - see eda/EDA_REPORT.md §1) and writes an append-only Delta
table. No incremental/checkpoint tracking - re-running overwrites, since a
one-shot local pipeline doesn't need Auto Loader's incremental-landing semantics.

Usage: python 01_bronze_ingest.py --farm A
"""
from __future__ import annotations

import argparse

from pyspark.sql import functions as F

from common import build_spark, bronze_path, raw_datasets_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--farm", required=True, choices=["A", "B", "C"])
    args = parser.parse_args()
    farm = args.farm

    spark = build_spark(f"bronze-ingest-{farm}")
    try:
        source_path = str(raw_datasets_dir(farm) / "*.csv")
        raw_df = (
            spark.read.option("header", "true")
            .option("inferSchema", "true")
            .csv(source_path)
            .withColumn("_source_file", F.input_file_name())
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("farm", F.lit(farm))
        )

        out_path = bronze_path(farm)
        raw_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").partitionBy(
            "farm"
        ).save(out_path)

        row_count = raw_df.count()
        print(f"Bronze ingest complete for farm={farm}: {row_count:,} rows -> {out_path}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
