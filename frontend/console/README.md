# Wind PdM Console

React + TypeScript console for the platform API. Every number on screen comes from the
API; when data is missing the console shows an explicit empty or error state, never a
placeholder value. `scripts/check-no-fake-data.sh` enforces this in CI and in the image
build.

| Page | What it shows |
|---|---|
| Fleet overview | KPIs, turbine × component health heatmap, latest alerts, live activity, farm cards |
| Turbines | Every turbine: health, weakest sub-part, active alert, replay position |
| Turbine | Component → sub-part health with sensors; health trends with alarm periods; measured vs expected (champion normal-behaviour model) with residuals; sensor explorer; digital twin; labelled events |
| Alerts | Work queue (filters, paging), detail drawer with drivers, acknowledge / assign / resolve / notes, activity timeline |
| Models | Registry versions per farm, champion vs challenger, detector / regressor / per-component / RUL comparisons, model card, deployments, approval (admin) |
| Drift & retraining | Drift status per farm with history against thresholds, policy, schedule, retrain jobs, manual retrain (admin) |
| Data & replay | Sensor coverage per sub-part, data-quality report, CARE events, per-turbine replay |
| Users & audit | User administration (admin), audit log (engineer+) |

Live updates come from the API's server-sent events (`/api/stream`): each event refreshes
the affected data. Times on a turbine's data clock (anonymised, per turbine) are shown in
UTC; wall-clock times (alerts, jobs, audit) are shown in the viewer's locale.

## Run

Built and served by the compose `web` service (nginx, port 3000), which proxies `/api` to
the API, so the console and API share one origin.

```sh
cd deploy/compose && docker compose up -d --build web   # http://localhost:3000
```

Development (Node 20; the host may run it in a container):

```sh
npm ci
WTPDM_API_URL=http://localhost:8000 npm run dev            # Vite on :5173, /api proxied
npm run typecheck && npm run lint && npm test && npm run check:no-fake-data
```

## End-to-end tests

`e2e/` drives every page in Chromium against the live stack (read-only) and saves
screenshots to `e2e/results/screens`. Credentials are read from the git-ignored
`deploy/compose/.env`:

```sh
sh e2e/run.sh
```
