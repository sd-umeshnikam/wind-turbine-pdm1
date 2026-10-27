"""Data-quality checks on curated sensor columns (per event file, aggregated per farm)."""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

# A value repeated for this many consecutive 10-minute rows (6 h) is treated as stuck.
STUCK_RUN_ROWS = 36

# Plausible physical ranges by unit; values outside are flagged (not removed here).
PLAUSIBLE_RANGE: dict[str, tuple[float, float]] = {
    "°C": (-40.0, 180.0),
    "%": (-1.0, 101.0),
    "m/s": (0.0, 60.0),
    "rpm": (-50.0, 3000.0),
    "Hz": (0.0, 70.0),
}


@dataclass
class ColumnQuality:
    rows: int = 0
    missing: int = 0
    stuck: int = 0
    out_of_range: int = 0

    def add(self, other: ColumnQuality) -> None:
        self.rows += other.rows
        self.missing += other.missing
        self.stuck += other.stuck
        self.out_of_range += other.out_of_range

    def as_dict(self) -> dict:
        r = max(self.rows, 1)
        return {
            "rows": self.rows,
            "missing_pct": round(100 * self.missing / r, 3),
            "stuck_pct": round(100 * self.stuck / r, 3),
            "out_of_range_pct": round(100 * self.out_of_range / r, 3),
        }


@dataclass
class FarmQuality:
    farm: str
    columns: dict[str, ColumnQuality] = field(default_factory=dict)

    def merge(self, column: str, q: ColumnQuality) -> None:
        self.columns.setdefault(column, ColumnQuality()).add(q)


def stuck_mask(series: pl.Series, min_run: int = STUCK_RUN_ROWS) -> pl.Series:
    """True where the value belongs to a run of >= min_run identical consecutive values."""
    run_id = (series != series.shift(1)).fill_null(True).cum_sum()
    run_len = run_id.to_frame("r").select(pl.len().over("r")).to_series()
    return (run_len >= min_run) & series.is_not_null()


def column_quality(series: pl.Series, unit: str | None, check_stuck: bool) -> ColumnQuality:
    q = ColumnQuality(rows=series.len(), missing=series.null_count() + int(series.is_nan().sum() or 0))
    if check_stuck:
        q.stuck = int(stuck_mask(series).sum())
    bounds = PLAUSIBLE_RANGE.get(unit or "")
    if bounds:
        lo, hi = bounds
        q.out_of_range = int(((series < lo) | (series > hi)).sum() or 0)
    return q
