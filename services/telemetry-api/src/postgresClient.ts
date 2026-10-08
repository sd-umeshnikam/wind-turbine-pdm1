import { Pool } from "pg";
import type { SensorReading } from "./types";

/**
 * Local-hosting backend (see docs/LINUX_HOSTING_GUIDE.md and ADR-0004) — queries a
 * TimescaleDB hypertable instead of Amazon Timestream. Selected via
 * `TELEMETRY_BACKEND=postgres` in handler.ts; the cloud path (Timestream) is
 * untouched. Returns `SensorReading[]` directly rather than mirroring
 * Timestream's column-info/row-array shape, since there's no equivalent
 * generic-result format to preserve here — Postgres rows are already named columns.
 */

let pool: Pool | undefined;

function getPool(): Pool {
  if (!pool) {
    pool = new Pool({ connectionString: process.env.TIMESCALE_URL });
  }
  return pool;
}

export async function queryReadings(
  turbineId: string,
  from: string,
  to: string,
): Promise<SensorReading[]> {
  const tableName = process.env.TIMESCALE_TABLE_NAME ?? "sensor_readings";
  const pool = getPool();

  // This backend holds bounded historical slices anchored to each turbine's own
  // real fault-event timing (see pipeline/04_sync_timescale.py's docstring),
  // not continuously arriving live data - callers (the frontend) ask for "the
  // last 48h" meaning wall-clock now, but that almost never overlaps any given
  // turbine's actual synced range (as of writing, only 15 of 36 turbines have
  // any data in a literal now-48h window on a given day). Anchoring to this
  // turbine's own latest reading instead - keeping the caller's requested
  // *duration*, not its literal end time - means "last 48h" always resolves to
  // this turbine's most recent 48h of real data. Only affects this local
  // (Postgres) backend; the cloud path (timestreamClient.ts) is untouched.
  const latestResult = await pool.query(
    `SELECT max(time) as latest FROM ${tableName} WHERE turbine_id = $1`,
    [turbineId],
  );
  const latest: Date | null = latestResult.rows[0]?.latest ?? null;
  let queryFrom = from;
  let queryTo = to;
  if (latest) {
    const requestedDurationMs = new Date(to).getTime() - new Date(from).getTime();
    queryTo = latest.toISOString();
    queryFrom = new Date(latest.getTime() - requestedDurationMs).toISOString();
  }

  // turbineId/from/to are user-facing resolver arguments, already validated by
  // handler.ts's parseArgs — unlike the Timestream path (which has to string-build
  // its query, see timestreamClient.ts's comment), `pg` supports real parameter
  // binding, so they're passed as bind params, not interpolated. `tableName` is
  // operator config (an env var), not user input, same trust boundary as
  // TIMESTREAM_TABLE_NAME in the cloud path.
  const result = await pool.query(
    `SELECT time, sensor, value, unit
       FROM ${tableName}
      WHERE turbine_id = $1
        AND time BETWEEN $2 AND $3
      ORDER BY time ASC`,
    [turbineId, queryFrom, queryTo],
  );

  return result.rows.map((row) => ({
    turbineId,
    timestamp: new Date(row.time).toISOString(),
    sensor: String(row.sensor),
    value: Number(row.value),
    unit: row.unit ? String(row.unit) : "",
  }));
}
