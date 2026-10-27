"""Load the asset catalog and CARE events from the curated lake into PostgreSQL.

Reads the per-farm catalog artifacts written by the ingest pipeline (the lake is the
source of truth), so the database can be rebuilt without re-reading the raw dataset:

    python -m wtpdm.ingest.load_db [--farm A]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from wtpdm import catalog
from wtpdm.db.models import (
    AuditLog,
    Component,
    Event,
    EventLabel,
    Farm,
    Sensor,
    SensorRole,
    Subcomponent,
    Turbine,
)
from wtpdm.db.session import session_scope
from wtpdm.ingest.source import FARMS
from wtpdm.logging import configure_logging, get_logger
from wtpdm.settings import get_settings
from wtpdm.taxonomy import Taxonomy, load_taxonomy

log = get_logger("load_db")

FARM_NAMES = {
    "A": ("Wind Farm A", "Onshore, Portugal (EDP open data)"),
    "B": ("Wind Farm B", "Offshore, Germany"),
    "C": ("Wind Farm C", "Offshore, Germany"),
}


def _upsert(session, model, rows: list[dict], key: list[str]) -> None:
    if not rows:
        return
    stmt = insert(model).values(rows)
    update_cols = {c: stmt.excluded[c] for c in rows[0] if c not in key}
    session.execute(stmt.on_conflict_do_update(index_elements=key, set_=update_cols))


def load_catalog(lake_root: Path, taxonomy: Taxonomy, farms: list[str]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    with session_scope() as s:
        _upsert(s, Component, [{"code": c.code, "name": c.name} for c in taxonomy.components], ["code"])
        _upsert(
            s,
            Subcomponent,
            [
                {"code": sc.code, "component_code": sc.component_code, "name": sc.name}
                for sc in taxonomy.subcomponents
            ],
            ["code"],
        )
        for farm in farms:
            sensors = catalog.sensors(lake_root, farm)
            events = catalog.events(lake_root, farm)
            asset_map = catalog.turbines(lake_root, farm)
            name, desc = FARM_NAMES.get(farm, (f"Wind Farm {farm}", None))
            _upsert(s, Farm, [{"id": farm, "name": name, "description": desc}], ["id"])
            _upsert(
                s,
                Turbine,
                [
                    {"id": tid, "farm_id": farm, "asset_id": asset, "name": f"Turbine {tid}"}
                    for asset, tid in asset_map.items()
                ],
                ["id"],
            )
            # Sensors and events are owned by ingest: replace them for this farm.
            s.execute(delete(Event).where(Event.farm_id == farm))
            s.execute(delete(Sensor).where(Sensor.farm_id == farm))
            s.add_all(
                Sensor(
                    farm_id=farm,
                    code=r["code"],
                    description=r["description"],
                    unit=r["unit"],
                    statistics=list(r["statistics"]),
                    is_angle=r["is_angle"],
                    is_counter=r["is_counter"],
                    role=SensorRole(r["role"]),
                    subcomponent_code=r["subcomponent_code"],
                    condition_kind=r["condition_kind"],
                )
                for r in sensors.iter_rows(named=True)
            )
            s.add_all(
                Event(
                    farm_id=farm,
                    source_event_id=r["event_id"],
                    turbine_id=r["turbine_id"],
                    label=EventLabel(r["label"]),
                    description=r["description"],
                    category=r["component_code"],
                    component_code=r["component_code"],
                    window_start=r["window_start"],
                    event_start=r["event_start"],
                    event_end=r["event_end"],
                    prediction_start=r["prediction_start"] or r["event_start"],
                    n_rows=r["rows"],
                )
                for r in events.iter_rows(named=True)
            )
            summary[farm] = {"turbines": len(asset_map), "sensors": sensors.height, "events": events.height}
            s.add(
                AuditLog(
                    actor="system:ingest",
                    action="catalog.load",
                    entity="farm",
                    entity_id=farm,
                    details=summary[farm],
                )
            )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--farm", choices=FARMS, action="append")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    farms = args.farm or catalog.available_farms(settings.lake_root)
    log.info("catalog loaded", farms=load_catalog(settings.lake_root, load_taxonomy(), farms))


if __name__ == "__main__":
    main()
