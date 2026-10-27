"""Ingest the raw CARE dataset into the curated lake and produce the catalog reports.

python -m wtpdm.ingest.pipeline [--farm A] [--skip-db]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from wtpdm.ingest.curate import curate_event_file, read_raw_event_file
from wtpdm.ingest.quality import FarmQuality
from wtpdm.ingest.source import (
    FARMS,
    EventSpec,
    SensorSpec,
    event_files,
    read_event_specs,
    read_sensor_specs,
    select_condition_sensors,
)
from wtpdm.logging import configure_logging, get_logger
from wtpdm.settings import get_settings
from wtpdm.taxonomy import Taxonomy, load_taxonomy

log = get_logger("ingest")


@dataclass
class CuratedEvent:
    farm: str
    event_id: int
    turbine_id: str
    asset_id: int
    label: str
    description: str | None
    component_code: str | None
    event_start: datetime
    event_end: datetime
    window_start: datetime
    window_end: datetime
    prediction_start: datetime | None
    rows: int
    path: str


@dataclass
class FarmResult:
    farm: str
    sensors: list[SensorSpec]
    conditions: dict[str, str]
    turbines: dict[int, str]  # asset_id -> turbine id
    events: list[CuratedEvent]
    quality: FarmQuality


def turbine_ids(files: dict[int, Path], farm: str) -> dict[int, str]:
    """Display ids "A-1".. assigned by ascending source asset_id (stable across runs)."""
    assets = set()
    for path in files.values():
        assets.add(int(pl.read_csv(path, columns=["asset_id"], n_rows=1)["asset_id"][0]))
    return {asset: f"{farm}-{i}" for i, asset in enumerate(sorted(assets), start=1)}


def ingest_farm(farm: str, raw_root: Path, lake_root: Path, taxonomy: Taxonomy) -> FarmResult:
    sensors = read_sensor_specs(raw_root, farm, taxonomy)
    conditions = select_condition_sensors(sensors, taxonomy)
    missing = [k for k in taxonomy.required_conditions if k not in conditions]
    if missing:
        raise ValueError(f"farm {farm}: required operating-condition sensors missing: {missing}")

    specs: dict[int, EventSpec] = {e.event_id: e for e in read_event_specs(raw_root, farm, taxonomy)}
    files = event_files(raw_root, farm)
    if set(specs) != set(files):
        only_info, only_files = sorted(set(specs) - set(files)), sorted(set(files) - set(specs))
        raise ValueError(
            f"farm {farm}: event_info and datasets disagree "
            f"(only in info: {only_info}, only files: {only_files})"
        )
    turbines = turbine_ids(files, farm)
    quality = FarmQuality(farm=farm)
    events: list[CuratedEvent] = []
    out_dir = lake_root / "curated" / f"farm={farm}"

    for event_id in sorted(files):
        spec = specs[event_id]
        raw = read_raw_event_file(files[event_id])
        asset_id = int(raw["asset_id"][0])
        result = curate_event_file(
            raw,
            farm=farm,
            event_id=event_id,
            turbine_id=turbines[asset_id],
            sensors=sensors,
            out_dir=out_dir,
        )
        for code, q in result.quality.items():
            quality.merge(code, q)
        events.append(
            CuratedEvent(
                farm=farm,
                event_id=event_id,
                turbine_id=turbines[asset_id],
                asset_id=asset_id,
                label=spec.label,
                description=spec.description,
                component_code=spec.component_code,
                event_start=spec.start,
                event_end=spec.end,
                window_start=result.window_start,
                window_end=result.window_end,
                prediction_start=result.prediction_start,
                rows=result.rows,
                path=str(result.path),
            )
        )
        log.info("curated", farm=farm, event_id=event_id, turbine=turbines[asset_id], rows=result.rows)
    return FarmResult(farm, sensors, conditions, turbines, events, quality)


def coverage_matrix(results: list[FarmResult], taxonomy: Taxonomy) -> dict:
    """farm -> component -> subcomponent -> number of monitored sensors."""
    matrix: dict = {}
    for r in results:
        farm_cov: dict = {}
        for comp in taxonomy.components:
            farm_cov[comp.code] = {
                sub.code: sum(1 for s in r.sensors if s.subcomponent_code == sub.code)
                for sub in comp.subcomponents
            }
        matrix[r.farm] = farm_cov
    return matrix


def write_reports(results: list[FarmResult], lake_root: Path, taxonomy: Taxonomy) -> None:
    """Per-farm artifacts, so re-ingesting one farm never clobbers another's catalog."""
    for r in results:
        out = lake_root / "catalog" / f"farm={r.farm}"
        out.mkdir(parents=True, exist_ok=True)
        pl.DataFrame([asdict(s) for s in r.sensors]).write_parquet(out / "sensors.parquet")
        pl.DataFrame([asdict(e) for e in r.events]).write_parquet(out / "events.parquet")
        (out / "turbines.json").write_text(json.dumps({str(a): t for a, t in r.turbines.items()}, indent=2))
        (out / "conditions.json").write_text(json.dumps(r.conditions, indent=2))
        (out / "coverage.json").write_text(json.dumps(coverage_matrix([r], taxonomy)[r.farm], indent=2))
        (out / "data_quality.json").write_text(
            json.dumps({code: q.as_dict() for code, q in sorted(r.quality.columns.items())}, indent=2)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--farm", choices=FARMS, action="append")
    parser.add_argument("--skip-db", action="store_true", help="only write the lake and reports")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    taxonomy = load_taxonomy()
    farms = args.farm or list(FARMS)
    results = [ingest_farm(f, settings.raw_data_root, settings.lake_root, taxonomy) for f in farms]
    write_reports(results, settings.lake_root, taxonomy)
    if not args.skip_db:
        from wtpdm.ingest.load_db import load_catalog

        load_catalog(settings.lake_root, taxonomy, farms)
    log.info(
        "ingest complete",
        farms=farms,
        events=sum(len(r.events) for r in results),
        rows=sum(e.rows for r in results for e in r.events),
    )


if __name__ == "__main__":
    main()
