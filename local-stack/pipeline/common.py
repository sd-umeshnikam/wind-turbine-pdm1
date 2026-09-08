"""Shared Spark session + path constants for the local medallion pipeline.

Ports data-platform/notebooks/*'s logic to plain PySpark + Delta Lake OSS,
replacing Databricks-only pieces:
  - `dbutils.widgets`            -> argparse (see each script's `parse_args`)
  - 3-level Unity Catalog tables -> path-based Delta tables under DATA_LAKE_ROOT
  - Auto Loader (streaming)      -> plain batch `spark.read.csv(...)` - a one-shot
                                     local run doesn't need incremental/checkpoint
                                     machinery
  - s3://<env>-wtb-bronze/...    -> the real raw dataset folder, read directly
                                     (RAW_DATASET_ROOT below), no upload step needed

Everything downstream of this file (COMPONENT_KEYWORDS, FAULT_CATEGORY_KEYWORDS,
rolling-window feature logic) is unchanged from data-platform/notebooks/gold - ported,
not redesigned.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pyspark.sql import SparkSession

FARMS = ["A", "B", "C"]

# This file lives at local-stack/pipeline/common.py; the platform repo root is two
# levels up, and the raw dataset repo is a sibling of that (see README.md's layout).
PLATFORM_ROOT = Path(__file__).resolve().parents[2]
RAW_DATASET_ROOT = Path(
    os.environ.get(
        "RAW_DATASET_ROOT",
        str(PLATFORM_ROOT.parent / "wind-turbine-scada-data-for-early-fault-detection"),
    )
)
DATA_LAKE_ROOT = Path(os.environ.get("DATA_LAKE_ROOT", str(PLATFORM_ROOT / "local-stack" / "data-lake")))

FARM_DIR_NAME = {"A": "Wind Farm A", "B": "Wind Farm B", "C": "Wind Farm C"}


def raw_datasets_dir(farm: str) -> Path:
    return RAW_DATASET_ROOT / FARM_DIR_NAME[farm] / "datasets"


def raw_event_info_path(farm: str) -> Path:
    return RAW_DATASET_ROOT / FARM_DIR_NAME[farm] / "comma_event_info.csv"


def raw_feature_description_path(farm: str) -> Path:
    return RAW_DATASET_ROOT / FARM_DIR_NAME[farm] / "comma_feature_description.csv"


def bronze_path(farm: str) -> str:
    return str(DATA_LAKE_ROOT / "bronze" / f"farm_{farm.lower()}_raw")


def silver_path(farm: str) -> str:
    return str(DATA_LAKE_ROOT / "silver" / f"farm_{farm.lower()}")


def gold_path(name: str) -> str:
    return str(DATA_LAKE_ROOT / "gold" / name)


DELTA_MAVEN_COORDINATE = "io.delta:delta-spark_2.12:3.2.0"


def build_spark(app_name: str) -> SparkSession:
    """Delta-enabled local SparkSession, runnable as plain `python <script>.py` (no
    spark-submit needed) - `spark.jars.packages` tells Spark to fetch the Delta Lake
    JAR via Ivy on first run (cached under ~/.ivy2 after that), the same JAR a
    Databricks cluster provides built-in."""
    return (
        SparkSession.builder.appName(app_name)
        .master(os.environ.get("SPARK_MASTER", "local[*]"))
        .config("spark.jars.packages", DELTA_MAVEN_COORDINATE)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


def delta_table_exists(spark: SparkSession, path: str) -> bool:
    return Path(path).joinpath("_delta_log").exists()


# --- Turbine display-ID mapping ---------------------------------------------------
#
# The real dataset's `asset_id` values are arbitrary integers, not a stable 1..N
# sequence, and aren't published anywhere the frontend can read (fleet_summary.json
# only carries per-farm turbine *counts* - see frontend/dashboard-app/src/shared/
# turbines.ts's own comment on this). That file already synthesizes turbine ids as
# `${farmId}-${i+1}` for i in 0..count-1. So real backend data lines up with what the
# frontend already links to, this file persists the SAME rank-based mapping
# (farm + sorted-ascending rank of real asset_id -> "A-1", "A-2", ...), built once
# from real data in 02_silver_clean.py, and read by 04_sync_timescale.py,
# 05_train_models.py's forecast lookup, and local-stack/inference/serve.py.

TURBINE_ID_MAP_PATH = DATA_LAKE_ROOT / "turbine_id_map.json"


def load_turbine_id_map() -> dict:
    if not TURBINE_ID_MAP_PATH.exists():
        return {}
    with open(TURBINE_ID_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_turbine_id_map_for_farm(farm: str, asset_ids: list) -> None:
    """Sorts this farm's distinct real asset_id values ascending and assigns rank
    1..N, merging into the shared map (does not touch other farms' entries)."""
    id_map = load_turbine_id_map()
    sorted_ids = sorted({str(a) for a in asset_ids}, key=lambda x: (len(x), x))
    id_map[farm] = {asset_id: rank + 1 for rank, asset_id in enumerate(sorted_ids)}
    TURBINE_ID_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TURBINE_ID_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(id_map, f, indent=2)


def turbine_id_for(farm: str, asset_id) -> str:
    """Real (farm, asset_id) -> display id, e.g. ("A", 3) -> "A-1" if asset_id=3 is
    Farm A's lowest real asset_id. Falls back to the raw asset_id if the map hasn't
    been built yet for this farm (run 02_silver_clean.py first)."""
    id_map = load_turbine_id_map()
    rank = id_map.get(farm, {}).get(str(asset_id))
    return f"{farm}-{rank}" if rank is not None else f"{farm}-{asset_id}"


def real_asset_id_for(display_turbine_id: str) -> tuple[str, str] | None:
    """Display id -> (farm, real asset_id), the reverse of turbine_id_for. Returns
    None if the id doesn't parse as "<farm>-<rank>" or isn't in the map."""
    if "-" not in display_turbine_id:
        return None
    farm, rank_str = display_turbine_id.split("-", 1)
    if not rank_str.isdigit():
        return None
    rank = int(rank_str)
    id_map = load_turbine_id_map().get(farm, {})
    for real_id, r in id_map.items():
        if r == rank:
            return farm, real_id
    return None
