"""Live replay of real SCADA history into the telemetry hypertable.

The CARE dataset is historical, so "real time" means streaming each turbine's ACTUAL
10-minute rows at a configurable speed - no value is synthesised. Per turbine the replay
timeline is the prediction window of every one of its events (the periods that lead into a
labelled outcome, fault or normal), each preceded by 24 h of warm-up history, in time
order and de-duplicated where windows of the same turbine overlap (the anomaly event wins,
so the row keeps its fault context). Rows keep their dataset timestamps, which are
anonymised per turbine: every turbine runs on its own clock. At the end of its timeline a
turbine loops back to the start (`cycle` counts the loops).

Timelines are materialised once per catalog version under <lake>/replay/farm=<F>/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import polars as pl
from sqlalchemy import Engine, text

from wtpdm import catalog
from wtpdm.logging import get_logger

log = get_logger("replay")
ROW_SECONDS = 600
WARMUP_ROWS = 144  # 24 h before each prediction window: smoothing is warm when it starts
TIMELINE_FORMAT = 1


def timeline_dir(lake_root: Path, farm: str) -> Path:
    return lake_root / "replay" / f"farm={farm}"


def timeline_path(lake_root: Path, farm: str, turbine_id: str) -> Path:
    return timeline_dir(lake_root, farm) / f"turbine={turbine_id}.parquet"


def sensor_columns(lake_root: Path, farm: str) -> list[str]:
    return [f"{code}_avg" for code in catalog.sensors(lake_root, farm)["code"].to_list()]


def merge_windows(parts: list[pl.DataFrame]) -> pl.DataFrame:
    """One turbine's event windows -> a single time-ordered timeline. Where windows overlap,
    the row of an anomaly event is kept (it carries the fault context)."""
    merged = pl.concat(parts, how="diagonal_relaxed")
    return (
        merged.with_columns((pl.col("label") != "anomaly").cast(pl.Int8).alias("_prio"))
        .sort(["ts", "_prio"])
        .unique(subset="ts", keep="first", maintain_order=True)
        .drop("_prio")
    )


def build_timelines(lake_root: Path, farm: str) -> dict[str, int]:
    """Write one replay timeline per turbine of the farm; returns turbine -> rows."""
    events = catalog.events(lake_root, farm)
    wanted = sensor_columns(lake_root, farm)
    per_turbine: dict[str, list[pl.DataFrame]] = {}
    for e in events.iter_rows(named=True):
        path = catalog.curated_event_path(lake_root, farm, int(e["event_id"]))
        present = set(pl.read_parquet_schema(path))
        cols = ["ts", "turbine_id", "status", *[c for c in wanted if c in present]]
        df = pl.read_parquet(path, columns=cols).sort("ts")
        start = df["ts"].search_sorted(e["prediction_start"])
        df = df.slice(max(0, start - WARMUP_ROWS)).with_columns(
            pl.lit(int(e["event_id"]), dtype=pl.Int32).alias("event_id"),
            pl.lit(e["label"]).alias("label"),
        )
        per_turbine.setdefault(e["turbine_id"], []).append(df)

    out = timeline_dir(lake_root, farm)
    out.mkdir(parents=True, exist_ok=True)
    rows = {}
    for turbine_id, parts in sorted(per_turbine.items()):
        timeline = merge_windows(parts)
        timeline.write_parquet(timeline_path(lake_root, farm, turbine_id))
        rows[turbine_id] = timeline.height
    meta = {"format": TIMELINE_FORMAT, "data_version": catalog.data_version(lake_root, farm), "rows": rows}
    (out / "_meta.json").write_text(json.dumps(meta, indent=2))
    log.info("replay timelines built", farm=farm, turbines=len(rows), rows=sum(rows.values()))
    return rows


def ensure_timelines(lake_root: Path, farm: str) -> dict[str, int]:
    """Timelines of the current catalog version (rebuilt after a re-ingest)."""
    meta_path = timeline_dir(lake_root, farm) / "_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("format") == TIMELINE_FORMAT and meta.get("data_version") == catalog.data_version(
            lake_root, farm
        ):
            return {t: int(n) for t, n in meta["rows"].items()}
    return build_timelines(lake_root, farm)


class TickClock:
    """Converts wall-clock ticks into whole 10-minute rows, carrying the fraction over so
    the long-run replay speed is exact (e.g. 60x with 10 s ticks = 1 row per tick)."""

    def __init__(self, speed: float, tick_seconds: float):
        self.rows_per_tick = speed * tick_seconds / ROW_SECONDS
        self._carry = 0.0

    def rows(self) -> int:
        self._carry += self.rows_per_tick
        n = int(self._carry)
        self._carry -= n
        return n


@dataclass
class TurbineStream:
    turbine_id: str
    farm: str
    path: Path
    total: int
    position: int = 0  # index of the next row to emit
    cycle: int = 0

    def next_rows(self, n: int) -> pl.DataFrame:
        """Up to n rows; never crosses the loop point, so a batch is always time-ordered."""
        if self.position >= self.total:
            self.position, self.cycle = 0, self.cycle + 1
        batch = pl.scan_parquet(self.path).slice(self.position, n).collect()
        self.position += batch.height
        return batch


# Bulk path: COPY into a transaction-local staging table, then one INSERT that skips rows
# already present (a looped replay re-sends rows it wrote in an earlier cycle).
STAGE_TELEMETRY = (
    "CREATE TEMP TABLE IF NOT EXISTS telemetry_stage"
    " (turbine_id text, ts timestamptz, sensor_id int, value real) ON COMMIT DELETE ROWS"
)
COPY_TELEMETRY = "COPY telemetry_stage (turbine_id, ts, sensor_id, value) FROM STDIN (FORMAT csv)"
MERGE_TELEMETRY = (
    "INSERT INTO telemetry (turbine_id, ts, sensor_id, value)"
    " SELECT turbine_id, ts, sensor_id, value FROM telemetry_stage ON CONFLICT DO NOTHING"
)

UPSERT_STATE = text(
    """
    INSERT INTO replay_state (turbine_id, cursor_ts, status, position, total_rows, cycle,
                              source_event_id, operating_status, updated_at)
    VALUES (:turbine_id, :cursor_ts, 'running', :position, :total_rows, :cycle,
            :source_event_id, :operating_status, now())
    ON CONFLICT (turbine_id) DO UPDATE SET
        cursor_ts = EXCLUDED.cursor_ts, status = EXCLUDED.status, position = EXCLUDED.position,
        total_rows = EXCLUDED.total_rows, cycle = EXCLUDED.cycle,
        source_event_id = EXCLUDED.source_event_id, operating_status = EXCLUDED.operating_status,
        updated_at = now()
    """
)


class Replay:
    """Advances every turbine of the given farms by the same number of rows per tick and
    writes them to telemetry. `tick()` returns the new rows per farm (wide format) for the
    online scorer."""

    def __init__(self, engine: Engine, lake_root: Path, farms: list[str], speed: float, tick_seconds: float):
        self.engine = engine
        self.lake_root = lake_root
        self.farms = farms
        self.clock = TickClock(speed, tick_seconds)
        self.streams: dict[str, TurbineStream] = {}
        self.sensor_ids: dict[str, dict[str, int]] = {}  # farm -> "<code>_avg" -> sensor.id

    def start(self) -> None:
        with self.engine.connect() as conn:
            saved = {
                r.turbine_id: r
                for r in conn.execute(text("SELECT turbine_id, position, cycle FROM replay_state"))
            }
            for farm in self.farms:
                self.sensor_ids[farm] = {
                    f"{code}_avg": sid
                    for sid, code in conn.execute(
                        text("SELECT id, code FROM sensor WHERE farm_id = :f"), {"f": farm}
                    )
                }
        for farm in self.farms:
            for turbine_id, total in ensure_timelines(self.lake_root, farm).items():
                prev = saved.get(turbine_id)
                self.streams[turbine_id] = TurbineStream(
                    turbine_id,
                    farm,
                    timeline_path(self.lake_root, farm, turbine_id),
                    total,
                    position=min(prev.position, total) if prev else 0,
                    cycle=prev.cycle if prev else 0,
                )
        log.info(
            "replay started",
            turbines=len(self.streams),
            rows_per_tick=round(self.clock.rows_per_tick, 3),
            resumed=sum(1 for t in self.streams if t in saved),
        )

    def tick(self) -> dict[str, pd.DataFrame]:
        n = self.clock.rows()
        if n == 0:
            return {}
        batches: dict[str, list[pl.DataFrame]] = {}
        states = []
        for stream in self.streams.values():
            rows = stream.next_rows(n)
            if rows.height == 0:
                continue
            batches.setdefault(stream.farm, []).append(rows)
            last = rows.row(-1, named=True)
            states.append(
                {
                    "turbine_id": stream.turbine_id,
                    "cursor_ts": last["ts"],
                    "position": stream.position,
                    "total_rows": stream.total,
                    "cycle": stream.cycle,
                    "source_event_id": last["event_id"],
                    "operating_status": last["status"],
                }
            )
        out = {}
        with self.engine.begin() as conn:
            for farm, parts in batches.items():
                wide = pl.concat(parts, how="diagonal_relaxed")
                self._write_telemetry(conn, farm, wide)
                out[farm] = wide.to_pandas(use_pyarrow_extension_array=False)
            if states:
                conn.execute(UPSERT_STATE, states)
        return out

    def _write_telemetry(self, conn, farm: str, wide: pl.DataFrame) -> None:
        ids = self.sensor_ids[farm]
        cols = [c for c in wide.columns if c in ids]
        long = (
            wide.unpivot(index=["turbine_id", "ts"], on=cols, variable_name="col", value_name="value")
            .drop_nulls("value")
            .filter(pl.col("value").is_not_nan())
            .with_columns(pl.col("col").replace_strict(ids, return_dtype=pl.Int32).alias("sensor_id"))
        )
        if not long.height:
            return
        csv = long.select("turbine_id", "ts", "sensor_id", "value").write_csv(
            include_header=False, datetime_format="%Y-%m-%d %H:%M:%S%z"
        )
        with conn.connection.driver_connection.cursor() as cur:
            cur.execute(STAGE_TELEMETRY)
            with cur.copy(COPY_TELEMETRY) as copy:
                copy.write(csv)
            cur.execute(MERGE_TELEMETRY)
