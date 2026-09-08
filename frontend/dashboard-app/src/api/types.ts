// Mirrors infra/terraform/modules/appsync-api/schema.graphql exactly.
// Kept as a thin local type layer (normal frontend practice for a GraphQL
// consumer) rather than importing from the infra package, which has no build
// output for the frontend to depend on.

export interface Turbine {
  id: string;
  farmId: string;
  name?: string | null;
  model?: string | null;
}

export interface SensorReading {
  turbineId: string;
  timestamp: string; // AWSDateTime (ISO 8601)
  sensor: string;
  value: number;
  unit?: string | null;
}

export type AlertSeverity = "low" | "medium" | "high" | "critical";

export interface Alert {
  id: string;
  turbineId: string;
  component: string;
  severity: string;
  message: string;
  createdAt: string;
  acknowledged: boolean;
}

export interface ForecastPoint {
  timestamp: string;
  value: number;
}

export interface Prediction {
  turbineId: string;
  component: string;
  faultProbability: number;
  rulHoursP10: number;
  rulHoursP50: number;
  rulHoursP90: number;
  forecastSeries: ForecastPoint[];
}

// AWSJSON on the schema is a free-form map (component name -> health status);
// the frontend narrows it to the three statuses the digital-twin UI renders.
export type HealthStatus = "green" | "amber" | "red";
export type ComponentHealth = Record<string, HealthStatus>;

export interface TwinState {
  turbineId: string;
  timestamp: string;
  pitchAngleDeg: number;
  rotorSpeedRpm: number;
  componentHealth: ComponentHealth;
}
