import type { SensorReading } from "../../shared/types";

export type { SensorReading };

/** Arguments for the `telemetry(turbineId, from, to)` AppSync query field. */
export interface TelemetryQueryArgs {
  turbineId: string;
  from: string; // ISO 8601
  to: string; // ISO 8601
}

/**
 * Minimal shape of the event AppSync sends to a direct Lambda data source resolver.
 * We only declare the parts this handler actually reads — the real event carries
 * `identity`, `source`, `request`, and `info` too, but modeling fields we never use
 * would just be speculative surface area. `field` matches the key name the
 * resolver's request template (infra/terraform/.../templates/invoke_request.vtl)
 * actually sends (`"field": "$context.info.fieldName"`) — not `fieldName`.
 */
export interface AppSyncLambdaResolverEvent<TArgs> {
  arguments: TArgs;
  field?: string;
}

export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

export class UpstreamError extends Error {
  constructor(message: string, readonly cause?: unknown) {
    super(message);
    this.name = "UpstreamError";
  }
}
