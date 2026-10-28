"""Read access to the curated lake's per-farm catalog artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

from wtpdm.ingest.source import FARMS


def catalog_dir(lake_root: Path, farm: str) -> Path:
    return lake_root / "catalog" / f"farm={farm}"


def data_version(lake_root: Path, farm: str) -> str:
    """Fingerprint of the farm catalog: changes whenever the lake is re-ingested differently."""
    h = hashlib.sha256()
    for name in ("events.parquet", "sensors.parquet", "conditions.json"):
        h.update((catalog_dir(lake_root, farm) / name).read_bytes())
    return h.hexdigest()[:12]


def available_farms(lake_root: Path) -> list[str]:
    return [f for f in FARMS if (catalog_dir(lake_root, f) / "sensors.parquet").exists()]


def sensors(lake_root: Path, farm: str) -> pl.DataFrame:
    return pl.read_parquet(catalog_dir(lake_root, farm) / "sensors.parquet")


def events(lake_root: Path, farm: str) -> pl.DataFrame:
    return pl.read_parquet(catalog_dir(lake_root, farm) / "events.parquet")


def turbines(lake_root: Path, farm: str) -> dict[int, str]:
    raw = json.loads((catalog_dir(lake_root, farm) / "turbines.json").read_text())
    return {int(a): t for a, t in raw.items()}


def conditions(lake_root: Path, farm: str) -> dict[str, str]:
    return json.loads((catalog_dir(lake_root, farm) / "conditions.json").read_text())


def data_quality(lake_root: Path, farm: str) -> dict[str, dict]:
    return json.loads((catalog_dir(lake_root, farm) / "data_quality.json").read_text())


def coverage(lake_root: Path, farm: str) -> dict[str, dict[str, int]]:
    return json.loads((catalog_dir(lake_root, farm) / "coverage.json").read_text())


def curated_event_path(lake_root: Path, farm: str, event_id: int) -> Path:
    return lake_root / "curated" / f"farm={farm}" / f"event={event_id}.parquet"
