# Runbook: Wind PdM Platform v2

Operating the Docker Compose deployment (`deploy/compose`). Every command runs from
`deploy/compose` unless stated otherwise.

## Services

| Service | Role | Port | Health |
|---|---|---|---|
| `db` | TimescaleDB (PostgreSQL 16): catalog, telemetry, health scores, alerts, audit, assistant | 5434 | `pg_isready` |
| `mlflow` | MLflow 2.22 tracking and registry. Metadata on volume `mlruns`, artifacts on `mlartifacts` | 5001 | `/health` |
| `migrate` | Alembic `upgrade head`, runs once before the API starts | – | exit 0 |
| `api` | Platform API (FastAPI), including the assistant | 8000 | `/api/ready` |
| `worker` | Replay of SCADA history, online scoring, alert engine, drift checks, retrain schedule | – | heartbeat file |
| `retrainer` | Runs queued retrain jobs, one at a time | – | – |
| `web` | Console (nginx), proxies `/api` | 3000 | `/healthz` |

Volumes: `dbdata` (database), `lake` (curated Parquet lake and reports), `mlruns` (MLflow
metadata) and `mlartifacts` (model artifacts). **All four must be backed up.**

## Configuration

All settings are `WTPDM_*` variables in `deploy/compose/.env`. That file is git-ignored;
`.env.example` documents every variable. Required:

- `WTPDM_DB_PASSWORD`
- `WTPDM_JWT_SECRET`: at least 32 characters, or the API refuses to start.
- `WTPDM_ADMIN_USERNAME` / `WTPDM_ADMIN_PASSWORD`: seeds the first admin when none exists.
- `WTPDM_LLM_API_KEY`: without it the assistant reports itself unavailable.

Tunables:

| Variable | Controls | Default |
|---|---|---|
| `WTPDM_REPLAY_SPEED` | data-seconds per wall-second | 60 |
| `WTPDM_DRIFT_INTERVAL_MINUTES` | how often drift is checked | 15 |
| `WTPDM_RETRAIN_CRON` | scheduled retrain (crontab, UTC) | weekly, Sunday 02:00 |
| `WTPDM_RETRAIN_COOLDOWN_HOURS` | wait between drift-triggered retrains of a farm | 24 |
| `WTPDM_RETRAIN_AUTO_PROMOTE` | `false` makes challengers that pass the gate wait for admin approval | `true` |

## Start, stop, upgrade

```sh
docker compose up -d                 # whole stack
docker compose ps                    # health of every service
docker compose logs -f worker        # JSON logs; api logs carry request ids
docker compose stop                  # keeps all data
docker compose build && docker compose up -d   # after a code change; `migrate` applies new migrations
```

The console keeps working while the API is redeployed: nginx re-resolves the `api` address
every 10 s.

## First-time data and models

```sh
docker compose run --rm migrate python -m wtpdm.ingest.pipeline     # raw CSVs -> lake, catalog, DB
docker compose run --rm migrate python -m wtpdm.ml.train            # all farms; or --farm A
```

Ingest is idempotent. Re-running it changes a farm's `data_version` only if the data
changed. Training registers a new version per farm, which goes through the promotion gate.

## Models and retraining

- **Champions and challengers:** in the console under Models, or in MLflow under
  *Models → wtpdm-health-{A,B,C}* (aliases `champion` and `challenger`).
- **Manual retrain (admin):** console, Drift & retraining → *Request retrain*; or
  `POST /api/retrain/jobs`. One job per farm can be queued or running at a time.
- **Approving a held challenger (admin):** Models → *Approve* (shown only when the gate
  passed and auto-promotion is off).
- **Rolling back a champion:** in MLflow, move the `champion` alias to the previous version.
  The worker and API pick it up within 60 s, and the change shows in the deployment
  history.
- **A failed job:** its error is on the job (Drift & retraining → Retrain jobs) and in
  `docker compose logs retrainer`. The champion is unaffected.

## Alerts

