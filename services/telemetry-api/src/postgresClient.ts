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

  // turbineId/from/to are user-facing resolver arguments, already validated by
  // handler.ts's parseArgs — unlike the Timestream path (which has to string-build
  // its query, see timestreamClient.ts's comment), `pg` supports real parameter
  // binding, so they're passed as bind params, not interpolated. `tableName` is
  // operator config (an env var), not user input, same trust boundary as
  // TIMESTREAM_TABLE_NAME in the cloud path.
  const result = await getPool().query(
    `SELECT time, sensor, value, unit
       FROM ${tableName}
      WHERE turbine_id = $1
        AND time BETWEEN $2 AND $3
      ORDER BY time ASC`,
    [turbineId, from, to],
  );

  return result.rows.map((row) => ({
    turbineId,
    timestamp: new Date(row.time).toISOString(),
    sensor: String(row.sensor),
    value: Number(row.value),
    unit: row.unit ? String(row.unit) : "",
  }));
}
