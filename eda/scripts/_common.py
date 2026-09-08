"""Shared paths/helpers for the wind-turbine PdM EDA scripts.

All scripts are designed to be run standalone, e.g.:
    python eda/scripts/01_data_quality.py
from the `wind-turbine-pdm-platform` repo root (or anywhere - paths are
resolved relative to this file, not the current working directory).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# --- Path resolution -------------------------------------------------------
# repo root = wind-turbine-pdm-platform/
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[2]
EDA_DIR = REPO_ROOT / "eda"
OUTPUTS_DIR = EDA_DIR / "outputs"
CHARTS_DIR = OUTPUTS_DIR / "charts"

# Raw data lives in a sibling directory next to the platform scaffold, per the
# task spec. It is READ-ONLY - never write into it.
RAW_DATA_ROOT = REPO_ROOT.parent / "wind-turbine-scada-data-for-early-fault-detection"

FARMS = ["A", "B", "C"]

FARM_META = {
    "A": {
        "label": "Wind Farm A",
        "dir": RAW_DATA_ROOT / "Wind Farm A",
        "location": "Onshore Portugal (EDP)",
        "known_faults": ["transformer", "hydraulic group", "gearbox"],
    },
    "B": {
        "label": "Wind Farm B",
        "dir": RAW_DATA_ROOT / "Wind Farm B",
        "location": "Offshore Germany (anonymized sensor names)",
        "known_faults": [],
    },
    "C": {
        "label": "Wind Farm C",
        "dir": RAW_DATA_ROOT / "Wind Farm C",
        "location": "Offshore Germany (3-axis independent pitch, hydraulics, water cooling)",
        "known_faults": ["pitch system", "hydraulics", "PLC/communications", "gearbox"],
    },
}

STATUS_TYPE_LABELS = {
    0: "normal operation",
    1: "derated",
    2: "idling (normal)",
    3: "service",
    4: "downtime (fault)",
    5: "other",
}


def farm_dir(farm: str) -> Path:
    return FARM_META[farm]["dir"]


def event_info_path(farm: str) -> Path:
    return farm_dir(farm) / "comma_event_info.csv"


def feature_description_path(farm: str) -> Path:
    return farm_dir(farm) / "comma_feature_description.csv"


def datasets_dir(farm: str) -> Path:
    return farm_dir(farm) / "datasets"


def dataset_files(farm: str) -> list[Path]:
    d = datasets_dir(farm)
    return sorted(d.glob("comma_*.csv"), key=lambda p: _natural_key(p.name))


def _natural_key(name: str):
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else name


def event_id_from_filename(path: Path) -> int:
    m = re.search(r"comma_(\d+)\.csv$", path.name)
    if not m:
        raise ValueError(f"Cannot parse event id from filename: {path.name}")
    return int(m.group(1))


def ensure_output_dirs() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)


# A small, print-friendly divider for human-readable console summaries.
def hr(title: str = "") -> None:
    line = "=" * 78
    if title:
        print(f"\n{line}\n{title}\n{line}")
    else:
        print(line)
