"""03 - Representative sensor profiling per farm.

For each farm, pick a handful of representative '_avg' sensors relevant to
Gearbox / Hydraulics / Pitch / Generator / Transformer / Rotor brake by
matching keywords against the free-text `description` column of
comma_feature_description.csv (the same approach used for event
classification in script 02, but applied to sensor descriptions instead of
event descriptions).

For the selected sensors per farm:
  - a histogram grid of value distributions
      -> outputs/charts/sensor_distributions_farm{A,B,C}.png
  - a correlation heatmap among those sensors
      -> outputs/charts/sensor_correlation_farm{A,B,C}.png

To keep this fast/memory-safe on Farm C (958 cols, 17GB), only the resolved
'_avg' columns (+ status_type_id) are read via `usecols`, and rows are
sub-sampled (every Nth row) after reading each file rather than loading full
farms into memory at once.

Run:
    python eda/scripts/03_sensor_profiling.py
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
    FARMS,
    FARM_META,
    CHARTS_DIR,
    dataset_files,
    ensure_output_dirs,
    feature_description_path,
    hr,
)

# category -> (match keywords, bonus keywords that indicate a physically
# meaningful degradation signal e.g. temperature/oil/pressure/level, used to
# rank candidates within a matched category)
CATEGORY_KEYWORDS = {
    "Gearbox": ["gear"],
    "Hydraulics": ["hydraulic"],
    "Pitch": ["pitch", "axis 1", "axis 2", "axis 3", "axis1", "axis2", "axis3"],
    "Generator": ["generator"],
    "Transformer": ["transformer"],
    # bare "brake" (not just "rotor brake") is intentional here, same as the
    # gold-layer COMPONENT_KEYWORDS match - a farm's brake instrumentation is
    # sometimes described without repeating "rotor" every time.
    "Rotor brake": ["rotor brake", "brake"],
    # Broadband vibration sensors (drive train/tower/nacelle) - condition
    # monitoring for bearing/drivetrain wear. Matched separately from
    # "Generator"/"Gearbox" bearing *temperature* sensors above - vibration is
    # a different physical signal (motion/acceleration, not heat).
    "Vibration": ["vibration"],
}
BONUS_KEYWORDS = ["temperature", "oil", "pressure", "level"]
MAX_SENSORS_PER_CATEGORY = 3

# Row sub-sampling stride per farm, chosen so histogram/correlation sample
# sizes stay in the tens-of-thousands range regardless of farm size.
SAMPLE_STRIDE = {"A": 3, "B": 3, "C": 8}


def load_feature_descriptions(farm: str) -> pd.DataFrame:
    df = pd.read_csv(feature_description_path(farm))
    df["description_lc"] = df["description"].fillna("").str.lower()
    return df


def available_columns(farm: str) -> list[str]:
    fp = dataset_files(farm)[0]
    with open(fp, encoding="utf-8") as f:
        header = f.readline().strip()
    return header.split(",")


def resolve_avg_column(sensor_name: str, columns: set[str]) -> str | None:
    avg_col = f"{sensor_name}_avg"
    if avg_col in columns:
        return avg_col
    if sensor_name in columns:
        return sensor_name
    return None


def select_representative_sensors(farm: str) -> dict[str, list[dict]]:
    """Return {category: [{"sensor_name", "column", "description"}]}."""
    feat = load_feature_descriptions(farm)
    cols = set(available_columns(farm))

    selected: dict[str, list[dict]] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        candidates = []
        for _, row in feat.iterrows():
            text = row["description_lc"]
            if any(kw in text for kw in keywords):
                col = resolve_avg_column(row["sensor_name"], cols)
                if col is None:
                    continue
                score = 1 + sum(1 for b in BONUS_KEYWORDS if b in text)
                candidates.append({
                    "sensor_name": row["sensor_name"],
                    "column": col,
                    "description": row["description"],
                    "score": score,
                })
        candidates.sort(key=lambda c: (-c["score"], c["sensor_name"]))
        selected[category] = candidates[:MAX_SENSORS_PER_CATEGORY]
    return selected


def load_sampled_farm_data(farm: str, columns: list[str]) -> pd.DataFrame:
    stride = SAMPLE_STRIDE[farm]
    frames = []
    read_cols = ["status_type_id"] + columns
    for fp in dataset_files(farm):
        df = pd.read_csv(fp, engine="pyarrow", usecols=read_cols)
        frames.append(df.iloc[::stride])
        del df
    out = pd.concat(frames, ignore_index=True)
    return out


def chart_distributions(farm: str, selected: dict[str, list[dict]], data: pd.DataFrame) -> None:
    entries = [(cat, s) for cat, sensors in selected.items() for s in sensors]
    n = len(entries)
    if n == 0:
        print(f"  [warn] no representative sensors found for {farm}, skipping distribution chart")
        return
    ncols = 4
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.2 * ncols, 3.4 * nrows))
    axes = axes.flatten() if n > 1 else [axes]
    for ax, (cat, s) in zip(axes, entries):
        vals = data[s["column"]].dropna()
        ax.hist(vals, bins=40, color="#4C72B0", edgecolor="white", linewidth=0.3)
        ax.set_title(f"[{cat}] {s['description']}", fontsize=9)
        ax.set_xlabel(s["column"], fontsize=8)
        ax.set_ylabel("count", fontsize=8)
        ax.tick_params(labelsize=7)
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(f"{FARM_META[farm]['label']} - representative sensor distributions (n={len(data):,} sampled rows)",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = CHARTS_DIR / f"sensor_distributions_farm{farm}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def chart_correlation(farm: str, selected: dict[str, list[dict]], data: pd.DataFrame) -> None:
    entries = [(cat, s) for cat, sensors in selected.items() for s in sensors]
    if len(entries) < 2:
        print(f"  [warn] fewer than 2 representative sensors for {farm}, skipping correlation chart")
        return
    cols = [s["column"] for _, s in entries]
    labels = [f"[{cat}] {s['description']}" for cat, s in entries]
    corr = data[cols].corr()

    fig, ax = plt.subplots(figsize=(1.1 * len(cols) + 3, 1.1 * len(cols) + 2))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(cols)))
    ax.set_yticklabels(labels, fontsize=8)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=7,
                     color="black" if abs(corr.values[i, j]) < 0.6 else "white")
    fig.colorbar(im, ax=ax, label="Pearson correlation", shrink=0.8)
    ax.set_title(f"{FARM_META[farm]['label']} - correlation among representative sensors\n"
                 f"(n={len(data):,} sampled rows)", fontsize=11)
    fig.tight_layout()
    out = CHARTS_DIR / f"sensor_correlation_farm{farm}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def main() -> None:
    ensure_output_dirs()
    summary = {}
    for farm in FARMS:
        hr(f"Sensor profiling - {FARM_META[farm]['label']}")
        selected = select_representative_sensors(farm)
        for cat, sensors in selected.items():
            names = [f"{s['sensor_name']} ({s['description']})" for s in sensors]
            print(f"  {cat}: {names if names else 'NO MATCH'}")

        all_cols = [s["column"] for sensors in selected.values() for s in sensors]
        if not all_cols:
            print("  No sensors selected at all - skipping charts for this farm")
            continue
        data = load_sampled_farm_data(farm, all_cols)
        print(f"  Loaded sampled dataset: {len(data):,} rows (stride={SAMPLE_STRIDE[farm]})")

        chart_distributions(farm, selected, data)
        chart_correlation(farm, selected, data)

        summary[farm] = {
            cat: [{"sensor_name": s["sensor_name"], "column": s["column"], "description": s["description"]}
                  for s in sensors]
            for cat, sensors in selected.items()
        }

    hr("SENSOR PROFILING SUMMARY")
    for farm, cats in summary.items():
        print(f"\n{FARM_META[farm]['label']}:")
        for cat, sensors in cats.items():
            if sensors:
                for s in sensors:
                    print(f"    [{cat}] {s['column']}: {s['description']}")
            else:
                print(f"    [{cat}] (no matching sensor found)")


if __name__ == "__main__":
    main()
