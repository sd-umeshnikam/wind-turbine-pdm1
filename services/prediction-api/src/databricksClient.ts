import type { DatabricksServingResponse } from "./types";

export interface DatabricksInvokeParams {
  turbineId: string;
  component?: string;
}

/**
 * Calls a Databricks Model Serving real-time endpoint (see ADR-0002). The endpoint
 * URL and auth token are both env-var driven so swapping to a SageMaker endpoint
 * later only touches this file and its two env vars, not the handler or the
 * GraphQL-facing contract (per ADR-0002's stated consequence).
 */
export async function invokeModel(
  params: DatabricksInvokeParams,
): Promise<DatabricksServingResponse> {
  const url = process.env.DATABRICKS_SERVING_URL;
  const token = process.env.DATABRICKS_SERVING_TOKEN;
  if (!url || !token) {
    throw new Error("DATABRICKS_SERVING_URL / DATABRICKS_SERVING_TOKEN are not configured.");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        dataframe_records: [
          { turbine_id: params.turbineId, component: params.component ?? null },
        ],
      }),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    throw new Error(`Databricks serving endpoint returned HTTP ${response.status}`);
  }

  return (await response.json()) as DatabricksServingResponse;
}
