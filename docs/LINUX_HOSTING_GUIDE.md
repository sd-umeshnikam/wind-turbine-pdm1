# Linux Hosting Guide — Full Stack, Including the Data Pipeline

This walks through running the **entire** platform on a single local Linux box:
the medallion pipeline (real Spark + Delta Lake), real model training (LightGBM +
statsmodels), a local model-serving API, a local GraphQL gateway substituting
AppSync, TimescaleDB substituting Timestream, LocalStack substituting
DynamoDB/SNS/S3, and the React dashboard served by nginx.

**Read [ADR-0004](adr/0004-local-hosting-substitutions.md) first** — it's the
one-page table of what's a genuine open-source substitute, what's a documented
simplification, and what's explicitly out of scope. This guide is the *how*; that
ADR is the *why*.

**If you just want the dashboard running against realistic mock data** (no
pipeline, no AWS-shaped services at all), you don't need any of this — see
[`docs/DEVELOPER_SETUP.md`](DEVELOPER_SETUP.md) instead, it's a five-minute path.

## 0. Architecture at a glance

```
Raw SCADA CSVs (sibling folder)
        │
        ▼
local-stack/pipeline/  (real PySpark + Delta Lake, run_pipeline.sh)
  01 bronze → 02 silver → 03 gold → 04 sync to Timescale → 05 train real models
        │                                    │                      │
        ▼                                    ▼                      ▼
  Delta tables on disk              TimescaleDB (Docker)     MLflow registry (local)
        │                                    │                      │
        │                                    │                      ▼
        │                                    │          local-stack/inference/serve.py
        │                                    │           (FastAPI, loads real models)
        │                                    │                      │
        └──────────────┬─────────────────────┴──────────────────────┘
                        ▼
          local-stack/gateway/  (Apollo Server, real schema.graphql,
                                 calls services/*/src handlers in-process)
                        │
                        ▼
                 nginx :80 → frontend/dashboard-app/dist (React) + /graphql proxy
```

## 1. Prerequisites

| Tool | Why | Check |
|---|---|---|
| Docker + Docker Compose plugin | LocalStack, TimescaleDB | `docker compose version` |
| Java 17 | PySpark | `java -version` |
| Python 3.10+ | pipeline, inference server | `python3 --version` |
| Node.js 18+ | gateway, frontend build | `node --version` |
| nginx | serves the frontend | `nginx -v` |
| AWS CLI | one-time LocalStack init | `aws --version` |
| `psql` (optional) | inspecting Timescale directly | `psql --version` |

On Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install -y openjdk-17-jdk python3-venv nginx awscli postgresql-client
# Docker + Compose plugin: follow docs.docker.com/engine/install/ for your distro
# Node.js 18+: use NodeSource or nvm, not the distro's often-stale package
```

## 2. Get the code and data in place

```bash
sudo mkdir -p /opt/wtb-pdm
sudo chown "$USER" /opt/wtb-pdm
cd /opt/wtb-pdm
git clone <this-repo> wind-turbine-pdm-platform
# The pipeline expects the raw dataset as a SIBLING folder (see
# local-stack/pipeline/common.py's RAW_DATASET_ROOT default):
git clone <raw-dataset-repo> wind-turbine-scada-data-for-early-fault-detection
```
(Or copy the dataset folder over by any means — it just needs to sit next to the
platform repo, or set `RAW_DATASET_ROOT` to wherever it actually is.)

## 3. Bring up LocalStack + TimescaleDB

```bash
cd wind-turbine-pdm-platform/local-stack
./up.sh
```
This starts both containers and runs the one-time init (DynamoDB tables, SNS topic
- see `init/localstack-init.sh`; Timescale's hypertable is created automatically on
first boot via `init/timescale-init.sql`). Re-running `up.sh` is safe.

Verify:
```bash
curl -s http://localhost:4566/_localstack/health | head -c 200
psql "postgresql://wtb_pdm:wtb_pdm_local@localhost:5433/wtb_pdm" -c '\dt'
```

## 4. Python environment + local MLflow server

```bash
cd ../local-stack/pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install mlflow==2.17.2   # already in requirements.txt, called out since the
                              # tracking *server* is a separate long-running process

# In its own terminal (or a systemd unit later):
mlflow server --host 127.0.0.1 --port 5000 \
  --backend-store-uri sqlite:///$(pwd)/../mlflow.db \
  --default-artifact-root file://$(pwd)/../mlruns
```
Leave this running. Open http://localhost:5000 to confirm the MLflow UI loads.

## 5. Run the pipeline

In the `pipeline` venv from step 4, with `MLFLOW_TRACKING_URI` and `TIMESCALE_URL`
exported:
```bash
export MLFLOW_TRACKING_URI=http://localhost:5000
export TIMESCALE_URL="postgresql://wtb_pdm:wtb_pdm_local@localhost:5433/wtb_pdm"
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64   # adjust to your install

