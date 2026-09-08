import { describe, it, expect, vi, beforeEach } from "vitest";

const runQueryMock = vi.fn();
const queryReadingsMock = vi.fn();

vi.mock("../src/timestreamClient", () => ({
  runQuery: (...args: unknown[]) => runQueryMock(...args),
}));
vi.mock("../src/postgresClient", () => ({
  queryReadings: (...args: unknown[]) => queryReadingsMock(...args),
}));

// Imported after the mocks so the handler picks up the mocked modules.
import { handler } from "../src/handler";

beforeEach(() => {
  runQueryMock.mockReset();
  queryReadingsMock.mockReset();
  process.env.TIMESTREAM_DATABASE_NAME = "wtb_dev";
  process.env.TIMESTREAM_TABLE_NAME = "telemetry";
  delete process.env.TELEMETRY_BACKEND;
});

describe("telemetry-api handler", () => {
  it("maps a happy-path Timestream response to SensorReading[]", async () => {
    runQueryMock.mockResolvedValueOnce({
      columnInfo: [
        { Name: "time", Type: { ScalarType: "TIMESTAMP" } },
        { Name: "measure_name", Type: { ScalarType: "VARCHAR" } },
        { Name: "measure_value", Type: { ScalarType: "DOUBLE" } },
        { Name: "unit", Type: { ScalarType: "VARCHAR" } },
      ],
      rows: [
        {
          Data: [
            { ScalarValue: "2026-01-01 00:00:00.000000000" },
            { ScalarValue: "gearbox_oil_temp" },
            { ScalarValue: "62.5" },
            { ScalarValue: "celsius" },
          ],
        },
      ],
    });

    const result = await handler({
      arguments: {
        turbineId: "T001",
        from: "2026-01-01T00:00:00Z",
        to: "2026-01-02T00:00:00Z",
      },
    });

    expect(result).toEqual([
      {
        turbineId: "T001",
        timestamp: "2026-01-01 00:00:00.000000000",
        sensor: "gearbox_oil_temp",
        value: 62.5,
        unit: "celsius",
      },
    ]);
  });

  it("returns an empty array for a range with no readings, without throwing", async () => {
    runQueryMock.mockResolvedValueOnce({ columnInfo: [], rows: [] });

    const result = await handler({
      arguments: {
        turbineId: "T001",
        from: "2026-01-01T00:00:00Z",
        to: "2026-01-01T00:05:00Z",
      },
    });

    expect(result).toEqual([]);
  });

  it("rejects malformed input (missing turbineId) before calling Timestream", async () => {
    await expect(
      handler({
        arguments: {
          from: "2026-01-01T00:00:00Z",
          to: "2026-01-02T00:00:00Z",
        },
      }),
    ).rejects.toThrow(/turbineId/i);

    expect(runQueryMock).not.toHaveBeenCalled();
  });

  it("wraps a Timestream failure as an UpstreamError instead of crashing uncaught", async () => {
    runQueryMock.mockRejectedValueOnce(new Error("throttled"));

    await expect(
      handler({
        arguments: {
          turbineId: "T001",
          from: "2026-01-01T00:00:00Z",
          to: "2026-01-02T00:00:00Z",
        },
      }),
    ).rejects.toThrow(/Failed to read telemetry/);
  });

  it("uses the Postgres/Timescale backend when TELEMETRY_BACKEND=postgres, not Timestream", async () => {
    process.env.TELEMETRY_BACKEND = "postgres";
    queryReadingsMock.mockResolvedValueOnce([
      { turbineId: "T001", timestamp: "2026-01-01T00:00:00.000Z", sensor: "gearbox_oil_temp", value: 62.5, unit: "celsius" },
    ]);

    const result = await handler({
      arguments: { turbineId: "T001", from: "2026-01-01T00:00:00Z", to: "2026-01-02T00:00:00Z" },
    });

    expect(result).toEqual([
      { turbineId: "T001", timestamp: "2026-01-01T00:00:00.000Z", sensor: "gearbox_oil_temp", value: 62.5, unit: "celsius" },
    ]);
    expect(queryReadingsMock).toHaveBeenCalledWith("T001", "2026-01-01T00:00:00.000Z", "2026-01-02T00:00:00.000Z");
    expect(runQueryMock).not.toHaveBeenCalled();
  });

  it("wraps a Timescale failure as an UpstreamError too", async () => {
    process.env.TELEMETRY_BACKEND = "postgres";
    queryReadingsMock.mockRejectedValueOnce(new Error("connection refused"));

    await expect(
      handler({
        arguments: { turbineId: "T001", from: "2026-01-01T00:00:00Z", to: "2026-01-02T00:00:00Z" },
      }),
    ).rejects.toThrow(/Failed to read telemetry/);
  });
});