Engineers work alerts under Alerts (acknowledge, assign, notes, resolve). An alert whose
condition has cleared stays open until resolved. After a resolution, the same turbine raises
a new alert within 24 h only if it is more severe. Every action is in the audit log.

## Users

Admins manage users under Users & audit (create, change role, deactivate, reset password).
Deactivation takes effect on the user's next request. After five failed sign-ins within
15 minutes an account is locked for the rest of that window (HTTP 429). Lockouts are
audited as `auth.login_locked`.

To recover a lost password (break-glass, from the host; audited as `user.update` by
`system:manage`; reactivates the account):

```sh
docker compose exec -it api python -m wtpdm.api.manage reset-password admin   # prompts for the new password
docker compose exec api python -m wtpdm.api.manage list-users
```

If no admin exists at all, the API creates one from `WTPDM_ADMIN_USERNAME` /
`WTPDM_ADMIN_PASSWORD` at its next start.

## Public link

The console is same-origin (`/api` proxied by nginx), so one public URL serves everything.
The optional `tunnel` service (profile `public`) opens a Cloudflare quick tunnel to `web`
only:

```sh
docker compose --profile public up -d tunnel
docker compose logs tunnel | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com'
docker compose --profile public stop tunnel      # take the link down
```

Before publishing:
- use strong passwords for every account;
- review the users (Users & audit);
- confirm that the data may be shown externally.

For a permanent hostname use a named Cloudflare tunnel or an ingress with TLS in front of
`web`. Never publish ports 5001, 5434 or 8000.

## Backups

```sh
# platform database
docker compose exec db pg_dump -U wtpdm -d wtpdm -Fc -f /tmp/wtpdm.dump && docker compose cp db:/tmp/wtpdm.dump ./backups/
# MLflow metadata and artifacts, and the lake (one archive per volume)
for v in mlruns mlartifacts lake; do
  docker run --rm -v wtpdm_$v:/v:ro -v "$PWD/backups:/b" alpine tar czf /b/$v.tgz -C /v .
done
```

To restore, stop the stack, recreate the volumes, restore with `pg_restore` and untar into
the volumes, then start the stack.

MLflow keeps its metadata in a file store (volume `mlruns`). To move it to Postgres
(database `mlflow` is reserved for this), use `mlflow-export-import` during a maintenance
window, then re-point `--backend-store-uri`. Do not drop the `mlruns` volume until the
registry is verified.

## Verification

```sh
# platform tests (unit, data contract, API, assistant; integration tests use the live DB in rolled-back transactions)
cd platform && docker compose -f ../deploy/compose/docker-compose.yml run --rm --no-deps -v "$PWD:/src" -w /src \
  -e PYTHONPATH=/src migrate sh -c 'ruff check wtpdm tests && mypy wtpdm && pytest -q'
# console: every page in Chromium against the live stack
sh frontend/console/e2e/run.sh
# assistant against the real model
docker compose exec api python -m wtpdm.assistant.eval --show-answers
# load: 25 console users through nginx, p95 and error-rate thresholds
docker run --rm --network wtpdm_default -e BASE_URL=http://web:8080 -e USERNAME=... -e PASSWORD=... \
  -v "$PWD/deploy/loadtest:/lt" grafana/k6:0.54.0 run /lt/api.js
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Console shows "Service temporarily unavailable" on models | `docker compose ps mlflow`; the API returns 503 while the registry is down |
| No health scores / fleet shows "No data" | `docker compose logs worker`: champion loaded? replay advancing (`/api/replay` → `last_update`)? |
| Live indicator "Offline" | `/api/stream` through nginx; the stream reconnects with backoff |
| Assistant "not configured" | `WTPDM_LLM_API_KEY` in `.env`, then `docker compose up -d api` |
| Assistant 502 or slow answers | LLM provider rate limits (429): the client retries with `retry-after`; see api logs |
| Retrain job stuck in "running" after a restart | the retrainer marks interrupted jobs failed on start; re-queue it |
