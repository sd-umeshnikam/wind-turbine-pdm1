import { runQuery } from "./timestreamClient";
import {
  AppSyncLambdaResolverEvent,
  TelemetryQueryArgs,
  SensorReading,
  ValidationError,
  UpstreamError,
} from "./types";
import type { ColumnInfo, Row } from "@aws-sdk/client-timestream-query";

const TURBINE_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * Validates and normalizes resolver arguments.
 *
 * Amazon Timestream's Query API has no bind-parameter mechanism (unlike, say, the
 * RDS Data API) — the query is always a single string. Since we can't parameterize
 * our way out of injection, we defend by strict allow-list validation instead:
 * turbineId must match a narrow identifier pattern, and from/to are only accepted
 * if they parse as real dates, then re-serialized from the parsed Date (never the
 * raw input) before being interpolated into the query string.
 */
function parseArgs(rawArgs: unknown): TelemetryQueryArgs {
  if (typeof rawArgs !== "object" || rawArgs === null) {
    throw new ValidationError("Missing query arguments.");
  }
  const args = rawArgs as Record<string, unknown>;

  const turbineId = args.turbineId;
  if (typeof turbineId !== "string" || turbineId.length === 0) {
    throw new ValidationError("turbineId is required.");
  }
  if (!TURBINE_ID_PATTERN.test(turbineId)) {
    throw new ValidationError("turbineId contains invalid characters.");
  }

  const from = normalizeTimestamp(args.from, "from");
  const to = normalizeTimestamp(args.to, "to");

  if (new Date(from).getTime() > new Date(to).getTime()) {
    throw new ValidationError("`from` must not be after `to`.");
  }

  return { turbineId, from, to };
}

function normalizeTimestamp(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new ValidationError(`${fieldName} is required.`);
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new ValidationError(`${fieldName} is not a valid ISO 8601 timestamp.`);
  }
  return parsed.toISOString();
}

function buildQuery(args: TelemetryQueryArgs): string {
  // Read lazily (not at module load) so tests can set env vars per-case and so a cold
  // start doesn't cache a value from before Lambda env config is fully resolved.
  const databaseName = process.env.TIMESTREAM_DATABASE_NAME ?? "";
  const tableName = process.env.TIMESTREAM_TABLE_NAME ?? "";
  if (!databaseName || !tableName) {
    throw new UpstreamError(
      "TIMESTREAM_DATABASE_NAME / TIMESTREAM_TABLE_NAME are not configured.",
    );
  }
  // turbineId/from/to are validated+normalized by parseArgs before reaching here.
  return `
    SELECT time, measure_name, measure_value::double AS measure_value, "unit"
    FROM "${databaseName}"."${tableName}"
    WHERE turbine_id = '${args.turbineId}'
      AND time BETWEEN from_iso8601_timestamp('${args.from}') AND from_iso8601_timestamp('${args.to}')
    ORDER BY time ASC
  `.trim();
}

function mapRowsToReadings(
  turbineId: string,
  columnInfo: ColumnInfo[],
  rows: Row[],
): SensorReading[] {
  const columnIndex = new Map<string, number>();
  columnInfo.forEach((col, idx) => {
    if (col.Name) columnIndex.set(col.Name, idx);
  });

  const timeIdx = columnIndex.get("time");
  const sensorIdx = columnIndex.get("measure_name");
  const valueIdx = columnIndex.get("measure_value");
  const unitIdx = columnIndex.get("unit");

  return rows.map((row) => {
    const data = row.Data ?? [];
    const timestamp = timeIdx !== undefined ? data[timeIdx]?.ScalarValue : undefined;
    const sensor = sensorIdx !== undefined ? data[sensorIdx]?.ScalarValue : undefined;
    const rawValue = valueIdx !== undefined ? data[valueIdx]?.ScalarValue : undefined;
    const unit = unitIdx !== undefined ? data[unitIdx]?.ScalarValue : undefined;

    return {
      turbineId,
      timestamp: timestamp ?? "",
      sensor: sensor ?? "",
      value: rawValue !== undefined ? Number(rawValue) : NaN,
      unit: unit ?? "",
    };
  });
}

/**
 * AppSync direct Lambda data source resolver for `Query.telemetry`.
 * Throwing here surfaces as a GraphQL field error to the client (AppSync's normal
 * error-propagation path for a Lambda data source) — we throw only for input
 * validation and upstream failure, and return `[]` for the legitimate "no readings
 * in range" case so callers can tell "empty" from "broken" apart.
 */
export async function handler(
  event: AppSyncLambdaResolverEvent<unknown>,
): Promise<SensorReading[]> {
  const args = parseArgs(event.arguments);
  const query = buildQuery(args);

  let result;
  try {
    result = await runQuery(query);
  } catch (err) {
    console.error("Timestream query failed", { turbineId: args.turbineId, err });
    throw new UpstreamError("Failed to read telemetry from Timestream.", err);
  }

  if (!result.rows.length) {
    return [];
  }

  return mapRowsToReadings(args.turbineId, result.columnInfo, result.rows);
}
