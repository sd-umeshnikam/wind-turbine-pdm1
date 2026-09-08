import type { Prediction, ForecastPoint } from "../../shared/types";

export type { Prediction, ForecastPoint };

/** Arguments for the `predictions(turbineId, component?)` AppSync query field. */
export interface PredictionQueryArgs {
  turbineId: string;
  component?: string;
}

export interface AppSyncLambdaResolverEvent<TArgs> {
  arguments: TArgs;
  fieldName?: string;
}

/** Shape returned by the Databricks Model Serving REST endpoint. Databricks Model
 * Serving wraps custom pyfunc/MLflow model output under `predictions` — the inner
 * shape is whatever the model logs, which we assume follows this scaffold's schema. */
export interface DatabricksServingResponse {
  predictions: Array<{
    turbine_id: string;
    component: string;
    fault_probability: number;
    rul_hours_p10: number;
    rul_hours_p50: number;
    rul_hours_p90: number;
    forecast_series?: Array<{ timestamp: string; value: number }>;
  }>;
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
