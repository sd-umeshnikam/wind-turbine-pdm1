/**
 * Shared GraphQL-mirrored type definitions only.
 *
 * This file intentionally contains NO business logic, no validation helpers, no
 * client wrappers, and no per-service assumptions. If you find yourself wanting to
 * add a function here, it almost certainly belongs in the individual service's
 * `src/` instead — a shared logic module would recreate the monolith this platform
 * is explicitly designed to avoid (see docs/architecture/BLUEPRINT.md section 5).
 *
 * These interfaces mirror `infra/terraform/modules/appsync-api/schema.graphql`
 * field-for-field (reconciled once both were built - the Terraform and backend
 * scaffolding were done in parallel from the same brief and initially drifted:
 * `metric`/`sensor` naming, `raisedAt`/`createdAt` naming, and Prediction's
 * `forecastSeries` were the three real mismatches found and fixed). If you change
 * a field here, update schema.graphql (and vice versa) in the same change.
 */

/** Component categories the platform predicts/monitors for. Extensible beyond the
 * initial three (see BLUEPRINT.md section 4) — kept as `string` rather than a closed
 * union so adding a component doesn't require a shared-type release across services. */
export type ComponentType = string;

export type AlertSeverity = "low" | "medium" | "high" | "critical";

export type HealthStatus = "green" | "amber" | "red";

export interface Turbine {
  id: string;
  farmId: string;
  name?: string;
  model?: string;
}

export interface SensorReading {
  turbineId: string;
  timestamp: string; // ISO 8601 UTC
  sensor: string;
  value: number;
  unit: string;
}

export interface Alert {
  id: string;
  turbineId: string;
  component: ComponentType;
  severity: AlertSeverity;
  message: string;
  createdAt: string; // ISO 8601 UTC
  acknowledged: boolean;
}

export interface ForecastPoint {
  timestamp: string; // ISO 8601 UTC
  value: number;
}

export interface Prediction {
  turbineId: string;
  component: ComponentType;
  faultProbability: number; // 0..1
  rulHoursP10: number;
  rulHoursP50: number;
  rulHoursP90: number;
  forecastSeries: ForecastPoint[];
}

/** Published by digital-twin-service on the `onTwinUpdate(turbineId)` subscription. */
export interface TwinState {
  turbineId: string;
  timestamp: string; // ISO 8601 UTC
  pitchAngleDeg: number;
  rotorSpeedRpm: number;
  componentHealth: Record<ComponentType, HealthStatus>;
}
