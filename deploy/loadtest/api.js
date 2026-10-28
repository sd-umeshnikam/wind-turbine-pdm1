// API load test (k6). Simulates console users: fleet overview polling, turbine pages,
// health trends, telemetry, the alert queue and model pages, through the nginx front end.
//
//   docker run --rm --network wtpdm_default -e BASE_URL=http://web:8080 \
//     -e USERNAME=... -e PASSWORD=... -v "$PWD/deploy/loadtest:/lt" grafana/k6:0.54.0 run /lt/api.js
//
// Thresholds are the release gate: p95 < 800 ms on reads, < 1% failed requests.
import http from "k6/http";
import { check, group, sleep } from "k6";

const BASE = __ENV.BASE_URL || "http://web:8080";

export const options = {
  scenarios: {
    console_users: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "20s", target: Number(__ENV.VUS || 25) },
        { duration: __ENV.HOLD || "60s", target: Number(__ENV.VUS || 25) },
        { duration: "10s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{kind:read}": ["p(95)<800"],
    "http_req_duration{kind:heavy}": ["p(95)<2500"],
  },
};

export function setup() {
  const res = http.post(`${BASE}/api/auth/token`, { username: __ENV.USERNAME, password: __ENV.PASSWORD });
  check(res, { "login ok": (r) => r.status === 200 });
  const token = res.json("access_token");
  const fleet = http.get(`${BASE}/api/fleet`, { headers: { Authorization: `Bearer ${token}` } }).json();
  const turbines = fleet.turbines.filter((t) => t.health !== null).map((t) => t.id);
  return { token, turbines };
}

export default function (data) {
  const headers = { Authorization: `Bearer ${data.token}` };
  const read = { headers, tags: { kind: "read" } };
  const heavy = { headers, tags: { kind: "heavy" } };
  const turbine = data.turbines[Math.floor(__VU + __ITER) % data.turbines.length];

  group("fleet", () => {
    check(http.get(`${BASE}/api/fleet`, read), { "fleet 200": (r) => r.status === 200 });
    check(http.get(`${BASE}/api/alerts/summary`, read), { "summary 200": (r) => r.status === 200 });
    check(http.get(`${BASE}/api/alerts?active=true&limit=6&sort=-updated_at`, read), { "alerts 200": (r) => r.status === 200 });
    check(http.get(`${BASE}/api/replay`, read), { "replay 200": (r) => r.status === 200 });
  });
  sleep(1);
  group("turbine", () => {
    const detail = http.get(`${BASE}/api/turbines/${turbine}`, read);
    check(detail, { "turbine 200": (r) => r.status === 200 });
    check(http.get(`${BASE}/api/turbines/${turbine}/snapshot`, read), { "snapshot 200": (r) => r.status === 200 });
    check(http.get(`${BASE}/api/turbines/${turbine}/health?points=600`, heavy), { "health 200": (r) => r.status === 200 });
    const sensor = detail.json("components_tree.0.subparts.0.sensors.0.code");
    if (sensor) {
      check(http.get(`${BASE}/api/turbines/${turbine}/telemetry?sensors=${sensor}&points=400`, heavy), {
        "telemetry 200": (r) => r.status === 200,
      });
    }
  });
  sleep(1);
  group("models & drift", () => {
    check(http.get(`${BASE}/api/models`, read), { "models 200": (r) => r.status === 200 });
    check(http.get(`${BASE}/api/drift`, read), { "drift 200": (r) => r.status === 200 });
  });
  sleep(2);
}
