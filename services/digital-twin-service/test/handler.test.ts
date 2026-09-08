import { describe, it, expect, vi, beforeEach } from "vitest";

const getLatestStateMock = vi.fn();
const publishTwinUpdateMock = vi.fn();

vi.mock("../src/twinStateStore", () => ({
  getLatestState: (...args: unknown[]) => getLatestStateMock(...args),
}));
vi.mock("../src/appsyncClient", () => ({
  publishTwinUpdate: (...args: unknown[]) => publishTwinUpdateMock(...args),
}));

import { handler } from "../src/handler";

beforeEach(() => {
  getLatestStateMock.mockReset();
  publishTwinUpdateMock.mockReset();
});

describe("digital-twin-service handler", () => {
  it("publishes the latest state for a turbine that has reported telemetry", async () => {
    getLatestStateMock.mockResolvedValueOnce({
      turbineId: "T001",
      updatedAt: "2026-01-01T00:00:00Z",
      pitchAngleDeg: 12.5,
      rotorSpeedRpm: 14.2,
      componentHealth: { gearbox: "green", hydraulics: "amber", pitch_system: "green" },
    });
    publishTwinUpdateMock.mockResolvedValueOnce(undefined);

    const result = await handler({ detail: { turbineId: "T001" } });

    expect(result).toEqual({ published: true });
    expect(publishTwinUpdateMock).toHaveBeenCalledWith(
      expect.objectContaining({ turbineId: "T001", pitchAngleDeg: 12.5 }),
    );
  });

  it("returns published:false without calling AppSync when there is no state yet", async () => {
    getLatestStateMock.mockResolvedValueOnce(undefined);

    const result = await handler({ detail: { turbineId: "T002" } });

    expect(result).toEqual({ published: false });
    expect(publishTwinUpdateMock).not.toHaveBeenCalled();
  });

  it("rejects malformed input (missing turbineId)", async () => {
    await expect(handler({ detail: {} })).rejects.toThrow(/turbineId/i);
    expect(getLatestStateMock).not.toHaveBeenCalled();
  });
});