./run_pipeline.sh
```
This runs, in order: bronze ingest (all 3 farms) → silver clean (all 3 farms) →
gold features/fault-events/RUL-labels → sync a bounded real slice into Timescale →
train real LightGBM/ETS models per component. Expect this to take a while the
first time (Delta Lake's JAR downloads via Ivy on first run, then it's cached) -
see `local-stack/pipeline/*.py`'s docstrings for exactly what each step does and
why it's scoped the way it is (especially `04_sync_timescale.py`'s comment on why
it doesn't copy the entire dataset into Timescale).

Verify:
```bash
ls data-lake/gold/                       # gold.*_features, fault_events, rul_labels
psql "$TIMESCALE_URL" -c "SELECT count(*) FROM sensor_readings;"
cat data-lake/turbine_id_map.json | head # real (farm, asset_id) -> display id map
# open http://localhost:5000 - registered models per component should now be listed
```

## 6. Start the local inference server

```bash
cd ../inference
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust DATA_LAKE_ROOT if you didn't use /opt/wtb-pdm
export $(grep -v '^#' .env | xargs)
uvicorn serve:app --host 127.0.0.1 --port 8080
```
Verify:
```bash
curl -s http://localhost:8080/health
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"dataframe_records":[{"turbine_id":"A-1","component":"gearbox"}]}'
```
An empty `predictions` array is a legitimate answer if that turbine/component
combination had no trained model (e.g. too few labeled rows — see step 5's
training-skip logging) - it means "no prediction available," not broken.

## 7. Start the local gateway

```bash
cd ../gateway
npm install
cp .env.example .env   # fill in real values (see the file's comments)
npx dotenv -e .env -- npm start
# or: export $(grep -v '^#' .env | xargs) && npm start
```
Verify (see docs/DEVELOPER_SETUP.md-style checks, but against real data now):
```bash
curl -s http://localhost:4000/health
curl -s -X POST http://localhost:4000/graphql -H "Content-Type: application/json" \
  -d '{"query":"query{ activeAlerts { id turbineId component severity } }"}'
```
The scheduler (see `src/scheduler.ts`) starts automatically and, once a minute by
default, walks every real turbine × component with a trained model through
prediction-api → alerting-service — so real alerts should start appearing in
`activeAlerts` within a couple of ticks if any turbine's real data breaches the
default thresholds.

## 8. Build and serve the frontend

```bash
cd ../../frontend/dashboard-app
npm install
VITE_APPSYNC_URL=http://localhost/graphql npm run build
```
(`VITE_APPSYNC_URL` points at nginx's own `/graphql` path, not the gateway's port
directly — nginx proxies it, see `local-stack/nginx/wtb-pdm.conf` — so the browser
only ever talks to port 80.)

```bash
sudo cp ../../local-stack/nginx/wtb-pdm.conf /etc/nginx/sites-available/wtb-pdm
sudo ln -sf /etc/nginx/sites-available/wtb-pdm /etc/nginx/sites-enabled/wtb-pdm
sudo rm -f /etc/nginx/sites-enabled/default   # avoid the stock site competing on :80
sudo nginx -t && sudo systemctl reload nginx
```
Open `http://<your-linux-box>/` — Fleet Overview, Asset Detail, Forecasts/RUL, and
Alerts should now show real locally-computed data. Digital Twin still runs its own
mock ticker (see ADR-0004 — nothing populates a real twin-state table yet, in
either the cloud or local architecture).

## 9. Persistence across reboots (optional but recommended)

```bash
sudo useradd -r -s /usr/sbin/nologin wtb-pdm   # if you don't already have a service user
sudo cp local-stack/systemd/wtb-pdm-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wtb-pdm-inference wtb-pdm-gateway
```
Adjust the `WorkingDirectory`/`ExecStart` paths in both unit files if you didn't
clone to `/opt/wtb-pdm`, and make sure each service's `.env` file (steps 6-7) is in
place before enabling. LocalStack/Timescale are already managed by Docker Compose's
own restart policy; nginx is a normal distro service (`systemctl enable nginx`).

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `run_pipeline.sh` fails with a ClassNotFoundException for Delta | `JAVA_HOME` unset or Ivy couldn't reach Maven Central | Set `JAVA_HOME`; check outbound network access for the first run (JAR download is cached after that) |
| `04_sync_timescale.py` inserts 0 rows for a farm | That farm's silver table has no `train_test == 'prediction'` rows yet, or `02_silver_clean.py` wasn't run for it first | Re-run `01`/`02` for that farm before `04` |
| `serve.py`'s `/invocations` always returns empty `predictions` | No models trained yet for that component (too few labeled rows), or `MLFLOW_TRACKING_URI` mismatch between training and serving | Check the MLflow UI's registered models list; confirm both processes point at the same tracking URI |
| Gateway logs `no turbines found yet` from the scheduler | Ran the gateway before the pipeline | Run `run_pipeline.sh` first — it writes `data-lake/turbine_id_map.json` |
| `activeAlerts` query errors with `ALERTS_TABLE_NAME is not configured` | Gateway `.env` not loaded | Confirm you exported/sourced it before `npm start` |
| Browser shows a CORS error | Frontend built with `VITE_APPSYNC_URL` pointing at the gateway port directly instead of nginx's `/graphql` | Rebuild with `VITE_APPSYNC_URL=http://<host>/graphql` (through nginx) |
| `docker compose up` fails to bind port 5433 or 4566 | Something else already listening | Change the host-side port in `docker-compose.yml` and update every `TIMESCALE_URL`/`AWS_ENDPOINT_URL` reference to match |

## 11. What's real vs. simplified

Don't re-derive this from the code — see [ADR-0004](adr/0004-local-hosting-substitutions.md)'s
table, which is the maintained source of truth for that question.
