import type { TwinState, HealthStatus, ComponentType } from "../../shared/types";

export type { TwinState, HealthStatus };

/** Shape of the EventBridge event's `detail` that triggers this service — either a
 * "new telemetry landed for this turbine" event, or (documented assumption) a
 * scheduled sweep event carrying the turbine to refresh. */
export interface TwinTriggerEventDetail {
  turbineId: string;
}

export interface EventBridgeLikeEvent {
  "detail-type"?: string;
  detail: unknown;
}

/** Raw latest-state row as stored in DynamoDB by the telemetry-sync path. */
export interface LatestStateItem {
  turbineId: string;
  updatedAt: string;
  pitchAngleDeg: number;
  rotorSpeedRpm: number;
  componentHealth: Record<ComponentType, HealthStatus>;
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
