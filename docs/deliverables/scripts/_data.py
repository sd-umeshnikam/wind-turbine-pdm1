"""Loads real, already-computed EDA outputs so the Word deliverables cite numbers
that trace back to eda/outputs/ rather than being retyped/guessed by hand."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
EDA_OUTPUTS = REPO_ROOT / "eda" / "outputs"


def fleet_summary() -> dict:
    with open(EDA_OUTPUTS / "fleet_summary.json", encoding="utf-8") as f:
        return json.load(f)


def data_quality() -> dict:
    with open(EDA_OUTPUTS / "data_quality.json", encoding="utf-8") as f:
        return json.load(f)


def events_categorized() -> pd.DataFrame:
    return pd.read_csv(
        EDA_OUTPUTS / "events_categorized.csv",
        parse_dates=["event_start", "event_end"],
    )


def event_row(df: pd.DataFrame, farm: str, event_id: int) -> pd.Series:
    return df[(df["farm"] == farm) & (df["event_id"] == event_id)].iloc[0]


def total_rows(dq: dict) -> int:
    return sum(dq[f]["n_rows_total"] for f in ("A", "B", "C"))


def total_turbines(fs: dict) -> int:
    return sum(fs["farms"][f]["n_turbines"] for f in ("A", "B", "C"))
