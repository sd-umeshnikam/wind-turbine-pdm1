"""Curate one raw event file into the lake.

Output: <lake>/curated/farm=<F>/event=<id>.parquet with columns
    ts (UTC), turbine_id, event_id, row_id, split ('train'|'prediction'), status (int8),
    operating (bool), <sensor>_avg / <sensor>_std (float32)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from wtpdm.ingest.quality import ColumnQuality, column_quality
from wtpdm.ingest.source import SensorSpec

# CARE status_type_id: 0 normal, 1 derated, 2 idling, 3 service, 4 downtime, 5 other.
# Only normal and derated operation describe the turbine working under load.
OPERATING_STATUS = (0, 1)
KEPT_STATS = ("avg", "std")  # min/max add little for 10-min aggregates and double the volume


class IngestError(ValueError):
    pass


@dataclass(frozen=True)
class CuratedFile:
    path: Path
    asset_id: int
    rows: int
    window_start: datetime
    window_end: datetime
    prediction_start: datetime | None
    quality: dict[str, ColumnQuality]


def read_raw_event_file(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, infer_schema_length=10_000)


def asset_of(raw: pl.DataFrame, farm: str, event_id: int) -> int:
    assets = raw["asset_id"].unique().to_list()
    if len(assets) != 1:
        raise IngestError(f"farm {farm} event {event_id}: expected one asset_id, found {assets}")
    return int(assets[0])


def curate_event_file(
    raw: pl.DataFrame,
    *,
    farm: str,
    event_id: int,
    turbine_id: str,
    sensors: list[SensorSpec],
    out_dir: Path,
) -> CuratedFile:
    asset_id = asset_of(raw, farm, event_id)

    sensor_exprs: list[pl.Expr] = []
    quality: dict[str, ColumnQuality] = {}
    for s in sensors:
        for stat in KEPT_STATS:
            col = f"{s.code}_{stat}"
            source = col
            if col not in raw.columns:
                # Single-statistic sensors (e.g. Farm A's 10-minute energy counters, incl.
                # "Total active power") are stored without a suffix: that IS their average.
                if stat == "avg" and s.code in raw.columns:
                    source = s.code
                else:
                    continue
            sensor_exprs.append(pl.col(source).cast(pl.Float32, strict=False).alias(col))
            if stat == "avg":
                quality[s.code] = column_quality(
                    raw[source].cast(pl.Float32, strict=False),
                    s.unit,
                    check_stuck=not (s.is_counter or s.is_angle),
                )

    df = (
        raw.lazy()
        .select(
            pl.col("time_stamp").str.to_datetime(time_zone="UTC").alias("ts"),
            pl.lit(turbine_id).alias("turbine_id"),
            pl.lit(event_id, dtype=pl.Int32).alias("event_id"),
            pl.col("id").cast(pl.Int32).alias("row_id"),
            pl.col("train_test").str.to_lowercase().alias("split"),
            pl.col("status_type_id").cast(pl.Int8).alias("status"),
            *sensor_exprs,
        )
        .with_columns(pl.col("status").is_in(OPERATING_STATUS).alias("operating"))
        .sort("ts")
        .collect()
    )
    if df["ts"].null_count():
        raise IngestError(f"farm {farm} event {event_id}: unparseable timestamps")
    if df["ts"].is_duplicated().any():
        df = df.unique(subset="ts", keep="first", maintain_order=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"event={event_id}.parquet"
    df.write_parquet(path, compression="zstd", statistics=True)

    pred = df.filter(pl.col("split") == "prediction")["ts"]
    return CuratedFile(
        path=path,
        asset_id=asset_id,
        rows=df.height,
        window_start=df["ts"].min(),  # type: ignore[arg-type]
        window_end=df["ts"].max(),  # type: ignore[arg-type]
        prediction_start=pred.min() if pred.len() else None,  # type: ignore[arg-type]
        quality=quality,
    )
