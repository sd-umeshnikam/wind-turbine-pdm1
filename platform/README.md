# wtpdm — Wind Turbine PdM Platform v2

One Python package shared by every backend role: data ingest, model training and
evaluation, online scoring, drift/retraining, the Platform API and the assistant.

| Path | Purpose |
|---|---|
| `wtpdm/settings.py` | All configuration, from `WTPDM_*` environment variables |
| `wtpdm/db/` | SQLAlchemy models, Alembic migrations (TimescaleDB hypertables for telemetry and health scores) |
| `wtpdm/ingest/`, `wtpdm/catalog.py` | Raw CARE CSVs -> curated Parquet lake + sensor/event catalog |
| `wtpdm/ml/` | Normal-behaviour models, health index, detectors, CARE-style evaluation, MLflow training |
| `wtpdm/realtime/` | Replay of real SCADA history, online scoring, alert engine, drift monitor, worker |
| `wtpdm/mlops/` | Retrain job queue and runner, challenger approval |
| `wtpdm/api/` | FastAPI Platform API (`/api/docs`) |
| `tests/` | pytest; tests marked `integration` need the compose database |

## Run locally (Docker only — no host Python needed)

```bash
cd deploy/compose
cp .env.example .env        # set passwords/secrets
docker compose up -d --build   # db, mlflow, migrate, api, worker, retrainer, web
curl localhost:8000/api/ready
```

| Service | URL |
|---|---|
| Platform API | http://localhost:8000/api/docs |
| MLflow | http://localhost:5001 |
| PostgreSQL/TimescaleDB | localhost:5434 (db `wtpdm`) |
| Console | http://localhost:3000 |

## Checks

```bash
docker compose run --rm --no-deps -e RUFF_CACHE_DIR=/tmp/ruff migrate \
  sh -c 'ruff check wtpdm tests && mypy wtpdm && pytest -q'
```

New migration after changing `wtpdm/db/models.py`:

```bash
docker compose run --rm --no-deps -v "$PWD/../../platform:/src" -w /src -e PYTHONPATH=/src migrate \
  alembic -c wtpdm/db/alembic.ini revision --autogenerate -m "<message>"
```

## Real-time operation (P3)

The dataset is historical, so "live" means replaying it: the `worker` streams each
turbine's **actual** 10-minute SCADA rows (the prediction window of each of its CARE events
plus 24 h warm-up) into `telemetry` at `WTPDM_REPLAY_SPEED` (default 60x: one row per 10 s
tick). Timestamps stay the dataset's own, anonymised per turbine. Each tick:

1. **Replay** writes the next rows to `telemetry`; `replay_state` holds each turbine's
   cursor, loop count, current CARE event and operating status.
2. **Online scorer** runs the farm's `@champion` bundle from the MLflow registry over a 48 h
   rolling buffer and writes `health_score` (one row per sub-part plus a `turbine` row with
   the detector score and alarm flag). Health is calibrated per model version against its
   normal-operation profile: 100 = typical, 50 = alarm level (as unusual as the worst 0.5%
   of normal operation), 25 = one more step beyond. The alias is re-checked every minute,
   so a promotion goes live without a restart.
3. **Alert engine** raises one alert per turbine on a persistent alarm, sets severity from
   calibrated health (>= 50 low, 25-50 medium, 10-25 high, < 10 critical; +1 after 48 h),
   records return-to-normal (6 h below 90% of threshold) without
   closing the alert, and applies a 24 h cool-down after a human resolves it. Every
   transition is written to `alert_note` and `audit_log`.

Every 15 min the **drift monitor** compares the last 30 days of each farm's live data with a
reference profile of the champion's training data and writes `drift_report`. Out-of-support
operating conditions or a 1.5x shift in residual level queue a `drift` retrain (max one per
farm per 24 h); input PSI and alert rate are reported but never trigger one (see
`wtpdm/realtime/drift.py`). A weekly cron (`WTPDM_RETRAIN_CRON`) queues `schedule` retrains.

The `retrainer` runs queued jobs one at a time with the full training and evaluation
protocol. A challenger is promoted only if it passes the gate (no more false alarms than
the baseline + 2 days/turbine-year, and a care score at least 0.005 above the champion).
With `WTPDM_RETRAIN_AUTO_PROMOTE=false` it waits for approval:

```bash
docker compose run --rm migrate python -m wtpdm.mlops.retrain enqueue --farm A --reason "sensor swap"
docker compose run --rm migrate python -m wtpdm.mlops.retrain approve --farm A --version 3 --actor <name>
```

## Platform API (P4)

FastAPI at `/api`, OpenAPI/Swagger at `/api/docs`. Everything except `/api/health`,
`/api/ready` and `/api/openapi.json` requires a bearer token.

