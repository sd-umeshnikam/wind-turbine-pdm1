"""02 - Event / fault taxonomy analysis across all three farms.

Reads each farm's comma_event_info.csv, classifies every *anomaly* event's
free-text event_description into a component category via keyword matching,
and produces:
  (a) outputs/charts/fault_category_by_farm.png
        - overall anomaly counts by category
        - per-farm grouped bar of anomaly counts by category
  (b) outputs/charts/anomaly_vs_normal_by_farm.png
        - anomaly vs normal event counts per farm
  (c) outputs/charts/event_timeline.png
        - Gantt-style event_start -> event_end spans, faceted per farm,
          colored by category (or "normal")
  outputs/events_categorized.csv - full categorized event table (all farms)

NOTE on dates: this dataset (CARE / EDP-style wind-turbine SCADA benchmark)
anonymizes calendar time by shifting each turbine's clock independently, so
event_start/event_end years (which range ~2014-2029 here) are NOT real
calendar dates and are not comparable across turbines - only relative
ordering/duration within a turbine is meaningful. The timeline chart is
still useful to see event duration and clustering per farm/turbine.

Run:
    python eda/scripts/02_event_analysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    FARMS,
    FARM_META,
    CHARTS_DIR,
    OUTPUTS_DIR,
    ensure_output_dirs,
    event_info_path,
    hr,
)

# Priority-ordered keyword taxonomy (first match wins for the "primary
# category" used in the bar charts). English + a handful of German synonyms
# since Farm B/C event descriptions are written by German-speaking offshore
# operators and mix both languages.
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Gearbox", ["gear", "getriebe"]),
    ("Hydraulics", ["hydraulic", "hydraulik"]),
    ("Pitch / blade angle", ["pitch", "blade angle", "axis 1", "axis 2", "axis 3", "axis1", "axis2", "axis3"]),
    ("Generator", ["generator"]),
    ("Transformer", ["transformer", "transformator"]),
    ("Converter", ["converter", "umrichter"]),
    ("Yaw", ["yaw"]),
    ("PLC / communication / wiring", [
        "plc", "communication", "wiring", "plug", "nc300", "nc310", "bk1120",
        "harting", "beckhoff",
    ]),
    ("Rotor brake", ["rotor brake", "rotorbrake", "rotorbremse"]),
    # Checked last (lowest priority) so "Generator bearing failure" still
    # primary-categorizes as Generator - this only catches bearing-related
    # text that didn't already match a more specific component above.
    ("Bearing", ["bearing", "lager"]),
]
OTHER_LABEL = "Other / unclassified"
CATEGORY_ORDER = [c for c, _ in CATEGORY_KEYWORDS] + [OTHER_LABEL]


def categorize(description: str) -> tuple[str, list[str]]:
    """Return (primary_category, all_matched_categories) for one description."""
    if not isinstance(description, str) or not description.strip():
        return OTHER_LABEL, []
    text = description.lower()
    matched = [cat for cat, kws in CATEGORY_KEYWORDS if any(kw in text for kw in kws)]
    if not matched:
        return OTHER_LABEL, []
    return matched[0], matched


def load_all_events() -> pd.DataFrame:
    frames = []
    for farm in FARMS:
        df = pd.read_csv(event_info_path(farm), parse_dates=["event_start", "event_end"])
        df.insert(0, "farm", farm)
        frames.append(df)
    events = pd.concat(frames, ignore_index=True)
    events["duration_days"] = (events["event_end"] - events["event_start"]).dt.total_seconds() / 86400.0

    cats, matched_all = [], []
    for label, desc in zip(events["event_label"], events["event_description"]):
        if label == "anomaly":
            primary, matched = categorize(desc)
        else:
            primary, matched = "Normal (n/a)", []
        cats.append(primary)
        matched_all.append(";".join(matched))
    events["category"] = cats
    events["matched_categories"] = matched_all
    return events


def chart_fault_category_by_farm(events: pd.DataFrame) -> None:
    anomalies = events[events["event_label"] == "anomaly"].copy()

    overall_counts = anomalies["category"].value_counts()
    order = [c for c in CATEGORY_ORDER if c in overall_counts.index]
    overall_counts = overall_counts.reindex(order)

    per_farm = (
        anomalies.groupby(["category", "farm"]).size().unstack(fill_value=0).reindex(order)
    )

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 11))

    bars = ax1.bar(overall_counts.index, overall_counts.values, color="#4C72B0")
    ax1.set_title("Anomaly events by component category - all farms combined")
    ax1.set_ylabel("Number of anomaly events")
    ax1.set_xticks(range(len(overall_counts.index)))
    ax1.set_xticklabels(overall_counts.index, rotation=35, ha="right")
    for rect, val in zip(bars, overall_counts.values):
        ax1.annotate(str(int(val)), (rect.get_x() + rect.get_width() / 2, val),
                     ha="center", va="bottom", fontsize=9)

    farm_colors = {"A": "#4C72B0", "B": "#DD8452", "C": "#55A868"}
    x = range(len(per_farm.index))
    width = 0.25
    for i, farm in enumerate(FARMS):
        if farm not in per_farm.columns:
            continue
        offs = [xi + (i - 1) * width for xi in x]
        ax2.bar(offs, per_farm[farm].values, width=width, label=FARM_META[farm]["label"],
                color=farm_colors[farm])
    ax2.set_title("Anomaly events by component category - per farm")
    ax2.set_ylabel("Number of anomaly events")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(per_farm.index, rotation=35, ha="right")
    ax2.legend()

    fig.tight_layout()
    out = CHARTS_DIR / "fault_category_by_farm.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Saved {out}")


def chart_anomaly_vs_normal(events: pd.DataFrame) -> None:
    counts = events.groupby(["farm", "event_label"]).size().unstack(fill_value=0)
    counts = counts.reindex(FARMS)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    x = range(len(counts.index))
    width = 0.35
    anomaly_vals = counts.get("anomaly", pd.Series(0, index=counts.index))
    normal_vals = counts.get("normal", pd.Series(0, index=counts.index))
    b1 = ax.bar([xi - width / 2 for xi in x], anomaly_vals.values, width=width,
                label="anomaly", color="#C44E52")
    b2 = ax.bar([xi + width / 2 for xi in x], normal_vals.values, width=width,
                label="normal", color="#55A868")
    for bars in (b1, b2):
        for rect in bars:
            h = rect.get_height()
            ax.annotate(str(int(h)), (rect.get_x() + rect.get_width() / 2, h),
                        ha="center", va="bottom", fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels([FARM_META[f]["label"] for f in counts.index])
    ax.set_ylabel("Number of labeled events")
    ax.set_title("Anomaly vs normal reference events per farm")
    ax.legend()
    fig.tight_layout()
    out = CHARTS_DIR / "anomaly_vs_normal_by_farm.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Saved {out}")


def chart_event_timeline(events: pd.DataFrame) -> None:
    cmap_categories = CATEGORY_ORDER + ["Normal (n/a)"]
    palette = plt.get_cmap("tab10").colors
    color_map = {cat: palette[i % len(palette)] for i, cat in enumerate(cmap_categories)}

    counts = {farm: (events["farm"] == farm).sum() for farm in FARMS}
    # Give each farm's panel enough vertical room (~0.28in/row, min 3in) so
    # 58-row Farm C is legible instead of squashed into the same height as
    # 15-row Farm B.
    row_heights = {farm: max(3.0, 0.28 * counts[farm]) for farm in FARMS}
    total_height = sum(row_heights.values()) + 2.0

    fig, axes = plt.subplots(
        3, 1, figsize=(14, total_height),
        gridspec_kw={"height_ratios": [row_heights[f] for f in FARMS]},
    )
    for ax, farm in zip(axes, FARMS):
        sub = events[events["farm"] == farm].sort_values("event_start").reset_index(drop=True)
        for i, row in sub.iterrows():
            color = color_map.get(row["category"], "gray")
            ax.barh(
                y=i,
                width=(row["event_end"] - row["event_start"]),
                left=row["event_start"],
                height=0.65,
                color=color,
            )
        ax.set_yticks(range(len(sub)))
        labels = [
            f"evt {r.event_id} ({'anom' if r.event_label=='anomaly' else 'norm'})"
            for r in sub.itertuples()
        ]
        fontsize = 7 if counts[farm] <= 25 else 6
        ax.set_yticklabels(labels, fontsize=fontsize)
        ax.set_ylim(-0.7, len(sub) - 0.3)
        ax.set_title(f"{FARM_META[farm]['label']} - event windows (event_start -> event_end), n={len(sub)}")
        ax.set_xlabel("Timestamp (per-turbine anonymized clock - not comparable across turbines)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.invert_yaxis()

    handles = [plt.Rectangle((0, 0), 1, 1, color=color_map[c]) for c in cmap_categories]
    fig.legend(handles, cmap_categories, loc="lower center", ncol=4, fontsize=8,
               bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Event timeline (Gantt-style) per farm, colored by fault category", fontsize=13)
    fig.tight_layout(rect=[0, 0.03, 1, 0.98])
    out = CHARTS_DIR / "event_timeline.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


def print_human_summary(events: pd.DataFrame) -> None:
    hr("EVENT / FAULT TAXONOMY SUMMARY")
    print(f"Total events across all farms: {len(events)} "
          f"({(events['event_label']=='anomaly').sum()} anomaly, "
          f"{(events['event_label']=='normal').sum()} normal)")
    for farm in FARMS:
        sub = events[events["farm"] == farm]
        n_anom = (sub["event_label"] == "anomaly").sum()
        n_norm = (sub["event_label"] == "normal").sum()
        print(f"\n{FARM_META[farm]['label']}: {n_anom} anomaly / {n_norm} normal events")
        cat_counts = sub[sub["event_label"] == "anomaly"]["category"].value_counts()
        for cat, cnt in cat_counts.items():
            print(f"    {cat}: {cnt}")
    print("\nOverall anomaly category counts (all farms):")
    overall = events[events["event_label"] == "anomaly"]["category"].value_counts()
    for cat, cnt in overall.items():
        print(f"    {cat}: {cnt}")
    print(f"\nMost common category overall: {overall.idxmax()} ({overall.max()} events)")


def main() -> None:
    ensure_output_dirs()
    events = load_all_events()

    csv_out = OUTPUTS_DIR / "events_categorized.csv"
    events.to_csv(csv_out, index=False)
    print(f"Saved categorized event table to {csv_out}")

    chart_fault_category_by_farm(events)
    chart_anomaly_vs_normal(events)
    chart_event_timeline(events)

    print_human_summary(events)


if __name__ == "__main__":
    main()
