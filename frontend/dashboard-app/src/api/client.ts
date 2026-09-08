// GraphQL client for the AppSync API defined in
// infra/terraform/modules/appsync-api/schema.graphql.
//
// Client approach: plain `fetch`-based GraphQL calls, not Amplify's
// `generateClient` from `aws-amplify/api`. Reasoning: `aws-amplify` requires
// `Amplify.configure(...)` with a Cognito user pool / identity pool at
// startup, and this scaffold pass explicitly defers auth wiring (see task
// constraints - Cognito is a backend/infra concern covered elsewhere). Pulling
// in the full Amplify client now would mean either half-configuring it (a
// footgun for whoever wires auth later) or configuring it against
// not-yet-real infra. A ~30-line fetch wrapper covers query/mutation needs
// with zero extra dependency weight. The one place Amplify would earn its
// keep is `Subscription.onTwinUpdate`, which needs AppSync's realtime
// (WebSocket) protocol - real IAM/API-key signed subscriptions are nontrivial
// to hand-roll. Since there is no live AppSync endpoint yet, that function
// always drives its demo animation from a local mock ticker; swapping in
// `aws-amplify/api`'s `client.graphql({query, variables}).subscribe(...)` is
// the natural upgrade once an endpoint and auth mode exist.
import type {
  Alert,
  ComponentHealth,
  ForecastPoint,
  Prediction,
  SensorReading,
  TwinState,
} from "./types";

const APPSYNC_URL = import.meta.env.VITE_APPSYNC_URL as string | undefined;
const APPSYNC_API_KEY = import.meta.env.VITE_APPSYNC_API_KEY as string | undefined;

async function graphqlRequest<T>(
  query: string,
  variables: Record<string, unknown>,
): Promise<T> {
  if (!APPSYNC_URL) {
    throw new Error("VITE_APPSYNC_URL not configured");
  }
  const res = await fetch(APPSYNC_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(APPSYNC_API_KEY ? { "x-api-key": APPSYNC_API_KEY } : {}),
    },
    body: JSON.stringify({ query, variables }),
  });
  if (!res.ok) {
    throw new Error(`AppSync request failed: ${res.status}`);
  }
  const body = (await res.json()) as { data?: T; errors?: unknown[] };
  if (body.errors && body.errors.length > 0) {
    throw new Error(`AppSync returned errors: ${JSON.stringify(body.errors)}`);
  }
  if (!body.data) {
    throw new Error("AppSync response had no data");
  }
  return body.data;
}

const COMPONENTS = [
  "Gearbox",
  "Hydraulics",
  "Pitch System",
  "Generator",
  "Transformer",
  "Rotor Brake",
  "Bearing",
] as const;

function hoursAgoIso(hours: number, from: Date): string {
  return new Date(from.getTime() - hours * 3600_000).toISOString();
}

// --- Telemetry -------------------------------------------------------------

const TELEMETRY_QUERY = /* GraphQL */ `
  query Telemetry($turbineId: ID!, $from: AWSDateTime!, $to: AWSDateTime!) {
    telemetry(turbineId: $turbineId, from: $from, to: $to) {
      turbineId
      timestamp
      sensor
      value
      unit
    }
  }
`;

function mockTelemetry(turbineId: string, from: string, to: string): SensorReading[] {
  const fromMs = new Date(from).getTime();
  const toMs = new Date(to).getTime();
  const points = 48;
  const stepMs = (toMs - fromMs) / points;
  const sensors: Array<{ name: string; unit: string; base: number; amp: number }> = [
    { name: "gearbox_oil_temp", unit: "°C", base: 55, amp: 8 },
    { name: "hydraulic_oil_temp", unit: "°C", base: 42, amp: 6 },
    { name: "pitch_motor_temp", unit: "°C", base: 38, amp: 5 },
    { name: "generator_bearing_temp", unit: "°C", base: 60, amp: 7 },
    { name: "transformer_oil_temp", unit: "°C", base: 50, amp: 6 },
    { name: "rotor_brake_pressure", unit: "bar", base: 120, amp: 10 },
    { name: "bearing_vibration_rms", unit: "mG", base: 3, amp: 2 },
  ];
  const readings: SensorReading[] = [];
  for (let i = 0; i < points; i++) {
    const t = new Date(fromMs + i * stepMs).toISOString();
    for (const s of sensors) {
      const wave = Math.sin(i / 6 + s.base) * s.amp;
      const drift = (i / points) * (s.name === "hydraulic_oil_temp" ? 4 : 1);
      const noise = (Math.sin(i * 13.7 + s.base) * 0.5) * 1.5;
      readings.push({
        turbineId,
        timestamp: t,
        sensor: s.name,
        value: Math.round((s.base + wave + drift + noise) * 10) / 10,
        unit: s.unit,
      });
    }
  }
  return readings;
}

export async function getTelemetry(
  turbineId: string,
  from: string,
  to: string,
): Promise<SensorReading[]> {
  try {
    const data = await graphqlRequest<{ telemetry: SensorReading[] }>(TELEMETRY_QUERY, {
      turbineId,
      from,
      to,
    });
    return data.telemetry;
  } catch {
    return mockTelemetry(turbineId, from, to);
  }
}

// --- Predictions -------------------------------------------------------------

const PREDICTIONS_QUERY = /* GraphQL */ `
  query Predictions($turbineId: ID!, $component: String) {
    predictions(turbineId: $turbineId, component: $component) {
      turbineId
      component
      faultProbability
      rulHoursP10
      rulHoursP50
      rulHoursP90
      forecastSeries {
        timestamp
        value
      }
    }
  }
`;

