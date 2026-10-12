import { describe, it, expect, vi, beforeEach } from "vitest";

const getThresholdConfigMock = vi.fn();
const putAlertMock = vi.fn();
const listActiveAlertsMock = vi.fn();
const publishAlertMock = vi.fn();
const resolveAlertMock = vi.fn();

vi.mock("../src/dynamoClient", () => ({
  getThresholdConfig: (...args: unknown[]) => getThresholdConfigMock(...args),
  putAlert: (...args: unknown[]) => putAlertMock(...args),
  listActiveAlerts: (...args: unknown[]) => listActiveAlertsMock(...args),
  resolveAlert: (...args: unknown[]) => resolveAlertMock(...args),
}));
vi.mock("../src/snsClient", () => ({
  publishAlert: (...args: unknown[]) => publishAlertMock(...args),
}));

import { handler, severityFor } from "../src/handler";

describe("severityFor", () => {
  const d = (faultProbability: number, rulHoursP50: number) => ({ turbineId: "T1", component: "gearbox", faultProbability, rulHoursP50 });

  it("escalates short remaining life only when fault probability corroborates it", () => {
    expect(severityFor(d(0.5, 10))).toBe("critical");
    expect(severityFor(d(0.5, 30))).toBe("high");
  });

  it("keeps an uncorroborated short (or negative) RUL at medium", () => {
    expect(severityFor(d(0.03, -17.4))).toBe("medium");
    expect(severityFor(d(0.03, 10))).toBe("medium");
  });

  it("still escalates on fault probability alone", () => {
    expect(severityFor(d(0.95, 5000))).toBe("critical");
    expect(severityFor(d(0.85, 5000))).toBe("high");
  });
});

beforeEach(() => {
  getThresholdConfigMock.mockReset();
  putAlertMock.mockReset();
  listActiveAlertsMock.mockReset();
  publishAlertMock.mockReset();
  resolveAlertMock.mockReset();
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

  it("resolves any earlier alert when no threshold is breached", async () => {
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
    expect(resolveAlertMock).toHaveBeenCalledWith("T001#gearbox");
  });

  it("rejects malformed input (missing turbineId) before touching AWS", async () => {
    await expect(
      handler({ detail: { component: "gearbox", faultProbability: 0.9, rulHoursP50: 10 } }),
    ).rejects.toThrow(/turbineId/i);
    expect(getThresholdConfigMock).not.toHaveBeenCalled();
  });

  it("answers Query.activeAlerts (AppSync-shaped event) via the DynamoDB list path", async () => {
    const alerts = [
      { id: "T001#gearbox", turbineId: "T001", component: "gearbox", severity: "high",
        message: "m", createdAt: "2026-01-01T00:00:00Z", acknowledged: false },
    ];
    listActiveAlertsMock.mockResolvedValueOnce(alerts);

    const result = await handler({ field: "activeAlerts", arguments: {} });

    expect(result).toEqual(alerts);
    expect(listActiveAlertsMock).toHaveBeenCalledTimes(1);
    expect(getThresholdConfigMock).not.toHaveBeenCalled();
    expect(putAlertMock).not.toHaveBeenCalled();
  });

  it("wraps a DynamoDB failure on the activeAlerts read path as an UpstreamError", async () => {
    listActiveAlertsMock.mockRejectedValueOnce(new Error("throttled"));

    await expect(handler({ field: "activeAlerts" })).rejects.toThrow(/active alerts/i);
  });
});
