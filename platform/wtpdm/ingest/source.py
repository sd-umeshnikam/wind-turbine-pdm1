"""Readers for the raw CARE dataset layout:

    Wind Farm <X>/comma_feature_description.csv   sensor catalog (UTF-8)
    Wind Farm <X>/comma_event_info.csv            labelled event windows (no turbine column)
    Wind Farm <X>/datasets/comma_<event_id>.csv   one turbine's history for that event

The event file name is the ONLY link between an event and its turbine.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from wtpdm.taxonomy import Taxonomy

FARMS = ("A", "B", "C")
EVENT_FILE_RE = re.compile(r"^comma_(\d+)\.csv$")
STATISTIC_SUFFIX = {"average": "avg", "maximum": "max", "minimum": "min", "std_dev": "std"}


def farm_dir(raw_root: Path, farm: str) -> Path:
    return raw_root / f"Wind Farm {farm}"


@dataclass(frozen=True)
class SensorSpec:
    farm: str
    code: str  # "sensor_11", "wind_speed_3", "power_58" ...
    description: str
    unit: str | None
    statistics: tuple[str, ...]  # suffixes present in the data: ("avg", "std", ...)
    is_angle: bool
    is_counter: bool
    role: str
    subcomponent_code: str | None
    condition_kind: str | None

    @property
    def avg_column(self) -> str:
        return f"{self.code}_avg"


@dataclass(frozen=True)
class EventSpec:
    farm: str
    event_id: int
    label: str  # anomaly | normal
    start: datetime
    end: datetime
    description: str | None
    component_code: str | None


def _clean_unit(unit: str) -> str | None:
    unit = unit.strip()
    if not unit:
        return None
    # The source files are UTF-8 but lost the degree sign upstream: it is stored as the
    # replacement character U+FFFD ("�C", and a bare "�" for angles).
    return unit.replace("�", "°")


def read_sensor_specs(raw_root: Path, farm: str, taxonomy: Taxonomy) -> list[SensorSpec]:
    path = farm_dir(raw_root, farm) / "comma_feature_description.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    specs = []
    for r in rows:
        stats = tuple(
            STATISTIC_SUFFIX[s.strip()]
            for s in r["statistics_type"].split(",")
            if s.strip() in STATISTIC_SUFFIX
        )
        desc = " ".join(r["description"].split())
        cls = taxonomy.classify_sensor(desc)
        specs.append(
            SensorSpec(
                farm=farm,
                code=r["sensor_name"].strip(),
                description=desc,
                unit=_clean_unit(r["unit"]),
                statistics=stats or ("avg",),
                is_angle=r["is_angle"].strip().lower() == "true",
                is_counter=r["is_counter"].strip().lower() == "true",
                role=cls.role,
                subcomponent_code=cls.subcomponent_code,
                condition_kind=cls.condition_kind,
            )
        )
    return specs


def select_condition_sensors(specs: list[SensorSpec], taxonomy: Taxonomy) -> dict[str, str]:
    """kind -> sensor code. Picks the sensor matching the EARLIEST pattern of each kind
    (patterns are listed in preference order), not the first sensor in file order."""
    chosen: dict[str, str] = {}
    for kind, patterns in taxonomy.conditions.items():
        for pattern in patterns:
            match = next(
                (s for s in specs if s.condition_kind == kind and pattern.search(s.description.lower())),
                None,
            )
            if match:
                chosen[kind] = match.code
                break
    return chosen


def _parse_ts(value: str) -> datetime:
    # Source timestamps are naive and anonymised per turbine; store them as UTC.
    return datetime.fromisoformat(value.strip()).replace(tzinfo=UTC)


def read_event_specs(raw_root: Path, farm: str, taxonomy: Taxonomy) -> list[EventSpec]:
    path = farm_dir(raw_root, farm) / "comma_event_info.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    events = []
    for r in rows:
        label = r["event_label"].strip().lower()
        desc = (r.get("event_description") or "").strip() or None
        events.append(
            EventSpec(
                farm=farm,
                event_id=int(r["event_id"]),
                label=label,
                start=_parse_ts(r["event_start"]),
                end=_parse_ts(r["event_end"]),
                description=desc,
                component_code=taxonomy.classify_event(desc) if label == "anomaly" else None,
            )
        )
    return events


def event_files(raw_root: Path, farm: str) -> dict[int, Path]:
    out = {}
    for p in (farm_dir(raw_root, farm) / "datasets").iterdir():
        m = EVENT_FILE_RE.match(p.name)
        if m:
            out[int(m.group(1))] = p
    return out
