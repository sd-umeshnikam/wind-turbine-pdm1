import { describe, it, expect, vi, beforeEach } from "vitest";

const getThresholdConfigMock = vi.fn();
const putAlertMock = vi.fn();
const publishAlertMock = vi.fn();

vi.mock("../src/dynamoClient", () => ({
  getThresholdConfig: (...args: unknown[]) => getThresholdConfigMock(...args),
  putAlert: (...args: unknown[]) => putAlertMock(...args),
}));
vi.mock("../src/snsClient", () => ({
  publishAlert: (...args: unknown[]) => publishAlertMock(...args),
}));

import { handler } from "../src/handler";

beforeEach(() => {
  getThresholdConfigMock.mockReset();
  putAlertMock.mockReset();
  publishAlertMock.mockReset();
});

describe("alerting-service handler", () => {
  it("raises and publishes an alert when faultProbability breaches the threshold", async () => {
    getThresholdConfigMock.mockResolvedValueOnce({
      component: "gearbox",
      faultProbabilityThreshold: 0.7,
      rulHoursP50Threshold: 72,
    });
    putAlertMock.mockResolvedValueOnce(undefined);
    publishAlertMock.mockResolvedValueOnce(undefined);

    const result = await handler({
      "detail-type": "prediction.updated",
      detail: { turbineId: "T001", component: "gearbox", faultProbability: 0.95, rulHoursP50: 200 },
    });

    expect(result).toEqual({ alerted: true });
    expect(putAlertMock).toHaveBeenCalledTimes(1);
    expect(publishAlertMock).toHaveBeenCalledTimes(1);
    const [alertArg] = putAlertMock.mock.calls[0] as [{ severity: string }];
    expect(alertArg.severity).toBe("critical");
  });

  it("does nothing when no threshold is breached", async () => {
    getThresholdConfigMock.mockResolvedValueOnce({
      component: "gearbox",
      faultProbabilityThreshold: 0.7,
      rulHoursP50Threshold: 72,
    });

    const result = await handler({
      detail: { turbineId: "T001", component: "gearbox", faultProbability: 0.1, rulHoursP50: 500 },
    });

    expect(result).toEqual({ alerted: false });
    expect(putAlertMock).not.toHaveBeenCalled();
    expect(publishAlertMock).not.toHaveBeenCalled();
  });

  it("rejects malformed input (missing turbineId) before touching AWS", async () => {
    await expect(
      handler({ detail: { component: "gearbox", faultProbability: 0.9, rulHoursP50: 10 } }),
    ).rejects.toThrow(/turbineId/i);
    expect(getThresholdConfigMock).not.toHaveBeenCalled();
  });
});
