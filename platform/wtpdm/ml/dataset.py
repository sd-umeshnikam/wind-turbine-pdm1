"""Assemble a farm's modelling frame from the curated lake.

Evaluation follows the CARE benchmark protocol: every event file holds one turbine's
normal `train` history followed by a `prediction` window leading into a labelled outcome
(anomaly = a real fault, normal = nothing happened). Models learn normal behaviour from
`train` rows only and are scored on `prediction` windows.

Leakage guard: a turbine appears in several event files whose time ranges can overlap,
so a `train` row of one file may fall inside another file's anomaly window. Any row of a
turbine that lies inside ANY of that turbine's anomaly windows (prediction start to event
end) is excluded from training.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from wtpdm import catalog

# Monitored sensors are dropped as model targets when the curated data says they are
# mostly stuck or missing (see ingest data-quality report).
MAX_STUCK_PCT = 50.0
MAX_MISSING_PCT = 5.0


@dataclass(frozen=True)
class FarmSchema:
    farm: str
    conditions: dict[str, str]  # kind -> "<sensor>_avg"
    targets: dict[str, list[str]]  # subcomponent -> ["<sensor>_avg", ...]
    descriptions: dict[str, str]  # "<sensor>_avg" -> human description
    units: dict[str, str | None]
    excluded: dict[str, str]  # "<sensor>_avg" -> reason

    @property
    def condition_columns(self) -> list[str]:
        return list(self.conditions.values())

    @property
    def target_columns(self) -> list[str]:
        return [c for cols in self.targets.values() for c in cols]

    def subcomponent_of(self, column: str) -> str:
        return next(sub for sub, cols in self.targets.items() if column in cols)


def farm_schema(lake_root: Path, farm: str) -> FarmSchema:
    sensors = catalog.sensors(lake_root, farm)
    quality = catalog.data_quality(lake_root, farm)
    conditions = {kind: f"{code}_avg" for kind, code in catalog.conditions(lake_root, farm).items()}
    targets: dict[str, list[str]] = {}
    excluded: dict[str, str] = {}
    for r in sensors.filter(pl.col("role") == "monitored").iter_rows(named=True):
        col = f"{r['code']}_avg"
        q = quality.get(r["code"], {})
        if r["is_counter"] or r["is_angle"]:
            excluded[col] = "counter/angle"
        elif q.get("stuck_pct", 0) > MAX_STUCK_PCT:
            excluded[col] = f"stuck {q['stuck_pct']:.0f}%"
        elif q.get("missing_pct", 0) > MAX_MISSING_PCT:
            excluded[col] = f"missing {q['missing_pct']:.0f}%"
        else:
            targets.setdefault(r["subcomponent_code"], []).append(col)
    descriptions = {f"{r['code']}_avg": r["description"] for r in sensors.iter_rows(named=True)}
    units = {f"{r['code']}_avg": r["unit"] for r in sensors.iter_rows(named=True)}
    return FarmSchema(farm, conditions, dict(sorted(targets.items())), descriptions, units, excluded)


def load_farm_frame(lake_root: Path, schema: FarmSchema) -> pl.DataFrame:
    """All curated rows of the farm with event context:

    split, operating, label ('anomaly'|'normal' of the row's own event file),
    event_start / event_end of the row's own file - for anomaly events this is the
    ABNORMAL PERIOD: event_start = onset of abnormal behaviour, event_end = failure /
    repair -, in_event_window, hours_to_failure (event_end - ts),
    in_any_anomaly_window, train_ok.
    """
    events = catalog.events(lake_root, schema.farm)
    cols = [
        "ts",
        "turbine_id",
        "event_id",
        "split",
        "status",
        "operating",
        *schema.condition_columns,
        *schema.target_columns,
    ]
    frames = [
        pl.read_parquet(catalog.curated_event_path(lake_root, schema.farm, int(e)), columns=cols)
        for e in events["event_id"].to_list()
    ]
    df = pl.concat(frames, how="vertical_relaxed")
    ev = events.select(
        pl.col("event_id").cast(pl.Int32),
        pl.col("label"),
        pl.col("event_start"),
        pl.col("event_end"),
        pl.col("component_code").alias("event_component"),
    )
    df = df.join(ev, on="event_id", how="left").with_columns(
        ((pl.col("event_end") - pl.col("ts")).dt.total_seconds() / 3600)
        .cast(pl.Float32)
        .alias("hours_to_failure"),
        ((pl.col("ts") >= pl.col("event_start")) & (pl.col("ts") <= pl.col("event_end"))).alias(
            "in_event_window"
        ),
    )

    # Leakage guard: mark rows inside any anomaly window of the same turbine.
    windows = events.filter(pl.col("label") == "anomaly").select(
        "turbine_id", pl.col("prediction_start").alias("w_start"), pl.col("event_end").alias("w_end")
    )
    flagged = (
        df.select("turbine_id", "ts")
        .unique()
        .join(windows, on="turbine_id", how="inner")
        .filter((pl.col("ts") >= pl.col("w_start")) & (pl.col("ts") <= pl.col("w_end")))
        .select("turbine_id", "ts")
        .unique()
        .with_columns(pl.lit(True).alias("in_any_anomaly_window"))
    )
    df = df.join(flagged, on=["turbine_id", "ts"], how="left").with_columns(
        pl.col("in_any_anomaly_window").fill_null(False)
    )
    return df.with_columns(
        (
            (pl.col("split") == "train")
            & pl.col("operating")
            & ~pl.col("in_any_anomaly_window")
            & pl.all_horizontal(pl.col(c).is_not_null() for c in schema.condition_columns)
        ).alias("train_ok")
    )
