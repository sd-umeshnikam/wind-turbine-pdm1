import { invokeModel } from "./databricksClient";
import {
  AppSyncLambdaResolverEvent,
  PredictionQueryArgs,
  Prediction,
  ValidationError,
  UpstreamError,
} from "./types";

const TURBINE_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

function parseArgs(rawArgs: unknown): PredictionQueryArgs {
  if (typeof rawArgs !== "object" || rawArgs === null) {
    throw new ValidationError("Missing query arguments.");
  }
  const args = rawArgs as Record<string, unknown>;

  const turbineId = args.turbineId;
  if (typeof turbineId !== "string" || !TURBINE_ID_PATTERN.test(turbineId)) {
    throw new ValidationError("turbineId is required and must be a valid identifier.");
  }

  const component = args.component;
  if (component !== undefined && typeof component !== "string") {
    throw new ValidationError("component, if provided, must be a string.");
  }

  return { turbineId, component };
}

/**
 * AppSync direct Lambda data source resolver for `Query.predictions`.
 * Returns `[]` when the model genuinely has no prediction for this turbine/component
 * (an empty `predictions` array from Databricks) — distinct from the upstream being
 * unreachable/erroring, which throws so AppSync surfaces a GraphQL error instead of
 * silently showing "no predictions" for what's actually an outage.
 */
export async function handler(
  event: AppSyncLambdaResolverEvent<unknown>,
): Promise<Prediction[]> {
  const args = parseArgs(event.arguments);

  let response;
  try {
    response = await invokeModel({ turbineId: args.turbineId, component: args.component });
  } catch (err) {
    console.error("Databricks Model Serving call failed", { turbineId: args.turbineId, err });
    throw new UpstreamError("Failed to reach the model serving endpoint.", err);
  }

  if (!response.predictions?.length) {
    return [];
  }

  return response.predictions.map((p) => ({
    turbineId: p.turbine_id,
    component: p.component,
    faultProbability: p.fault_probability,
    rulHoursP10: p.rul_hours_p10,
    rulHoursP50: p.rul_hours_p50,
    rulHoursP90: p.rul_hours_p90,
    forecastSeries: (p.forecast_series ?? []).map((point) => ({
      timestamp: point.timestamp,
      value: point.value,
    })),
  }));
}
