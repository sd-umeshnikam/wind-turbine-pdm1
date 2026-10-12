"""05 - Fleet summary JSON for the React dashboard fixture.

Produces outputs/fleet_summary.json, a compact, machine-readable digest of
what scripts 01-04 actually computed:
  - per farm: distinct turbine count (by asset_id, NOT file/event count -
    see note below), event counts, anomaly count by category
  - fleet-wide headline KPIs: total anomaly events, most common fault
    category (both the literal top bucket and the top *named* category
    excluding "Other/unclassified"), and - if reliably computable from the
    real status_type_id sequences - the warning time between a fault's
    logged start and the turbine's first downtime (see method below).

IMPORTANT real-data finding baked into this script: the number of dataset
files per farm (22 / 15 / 58) is NOT the turbine count. Each file is one
event WINDOW for one turbine, and turbines recur across multiple event
files. The true fleet size (distinct asset_id) is smaller: 5 turbines for
Farm A, 9 for Farm B, 22 for Farm C.

Warning-time method (documented, not fabricated): for each anomaly event's
file, warning time = (first downtime (4) at or after the event's logged start
row, event_start_id) - (event start). Both timestamps come from the same
turbine's file, so the per-turbine date anonymization doesn't affect it. Events
whose file records no downtime after the fault start are excluded, not imputed.
The median and interquartile range are reported because a few multi-week cases
make the mean unrepresentative.

This replaced an earlier derated/idle-onset -> downtime metric that only Farm B's
status codes could support (2 of 44 events): Farms A and C never emit
status_type_id 1 (derated) or 2 (idling).

Run:
    python eda/scripts/05_fleet_summary.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    FARMS,
    FARM_META,
    OUTPUTS_DIR,
    dataset_files,
    ensure_output_dirs,
    hr,
)

DOWNTIME = 4


def distinct_turbine_count(farm: str) -> int:
    ids = set()
    for fp in dataset_files(farm):
        df = pd.read_csv(fp, engine="pyarrow", usecols=["asset_id"])
        ids.update(df["asset_id"].unique().tolist())
    return len(ids)


def fault_to_downtime_hours(farm: str, event_id: int, event_start_id: int) -> float | None:
    fp = next((f for f in dataset_files(farm) if f.name == f"comma_{event_id}.csv"), None)
    if fp is None:
        return None
    df = pd.read_csv(fp, engine="pyarrow", usecols=["id", "time_stamp", "status_type_id"])
    after_start = df[df["id"] >= event_start_id].sort_values("id")
    if after_start.empty:
        return None
    downtime = after_start[after_start["status_type_id"] == DOWNTIME]
    if downtime.empty:
        return None
    hours = (downtime["time_stamp"].iloc[0] - after_start["time_stamp"].iloc[0]).total_seconds() / 3600.0
    return round(hours, 1)


def warning_time_stats(hours: list[float]) -> dict:
    if not hours:
        return {"median_hours": None, "p25_hours": None, "p75_hours": None}
    s = pd.Series(hours)
    return {
        "median_hours": round(float(s.median()), 1),
        "p25_hours": round(float(s.quantile(0.25)), 1),
        "p75_hours": round(float(s.quantile(0.75)), 1),
    }


def main() -> None:
    ensure_output_dirs()
    events = pd.read_csv(OUTPUTS_DIR / "events_categorized.csv", parse_dates=["event_start", "event_end"])

    per_farm = {}
    warning_all = []
    for farm in FARMS:
        hr(f"Fleet summary - {FARM_META[farm]['label']}")
        n_turbines = distinct_turbine_count(farm)
        farm_events = events[events["farm"] == farm]
        n_anomaly = int((farm_events["event_label"] == "anomaly").sum())
        n_normal = int((farm_events["event_label"] == "normal").sum())
        cat_counts = (
            farm_events[farm_events["event_label"] == "anomaly"]["category"]
            .value_counts()
            .to_dict()
        )

        warning_farm = []
        for ev in farm_events[farm_events["event_label"] == "anomaly"].itertuples():
            h = fault_to_downtime_hours(farm, int(ev.event_id), int(ev.event_start_id))
            if h is not None:
                warning_farm.append(h)
        warning_all.extend(warning_farm)
        farm_stats = warning_time_stats(warning_farm)

        print(f"  Distinct turbines (asset_id): {n_turbines}  "
              f"(vs {len(dataset_files(farm))} event files - each turbine appears in multiple event windows)")
        print(f"  Events: {n_anomaly} anomaly / {n_normal} normal")
        print(f"  Anomaly by category: {cat_counts}")
        print(f"  Fault-start -> downtime computable for {len(warning_farm)}/{n_anomaly} anomaly events"
              + (f", median {farm_stats['median_hours']}h" if warning_farm else ""))

        per_farm[farm] = {
            "label": FARM_META[farm]["label"],
            "n_turbines": n_turbines,
            "n_event_files": len(dataset_files(farm)),
            "n_anomaly_events": n_anomaly,
            "n_normal_events": n_normal,
            "anomaly_count_by_category": cat_counts,
            "fault_to_downtime_hours": {
                "n_events_computable": len(warning_farm),
                "n_anomaly_events_total": n_anomaly,
                **farm_stats,
            },
        }

    overall_cat_counts = (
        events[events["event_label"] == "anomaly"]["category"].value_counts().to_dict()
    )
    named_only = {k: v for k, v in overall_cat_counts.items() if k != "Other / unclassified"}
    most_common_overall = max(overall_cat_counts, key=overall_cat_counts.get) if overall_cat_counts else None
    most_common_named = max(named_only, key=named_only.get) if named_only else None

    fleet_summary = {
        "farms": per_farm,
        "fleet_totals": {
            "total_turbines": sum(v["n_turbines"] for v in per_farm.values()),
            "total_event_files": sum(v["n_event_files"] for v in per_farm.values()),
            "total_anomaly_events": int((events["event_label"] == "anomaly").sum()),
            "total_normal_events": int((events["event_label"] == "normal").sum()),
            "anomaly_count_by_category": overall_cat_counts,
        },
        "headline_kpis": {
            "total_anomaly_events": int((events["event_label"] == "anomaly").sum()),
            "most_common_fault_category_including_other": most_common_overall,
            "most_common_named_fault_category": most_common_named,
            "fault_to_downtime_hours": warning_time_stats(warning_all),
            "fault_to_downtime_coverage": f"{len(warning_all)}/{int((events['event_label']=='anomaly').sum())} anomaly events",
        },
        "data_quality_note": (
            "Turbine counts are distinct asset_id values per farm, not dataset file counts - "
            "each physical turbine appears across multiple event-window files."
        ),
    }

    out_path = OUTPUTS_DIR / "fleet_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fleet_summary, f, indent=2)
    print(f"\nSaved {out_path}")

    hr("FLEET SUMMARY - HEADLINE KPIs")
    for k, v in fleet_summary["headline_kpis"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
