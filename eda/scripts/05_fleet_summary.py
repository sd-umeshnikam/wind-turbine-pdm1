"""05 - Fleet summary JSON for the React dashboard fixture.

Produces outputs/fleet_summary.json, a compact, machine-readable digest of
what scripts 01-04 actually computed:
  - per farm: distinct turbine count (by asset_id, NOT file/event count -
    see note below), event counts, anomaly count by category
  - fleet-wide headline KPIs: total anomaly events, most common fault
    category (both the literal top bucket and the top *named* category
    excluding "Other/unclassified"), and - if reliably computable from the
    real status_type_id sequences - the average lead time between a
    derated/idling status onset and the following downtime status onset
    across anomaly events.

IMPORTANT real-data finding baked into this script: the number of dataset
files per farm (22 / 15 / 58) is NOT the turbine count. Each file is one
event WINDOW for one turbine, and turbines recur across multiple event
files. The true fleet size (distinct asset_id) is smaller: 5 turbines for
Farm A, 9 for Farm B, 22 for Farm C.

Lead-time method (documented, not fabricated): for each anomaly event's
file, take the status_type_id time series, find the first downtime (4)
timestamp, and walk backward through the immediately preceding contiguous
run of derated (1) / idling-normal (2) status. If that run exists, lead
time = (first downtime time) - (start of that run). If status jumps
straight from normal/other to downtime with no derated/idling lead-in in
that file, the event contributes no lead-time sample (excluded, not
imputed as zero).

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

DERATED_IDLE = {1, 2}
DOWNTIME = 4


def distinct_turbine_count(farm: str) -> int:
    ids = set()
    for fp in dataset_files(farm):
        df = pd.read_csv(fp, engine="pyarrow", usecols=["asset_id"])
        ids.update(df["asset_id"].unique().tolist())
    return len(ids)


def lead_time_hours_for_event(farm: str, event_id: int) -> float | None:
    fp = None
    for f in dataset_files(farm):
        if f.name == f"comma_{event_id}.csv":
            fp = f
            break
    if fp is None:
        return None
    df = pd.read_csv(fp, engine="pyarrow", usecols=["time_stamp", "status_type_id"])
    df = df.sort_values("time_stamp").reset_index(drop=True)
    downtime_idx = df.index[df["status_type_id"] == DOWNTIME]
    if len(downtime_idx) == 0:
        return None
    first_down = downtime_idx[0]
    if first_down == 0:
        return None
    if df.loc[first_down - 1, "status_type_id"] not in DERATED_IDLE:
        return None
    i = first_down - 1
    while i > 0 and df.loc[i - 1, "status_type_id"] in DERATED_IDLE:
        i -= 1
    onset_time = df.loc[i, "time_stamp"]
    down_time = df.loc[first_down, "time_stamp"]
    hours = (down_time - onset_time).total_seconds() / 3600.0
    return hours if hours > 0 else None


def main() -> None:
    ensure_output_dirs()
    events = pd.read_csv(OUTPUTS_DIR / "events_categorized.csv", parse_dates=["event_start", "event_end"])

    per_farm = {}
    lead_times_all = []
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

        lead_times_farm = []
        for eid in farm_events[farm_events["event_label"] == "anomaly"]["event_id"]:
            lt = lead_time_hours_for_event(farm, int(eid))
            if lt is not None:
                lead_times_farm.append(lt)
        lead_times_all.extend(lead_times_farm)

        print(f"  Distinct turbines (asset_id): {n_turbines}  "
              f"(vs {len(dataset_files(farm))} event files - each turbine appears in multiple event windows)")
        print(f"  Events: {n_anomaly} anomaly / {n_normal} normal")
        print(f"  Anomaly by category: {cat_counts}")
        print(f"  Lead-time computable for {len(lead_times_farm)}/{n_anomaly} anomaly events"
              + (f", avg {sum(lead_times_farm)/len(lead_times_farm):.1f}h" if lead_times_farm else ""))

        per_farm[farm] = {
            "label": FARM_META[farm]["label"],
            "n_turbines": n_turbines,
            "n_event_files": len(dataset_files(farm)),
            "n_anomaly_events": n_anomaly,
            "n_normal_events": n_normal,
            "anomaly_count_by_category": cat_counts,
            "lead_time_hours": {
                "n_events_computable": len(lead_times_farm),
                "n_anomaly_events_total": n_anomaly,
                "avg_hours": round(sum(lead_times_farm) / len(lead_times_farm), 2) if lead_times_farm else None,
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
            "avg_derated_or_idle_to_downtime_lead_time_hours": (
                round(sum(lead_times_all) / len(lead_times_all), 2) if lead_times_all else None
            ),
            "lead_time_sample_coverage": f"{len(lead_times_all)}/{int((events['event_label']=='anomaly').sum())} anomaly events",
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
