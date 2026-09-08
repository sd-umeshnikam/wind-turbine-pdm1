import type { Alert, AlertSeverity, ComponentType } from "../../shared/types";

export type { Alert, AlertSeverity };

/**
 * Shape of the `detail` field on the EventBridge event that triggers this service.
 * ASSUMPTION (documented): no formal EventBridge schema registry entry exists yet
 * for "new prediction" events, so this mirrors the `Prediction` fields relevant to
 * threshold evaluation, published by prediction-api / the Gold-sync job after a new
 * inference or Gold row lands.
 */
export interface PredictionEventDetail {
  turbineId: string;
  component: ComponentType;
  faultProbability: number;
  rulHoursP50: number;
}

export interface EventBridgeLikeEvent {
  "detail-type"?: string;
  detail: unknown;
}

/** Per-component thresholds, stored in DynamoDB so ops can tune sensitivity without
 * a redeploy. `src/dynamoClient.ts` falls back to DEFAULT_THRESHOLDS when no
 * config item exists yet for a component. */
export interface AlertThresholdConfig {
  component: ComponentType;
  faultProbabilityThreshold: number;
  rulHoursP50Threshold: number;
}

export const DEFAULT_THRESHOLDS: Omit<AlertThresholdConfig, "component"> = {
  faultProbabilityThreshold: 0.7,
  rulHoursP50Threshold: 72,
};

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
