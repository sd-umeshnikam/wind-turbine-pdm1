import { describe, it, expect, vi, beforeEach } from "vitest";

const getDatabricksAuthTokenMock = vi.fn();
const triggerJobRunMock = vi.fn();

vi.mock("../src/secretsClient", () => ({
  getDatabricksAuthToken: (...args: unknown[]) => getDatabricksAuthTokenMock(...args),
}));
vi.mock("../src/databricksJobsClient", () => ({
  triggerJobRun: (...args: unknown[]) => triggerJobRunMock(...args),
}));

import { handler } from "../src/handler";

beforeEach(() => {
  getDatabricksAuthTokenMock.mockReset();
  triggerJobRunMock.mockReset();
  getDatabricksAuthTokenMock.mockResolvedValue("test-token");
});

function s3Event(key: string, bucket = "dev-wtb-bronze") {
  return {
    Records: [{ eventName: "ObjectCreated:Put", s3: { bucket: { name: bucket }, object: { key } } }],
  };
}

describe("ingestion-trigger handler", () => {
  it("triggers a Databricks job run for a key matching the bronze prefix pattern", async () => {
    triggerJobRunMock.mockResolvedValueOnce(4242);

    const result = await handler(s3Event("farm=A/turbine=T001/2026-01-01.csv"));

    expect(result).toEqual([
      { bucket: "dev-wtb-bronze", key: "farm=A/turbine=T001/2026-01-01.csv", runId: 4242 },
    ]);
    expect(triggerJobRunMock).toHaveBeenCalledTimes(1);
  });

  it("skips (does not call Databricks for) a key outside the bronze prefix pattern", async () => {
    const result = await handler(s3Event("some-other-prefix/file.csv"));

    expect(result).toEqual([
      {
        bucket: "dev-wtb-bronze",
        key: "some-other-prefix/file.csv",
        skipped: true,
        reason: "key does not match bronze prefix pattern",
      },
    ]);
    expect(triggerJobRunMock).not.toHaveBeenCalled();
  });

  it("rejects malformed input (no Records)", async () => {
    await expect(handler({})).rejects.toThrow(/Records/);
    expect(getDatabricksAuthTokenMock).not.toHaveBeenCalled();
  });

  it("wraps a Databricks Jobs API failure as an UpstreamError instead of crashing uncaught", async () => {
    triggerJobRunMock.mockRejectedValueOnce(new Error("HTTP 500"));

    await expect(handler(s3Event("farm=A/turbine=T001/2026-01-01.csv"))).rejects.toThrow(
      /Failed to trigger Databricks job run/,
    );
  });
});
