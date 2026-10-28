import { describe, expect, it } from "vitest";
import { errorMessage, queryString } from "../api/client";
import type { ConditionReading } from "../api/types";
import { pickReading } from "../pages/turbine/TwinTab";
import { ago, dataTime, num, pct, withUnit } from "./format";
import { band } from "./health";
import { windowFrom } from "./range";

describe("health bands", () => {
  it("puts the calibrated alarm level at 50", () => {
    expect(band(49.9)).toBe("alarm");
    expect(band(50)).toBe("degraded");
    expect(band(65)).toBe("watch");
    expect(band(80)).toBe("good");
    expect(band(null)).toBe("none");
  });
});

describe("formatting", () => {
  it("never invents a value for missing data", () => {
    expect(num(null)).toBe("—");
    expect(withUnit(null, "°C")).toBe("—");
    expect(pct(undefined)).toBe("—");
    expect(dataTime(null)).toBe("—");
  });
  it("shows data-clock times in UTC", () => {
    expect(dataTime("2019-01-13T03:20:00Z")).toBe("2019-01-13 03:20 UTC");
  });
  it("describes ages", () => {
    const now = Date.parse("2026-10-28T12:00:00Z");
    expect(ago("2026-10-28T11:59:50Z", now)).toBe("just now");
    expect(ago("2026-10-28T11:00:00Z", now)).toBe("1 h ago");
  });
});

describe("api client", () => {
  it("drops empty params and repeats arrays", () => {
    expect(queryString({ a: 1, b: "", c: undefined, d: null, severity: ["high", "critical"] })).toBe(
      "?a=1&severity=high&severity=critical",
    );
    expect(queryString({})).toBe("");
  });
  it("reads FastAPI error bodies", () => {
    expect(errorMessage({ detail: "No turbine X" }, "x")).toBe("No turbine X");
    expect(errorMessage({ detail: [{ msg: "too short" }, { msg: "bad" }] }, "x")).toBe("too short; bad");
    expect(errorMessage("<html>", "fallback")).toBe("fallback");
  });
});

describe("windows on the turbine clock", () => {
  it("ends at the cursor and rounds the start to the hour", () => {
    expect(windowFrom("2019-01-13T03:20:00Z", 1)).toBe("2019-01-12T03:00:00Z");
    expect(windowFrom(null, 7)).toBeUndefined();
  });
});

describe("digital twin readings", () => {
  const r = (kind: string, description: string, value: number | null): ConditionReading => ({
    code: description,
    description,
    unit: null,
    kind,
    value,
    ts: null,
  });
  const readings = [
    r("rotor_speed", "Generator converter rotational speed", 1200),
    r("rotor_speed", "Rotor speed", 12),
    r("power", "Total active power", null),
  ];
  it("prefers the rotor over the generator", () => {
    expect(pickReading(readings, "rotor_speed", /rotor/i, /generator/i)?.value).toBe(12);
  });
  it("does not substitute a generator speed when no rotor speed exists", () => {
    expect(pickReading([readings[0]!], "rotor_speed", /rotor/i, /generator/i)).toBeUndefined();
  });
  it("ignores readings without a value", () => {
    expect(pickReading(readings, "power")).toBeUndefined();
  });
});