function mockForecastSeries(baseRul: number, volatility: number): ForecastPoint[] {
  const now = new Date();
  const points: ForecastPoint[] = [];
  for (let i = 0; i < 14; i++) {
    const t = new Date(now.getTime() + i * 24 * 3600_000).toISOString();
    const decay = Math.max(0, baseRul - i * (baseRul / 16));
    const noise = Math.sin(i * 1.9) * volatility;
    points.push({ timestamp: t, value: Math.round((decay + noise) * 10) / 10 });
  }
  return points;
}

function mockPredictions(turbineId: string, component?: string): Prediction[] {
  const defs = [
    { component: "Gearbox", p50: 620, spread: 140, prob: 0.18 },
    { component: "Hydraulics", p50: 340, spread: 90, prob: 0.32 },
    { component: "Pitch System", p50: 890, spread: 160, prob: 0.09 },
    { component: "Generator", p50: 1100, spread: 200, prob: 0.07 },
    { component: "Transformer", p50: 1450, spread: 260, prob: 0.04 },
    { component: "Rotor Brake", p50: 780, spread: 120, prob: 0.11 },
    { component: "Bearing", p50: 540, spread: 160, prob: 0.21 },
  ];
  return defs
    .filter((d) => !component || d.component === component)
    .map((d) => ({
      turbineId,
      component: d.component,
      faultProbability: d.prob,
      rulHoursP10: Math.max(0, d.p50 - d.spread),
      rulHoursP50: d.p50,
      rulHoursP90: d.p50 + d.spread,
      forecastSeries: mockForecastSeries(d.p50 / 24, d.spread / 24 / 4),
    }));
}

export async function getPredictions(
  turbineId: string,
  component?: string,
): Promise<Prediction[]> {
  try {
    const data = await graphqlRequest<{ predictions: Prediction[] }>(PREDICTIONS_QUERY, {
      turbineId,
      component: component ?? null,
    });
    return data.predictions;
  } catch {
    return mockPredictions(turbineId, component);
  }
}

// --- Alerts -------------------------------------------------------------

const ACTIVE_ALERTS_QUERY = /* GraphQL */ `
  query ActiveAlerts {
    activeAlerts {
      id
      turbineId
      component
      severity
      message
      createdAt
      acknowledged
    }
  }
`;

function mockActiveAlerts(): Alert[] {
  const now = new Date();
  const raw: Array<[string, string, string, string, number]> = [
    ["A-03", "Hydraulics", "high", "Hydraulic oil temperature sustained 14°C above baseline", 2],
    ["C-11", "Pitch System", "critical", "Axis 2 pitch motor not ready-to-operate", 1],
    ["C-06", "Gearbox", "medium", "Gearbox oil pressure erratic, intermittent drop-outs", 9],
    ["A-01", "Transformer", "low", "Transformer temperature trending upward, within limits", 30],
    ["C-19", "PLC / communication", "medium", "Beckhoff card intermittent comms fault", 14],
    ["C-12", "Rotor Brake", "high", "Rotor brake B pressure irregular, two-pump mode active", 3],
    ["B-02", "Bearing", "high", "Tower vibration sustained elevated band post-shutdown, main bearing suspect", 6],
  ];
  return raw.map(([turbineId, component, severity, message, hoursAgo], i) => ({
    id: `alert-${i + 1}`,
    turbineId,
    component,
    severity,
    message,
    createdAt: hoursAgoIso(hoursAgo, now),
    acknowledged: false,
  }));
}

export async function getActiveAlerts(): Promise<Alert[]> {
  try {
    const data = await graphqlRequest<{ activeAlerts: Alert[] }>(ACTIVE_ALERTS_QUERY, {});
    return data.activeAlerts;
  } catch {
    return mockActiveAlerts();
  }
}

// Real ack is a backend mutation not yet in schema.graphql; this stubs the
// contract the Alerts module needs and optimistically resolves so the UI can
// be built against it now.
export async function acknowledgeAlert(alertId: string): Promise<{ id: string }> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  return { id: alertId };
}

// --- Digital twin subscription -------------------------------------------------------------

function randomHealth(prevHealth: ComponentHealth): ComponentHealth {
  const health: ComponentHealth = {};
  for (const component of COMPONENTS) {
    const prev = prevHealth[component] ?? "green";
    // Mostly stable, small chance of drifting one step so the demo panel visibly varies.
    const roll = Math.random();
    if (roll < 0.85) {
      health[component] = prev;
    } else if (prev === "green") {
      health[component] = "amber";
    } else if (prev === "amber") {
      health[component] = Math.random() < 0.5 ? "green" : "red";
    } else {
      health[component] = "amber";
    }
  }
  return health;
}

export function subscribeToTwinUpdates(
  turbineId: string,
  onUpdate: (state: TwinState) => void,
): () => void {
  let health: ComponentHealth = Object.fromEntries(
    COMPONENTS.map((c) => [c, "green"]),
  ) as ComponentHealth;
  let tick = 0;
  const intervalId = setInterval(() => {
    tick += 1;
    health = randomHealth(health);
    const rotorSpeedRpm = 12 + Math.sin(tick / 5) * 5 + Math.random() * 0.6;
    const pitchAngleDeg = 10 + Math.sin(tick / 7) * 15;
    onUpdate({
      turbineId,
      timestamp: new Date().toISOString(),
      pitchAngleDeg: Math.round(pitchAngleDeg * 10) / 10,
      rotorSpeedRpm: Math.round(rotorSpeedRpm * 10) / 10,
      componentHealth: health,
    });
  }, 1200);
  return () => clearInterval(intervalId);
}

export const KNOWN_COMPONENTS = COMPONENTS;