**Auth.** `POST /api/auth/token` (OAuth2 password form) returns a JWT (HS256, `WTPDM_JWT_SECRET`
>= 32 chars, lifetime `WTPDM_JWT_TTL_MINUTES`). The API refuses to start without a strong
secret. On first start it creates the admin from `WTPDM_ADMIN_USERNAME` /
`WTPDM_ADMIN_PASSWORD` if no admin exists. The user row is re-read on every request, so a
deactivation or role change applies at once.

| Role | Can |
|---|---|
| viewer | read fleet, turbines, alerts, models, drift, data, the event stream |
| engineer | + acknowledge / assign / resolve / annotate alerts, read the audit log |
| admin | + manage users, request retrains, approve challengers |

| Area | Endpoints |
|---|---|
| Fleet | `GET /farms`, `GET /fleet` (KPIs + every turbine at its replay cursor) |
| Turbine | `GET /turbines/{id}` (component -> sub-part health tree with sensors), `/health` (trend), `/telemetry` (downsampled avg/min/max), `/expected` (actual vs champion NBM expectation + residual z), `/events` |
| Alerts | `GET /alerts` (filters, search, paging), `/alerts/summary`, `/alerts/{id}` (notes + audit trail); `POST .../acknowledge`, `/assign`, `/resolve`, `/notes` |
| Models | `GET /models` (registry versions, aliases, gate, metrics, MLflow link), `/models/deployments`, `/models/{farm}/versions/{v}/comparison` (detectors, NBM regressors, components, RUL), `/card`, `/models/{farm}/compare?a=&b=` (default champion vs challenger); `POST .../approve` |
| Drift | `GET /drift` (latest per farm: ok / warning / drift), `/drift/history`, `/drift/policy` |
| Retrain | `GET /retrain/jobs`, `/retrain/jobs/{id}`, `/retrain/schedule`; `POST /retrain/jobs` |
| Data | `GET /data/sensors`, `/data/coverage`, `/data/quality`, `/data/events`, `/replay`, `/audit` |
| Live | `GET /stream` (server-sent events: `fleet` every 10 s, one event per audit entry such as `alert`, `model`, `retrain`, plus `drift`). EventSource clients pass `?access_token=` |

Time-series windows are anchored on each turbine's replay cursor (`from`/`to` optional,
default the last 7 days of that turbine's data time) and never extend past it. Rows after
the cursor are left over from the previous replay loop. Every state-changing call writes
`audit_log`, and alert transitions lock the alert row, so a race with the alert engine
returns 409 instead of losing an update.

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/token -d "username=admin&password=$ADMIN_PASSWORD" | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/fleet | jq .kpis
```

API integration tests (`tests/test_api.py`) run against the live database inside one
transaction per test, which is rolled back, so test users and alerts never persist.

## Maintenance assistant (P6)

A tool-calling LLM (OpenAI-compatible; Groq `openai/gpt-oss-120b` by default) over the live
platform, served under `/api/assistant` and shown as a panel in the console.

| Capability | How |
|---|---|
| Grounded answers | 14 read-only tools (fleet, turbine health, health trend, sensor deviations, measured vs expected, alerts, alert details, recommendations, models, drift, retrain jobs, labelled events, knowledge search) run in the user's session. Figures in the answer that appear nowhere in the tool results are marked *unverified*. |
| Retrieval (RAG) | BM25 over the platform guide (`assistant/knowledge/`), the maintenance playbook and each farm's champion model card from MLflow. |
| Suggested follow-ups | The LLM proposes next questions, each validated (domain, length, guardrails); a rule-based set built from the entities in the answer fills in. Starter questions use real ids from the live state and the page on screen. |
| Proactive insights | `GET /api/assistant/insights`: since the previous visit — new / escalated / re-occurred alerts, resolutions, the user's queue, model registry and retraining changes, drift, turbines below the watch level. Deterministic, from the audit log and live state. |
| Maintenance recommendations | `GET /api/assistant/recommendations?alert_id=…`: the playbook entries (`assistant/playbook.yaml`, every taxonomy sub-part) of the sub-parts the alert implicates, with the live evidence, response window by severity, safety flags and citations. Advisory only. |
| Guardrails | Prompt-injection and unsafe-operation refusal, off-topic filter, PII redaction before the provider, secret scrubbing, output length cap, 12 questions/min per user. |
| Memory & feedback | Every turn is stored in `assistant_message` (tools, citations, flags, latency); users rate answers. |

The key is read from `WTPDM_LLM_API_KEY` (git-ignored `.env`); without it the assistant
reports itself unavailable instead of answering ungrounded.

Evaluation against the live data and the real model (rolled back, leaves no rows):

```sh
docker compose -f ../deploy/compose/docker-compose.yml exec api python -m wtpdm.assistant.eval --show-answers
```

The eval set (`assistant/eval_set.yaml`) fills in real ids at run time and checks tool
selection, entity mentions, grounding, follow-ups and guardrail verdicts.
