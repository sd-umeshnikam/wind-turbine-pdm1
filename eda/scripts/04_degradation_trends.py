"""04 - Degradation-trend charts: the key PdM evidence plots.

For each farm, for each of the six target component categories (Gearbox,
Hydraulics, Pitch/blade angle, Generator, Transformer, Rotor brake) where a
matching REAL anomaly event exists, this plots the relevant representative
sensor(s) over the dataset's own `train_test == 'prediction'` window (the
lead-up-to-and-including-the-fault window the CARE/EDP-style benchmark
itself designates for early fault detection), relative to that event's
`event_start`, and overlays a normal-event baseline from the same farm on
the same relative time axis for comparison.

Selection rule (documented, not cherry-picked by hand):
  - candidate anomaly events = all anomaly events in that farm already
    tagged with the category by script 02 (outputs/events_categorized.csv)
  - among candidates, pick the one with the most 'prediction'-window rows
    (longest lead-up context available to visualize)
  - baseline = the same farm's normal event with the most 'prediction'-
    window rows
  - sensors = the top-ranked representative sensors for that category from
    script 03's keyword match against comma_feature_description.csv

Farm B has zero anomaly events falling into Gearbox/Hydraulics/Pitch under
the given keyword taxonomy (its real anomalies are "high temperature" and
bearing-damage descriptions - see script 02 / EDA_REPORT) so it is skipped
here; that omission is itself a reported finding, not a bug.

Run:
    python eda/scripts/04_degradation_trends.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    FARM_META,
    CHARTS_DIR,
    OUTPUTS_DIR,
    datasets_dir,
    ensure_output_dirs,
    hr,
)
from importlib import import_module  # noqa: E402

sensor_profiling = import_module("03_sensor_profiling")

# (event-category label as produced by script 02, filename slug, script03 key)
TARGET_CATEGORIES = [
    ("Gearbox", "gearbox", "Gearbox"),
    ("Hydraulics", "hydraulics", "Hydraulics"),
    ("Pitch / blade angle", "pitch", "Pitch"),
    ("Generator", "generator", "Generator"),
    ("Transformer", "transformer", "Transformer"),
    ("Rotor brake", "rotor_brake", "Rotor brake"),
    ("Bearing", "vibration", "Vibration"),
]
MAX_SENSORS_PER_CHART = 2


def event_file(farm: str, event_id: int) -> Path:
    return datasets_dir(farm) / f"comma_{event_id}.csv"


def prediction_row_count(farm: str, event_id: int) -> int:
    fp = event_file(farm, event_id)
    if not fp.exists():
        return 0
    df = pd.read_csv(fp, engine="pyarrow", usecols=["train_test"])
    return int((df["train_test"] == "prediction").sum())


def load_prediction_window(farm: str, event_id: int, sensor_cols: list[str]) -> pd.DataFrame:
    fp = event_file(farm, event_id)
    df = pd.read_csv(fp, engine="pyarrow", usecols=["time_stamp", "train_test"] + sensor_cols)
    return df[df["train_test"] == "prediction"].copy()


def pick_best(events: pd.DataFrame, farm: str) -> tuple[int | None, int]:
    """Return (event_id, prediction_row_count) with the most prediction rows, or (None, 0)."""
    best_id, best_n = None, -1
    for eid in events["event_id"]:
        n = prediction_row_count(farm, int(eid))
        if n > best_n:
            best_id, best_n = int(eid), n
    return best_id, max(best_n, 0)


def make_chart(farm: str, slug: str, category_label: str,
                anomaly_row: pd.Series, baseline_row: pd.Series | None,
                sensors: list[dict]) -> Path | None:
    sensor_cols = [s["column"] for s in sensors[:MAX_SENSORS_PER_CHART]]
    if not sensor_cols:
        return None

    a_event_start = pd.Timestamp(anomaly_row["event_start"])
    a_event_end = pd.Timestamp(anomaly_row["event_end"])
    a_df = load_prediction_window(farm, int(anomaly_row["event_id"]), sensor_cols)
    if a_df.empty:
        print(f"  [warn] no 'prediction' rows for anomaly event {anomaly_row['event_id']} - skipping chart")
        return None
    a_df["rel_days"] = (a_df["time_stamp"] - a_event_start).dt.total_seconds() / 86400.0

    b_df = None
    if baseline_row is not None:
        b_event_start = pd.Timestamp(baseline_row["event_start"])
        b_df = load_prediction_window(farm, int(baseline_row["event_id"]), sensor_cols)
        if not b_df.empty:
            b_df["rel_days"] = (b_df["time_stamp"] - b_event_start).dt.total_seconds() / 86400.0
        else:
            b_df = None

    n = len(sensor_cols)
    fig, axes = plt.subplots(n, 1, figsize=(11, 4.2 * n), squeeze=False)
    axes = axes[:, 0]
    fault_span_days = (a_event_end - a_event_start).total_seconds() / 86400.0

    for ax, s, col in zip(axes, sensors[:MAX_SENSORS_PER_CHART], sensor_cols):
        ax.plot(a_df["rel_days"], a_df[col], color="#C44E52", linewidth=1.1,
                label=f"Anomaly event {int(anomaly_row['event_id'])}")
        if b_df is not None:
            ax.plot(b_df["rel_days"], b_df[col], color="#55A868", linewidth=1.0, alpha=0.85,
                     linestyle="--", label=f"Normal baseline (event {int(baseline_row['event_id'])})")
        ax.axvline(0, color="black", linestyle=":", linewidth=1.3, label="event_start")
        if fault_span_days > 0:
            ax.axvspan(0, fault_span_days, color="red", alpha=0.08, label="event_start -> event_end")
        ax.set_title(f"{s['description']}  ({col})", fontsize=10)
        ax.set_xlabel("Days relative to event_start (dataset's own 'prediction' window)")
        ax.set_ylabel(col)
        ax.legend(fontsize=8, loc="best")

    desc = str(anomaly_row["event_description"])[:110]
    fig.suptitle(
        f"{FARM_META[farm]['label']} - {category_label} degradation trend\n"
        f"event_id={int(anomaly_row['event_id'])}: \"{desc}\"",
        fontsize=12,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = CHARTS_DIR / f"degradation_trend_{farm}_{slug}_{int(anomaly_row['event_id'])}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> None:
    ensure_output_dirs()
    events = pd.read_csv(
        OUTPUTS_DIR / "events_categorized.csv",
        parse_dates=["event_start", "event_end"],
    )

    report_lines = []
    for farm in ["A", "B", "C"]:
        hr(f"Degradation trends - {FARM_META[farm]['label']}")
        farm_events = events[events["farm"] == farm]
        normal_events = farm_events[farm_events["event_label"] == "normal"]
        baseline_id, baseline_n = pick_best(normal_events, farm) if len(normal_events) else (None, 0)
        baseline_row = (
            farm_events[farm_events["event_id"] == baseline_id].iloc[0]
            if baseline_id is not None else None
        )
        if baseline_row is not None:
            print(f"  Baseline normal event: {baseline_id} ({baseline_n} prediction rows)")
        else:
            print("  No normal event available for baseline")

        selected_sensors = sensor_profiling.select_representative_sensors(farm)

        for category_label, slug, script03_key in TARGET_CATEGORIES:
            candidates = farm_events[
                (farm_events["category"] == category_label) & (farm_events["event_label"] == "anomaly")
            ]
            if candidates.empty:
                msg = f"  [{category_label}] SKIPPED - no anomaly event in this farm falls into this category"
                print(msg)
                report_lines.append((farm, category_label, None, msg.strip()))
                continue

            best_id, best_n = pick_best(candidates, farm)
            if best_id is None or best_n == 0:
                msg = f"  [{category_label}] SKIPPED - candidate event(s) have no 'prediction' rows"
                print(msg)
                report_lines.append((farm, category_label, None, msg.strip()))
                continue

            anomaly_row = candidates[candidates["event_id"] == best_id].iloc[0]
            sensors = selected_sensors.get(script03_key, [])
            if not sensors:
                msg = f"  [{category_label}] SKIPPED - no representative sensor found for this farm/category"
                print(msg)
                report_lines.append((farm, category_label, best_id, msg.strip()))
                continue

            out = make_chart(farm, slug, category_label, anomaly_row, baseline_row, sensors)
            if out:
                print(f"  [{category_label}] event {best_id} ({best_n} prediction rows) -> {out}")
                report_lines.append((farm, category_label, best_id, str(out)))
            else:
                report_lines.append((farm, category_label, best_id, "FAILED to render"))

    hr("DEGRADATION TREND SUMMARY")
    for farm, cat, eid, info in report_lines:
        print(f"  {farm:>1} | {cat:<22} | event {eid} -> {info}")


if __name__ == "__main__":
    main()
