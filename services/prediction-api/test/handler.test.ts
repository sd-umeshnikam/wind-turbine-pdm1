import { describe, it, expect, vi, beforeEach } from "vitest";

const invokeModelMock = vi.fn();

vi.mock("../src/databricksClient", () => ({
  invokeModel: (...args: unknown[]) => invokeModelMock(...args),
}));

import { handler } from "../src/handler";

beforeEach(() => {
  invokeModelMock.mockReset();
});

describe("prediction-api handler", () => {
  it("maps a Databricks serving response to Prediction[]", async () => {
    invokeModelMock.mockResolvedValueOnce({
      predictions: [
        {
          turbine_id: "T001",
          component: "gearbox",
          fault_probability: 0.82,
          rul_hours_p10: 40,
          rul_hours_p50: 120,
          rul_hours_p90: 300,
          forecast_series: [{ timestamp: "2026-01-01T00:00:00Z", value: 0.6 }],
        },
      ],
    });

    const result = await handler({ arguments: { turbineId: "T001" } });

    expect(result).toEqual([
      {
        turbineId: "T001",
        component: "gearbox",
        faultProbability: 0.82,
        rulHoursP10: 40,
        rulHoursP50: 120,
        rulHoursP90: 300,
        forecastSeries: [{ timestamp: "2026-01-01T00:00:00Z", value: 0.6 }],
      },
    ]);
  });

  it("rejects malformed input (missing turbineId)", async () => {
    await expect(handler({ arguments: {} })).rejects.toThrow(/turbineId/i);
    expect(invokeModelMock).not.toHaveBeenCalled();
  });

  it("wraps an upstream failure instead of crashing uncaught", async () => {
    invokeModelMock.mockRejectedValueOnce(new Error("HTTP 503"));

    await expect(handler({ arguments: { turbineId: "T001" } })).rejects.toThrow(
      /Failed to reach the model serving endpoint/,
    );
  });
});
