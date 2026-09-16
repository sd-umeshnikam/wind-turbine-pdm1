# Windows Hosting Guide — Full Stack, Including the Data Pipeline (with ngrok)

This is the Windows counterpart to [`LINUX_HOSTING_GUIDE.md`](LINUX_HOSTING_GUIDE.md): running
the **entire** platform on a single Windows box — the medallion pipeline (real Spark + Delta
Lake), real model training (LightGBM + statsmodels), a local model-serving API, a local GraphQL
gateway substituting AppSync, TimescaleDB substituting Timestream, LocalStack substituting
DynamoDB/SNS/S3, and the React dashboard served by nginx — then tunneling it to a public URL with
**ngrok** so it's reachable off-box without any router/firewall changes.

Every script this guide runs is the **same `.sh` script the Linux guide runs, unmodified** — no
PowerShell port exists or is needed, because Git for Windows ships a real `bash` (Git Bash) that
runs them as-is. The only genuinely Windows-specific pieces are the ones with no bash equivalent:
the Java/Python/Node installs themselves, nginx's Windows binary, and running things as background
services (Windows has no systemd).

**This version assumes Docker is not installed.** The Linux guide's LocalStack + TimescaleDB
containers (`local-stack/docker-compose.yml`) are the only pieces that genuinely need Docker;
§3 below replaces them with native, installer-based equivalents — a real PostgreSQL install
(no container) for the Timescale substitute, and DynamoDB Local's standalone `.jar` (no container)
for the DynamoDB substitute. Everything else in this guide (the pipeline scripts, inference
server, gateway, nginx, ngrok) is identical either way. If you install Docker Desktop later,
you can switch to `local-stack/docker-compose.yml` + `./up.sh` as in the Linux guide instead —
they're interchangeable, not something you need to migrate off of once running.

**Read [ADR-0004](adr/0004-local-hosting-substitutions.md) first** — the one-page table of what's
a genuine open-source substitute, what's a documented simplification, and what's explicitly out of
scope. This guide is the *how*; that ADR is the *why*.

**If you just want the dashboard running against realistic mock data** (no pipeline, no
AWS-shaped services at all), you don't need any of this — see
[`docs/DEVELOPER_SETUP.md`](DEVELOPER_SETUP.md) instead, it's a five-minute path.

**Stuck on the Ubuntu install instead?** This guide exists as a working alternative so you're not
blocked while that gets sorted — if you paste the actual error you're hitting on the Ubuntu box,
that's usually faster to fix directly than switching platforms.

## 0. Architecture at a glance

```
Public https://<your-id>.ngrok-free.app
        │  (ngrok agent tunnel, no router/firewall changes needed)
        ▼
Raw SCADA CSVs (sibling folder)
        │
        ▼
local-stack/pipeline/  (real PySpark + Delta Lake, run_pipeline.sh)
  01 bronze → 02 silver → 03 gold → 04 sync to Timescale → 05 train real models
        │                                    │                      │
        ▼                                    ▼                      ▼
  Delta tables on disk         PostgreSQL (native service,    MLflow registry (local)
                                   no Docker — see §3)
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
                        ▲
                        │  ngrok tunnels exactly this port — nothing downstream changes
```

## 1. Prerequisites

| Tool | Why | Check |
|---|---|---|
| **Git for Windows** | Gives you **Git Bash**, the shell every command below runs in — it's what lets the repo's existing `.sh` scripts run unmodified | `bash --version` (from Git Bash) |
| PostgreSQL 14+ for Windows (postgresql.org, native EDB installer — **not** Docker) | Timescale substitute for telemetry-api (§3) | `psql --version` |
| Temurin/OpenJDK 17 | PySpark, **and** runs DynamoDB Local's `.jar` (§3) | `java -version` |
| Python 3.10–3.12 (python.org, check "Add to PATH") | pipeline, inference server | `python --version` |
| Node.js 18 LTS+ | gateway, frontend build | `node --version` |
| nginx for Windows (zip from nginx.org, no installer) | serves the frontend | `nginx -v` |
| AWS CLI | creates DynamoDB Local's tables (§3) | `aws --version` |
| **ngrok** (ngrok.com/download) | public tunnel to your box | `ngrok version` |
| NSSM (nssm.cc, optional, §10 only) | wraps exes as Windows services (systemd's replacement) | `nssm version` |

No Docker Desktop needed anywhere in this guide — §3 covers the native substitutes.

Run every command below **in a Git Bash terminal**, not PowerShell or cmd — that's what makes the
`.sh` scripts work as-is. Docker Desktop, Java, Python, Node, and nginx all put their executables
on the same Windows `PATH`, which Git Bash also sees, so nothing needs a separate Windows-only
install path.

**Pick a short, space-free clone path** (e.g. `D:\wtb-pdm`, not somewhere under
`OneDrive - Company Name\...`). Spaces and OneDrive sync locks are a known source of flaky
`npm install`/Spark/JVM errors (see `DEVELOPER_SETUP.md`'s troubleshooting) — for a long-running
hosted setup it's worth avoiding that class of problem entirely rather than working around it
later.

**Budget at least ~30GB free on whichever drive you pick.** The raw dataset alone is ~18.5GB, the
platform repo plus its Python/Node virtual environments and `node_modules` add another ~8GB, and
things like MLflow's run artifacts and the pipeline's Delta tables (§3–§5) grow further from
there. Check free space first (`Get-PSDrive -PSProvider FileSystem` in PowerShell, or just look at
drive properties in Explorer) — `D:\wtb-pdm` is only an example path in this guide, not a
requirement; use whichever drive actually has the room (`D:\wtb-pdm`, etc.), keeping the same
relative folder structure. If you only discover this after `C:` fills up mid-setup, see §13 for
how to move everything to another drive without starting over.

## 2. Get the code and data in place

In Git Bash:
```bash
mkdir -p /d/wtb-pdm
cd /d/wtb-pdm
git clone <this-repo> wind-turbine-pdm-platform
# The pipeline expects the raw dataset as a SIBLING folder (see
# local-stack/pipeline/common.py's RAW_DATASET_ROOT default):
git clone <raw-dataset-repo> wind-turbine-scada-data-for-early-fault-detection
```
(Or copy the dataset folder over by any means — it just needs to sit next to the platform repo, or
set `RAW_DATASET_ROOT` to wherever it actually is. Git Bash's `/d/wtb-pdm` and Windows'
`D:\wtb-pdm` are the same folder — Windows-native tools like Docker Desktop and `python.exe` will
happily use whichever path form you give them.)

## 3. Bring up the Timescale + DynamoDB substitutes (no Docker)

This replaces the Linux guide's `docker compose up` + `./up.sh` with two native installs — a real
PostgreSQL server and DynamoDB Local's standalone `.jar`. Neither is a container; both are genuine
processes running directly on Windows.

**3a. PostgreSQL (Timescale substitute)**

Install PostgreSQL for Windows (the EDB installer from postgresql.org), keeping the default port
5432 and remembering the `postgres` superuser password you set. The installer registers PostgreSQL
as a Windows service that starts automatically — no `systemctl`/Docker restart-policy equivalent
needed (see §10).

**The installer does not reliably put `psql`/`createdb` on `PATH`** — a fresh Git Bash window will
say `createdb: command not found` even right after a successful install. Point at the version you
installed explicitly (adjust `17` if yours differs — check with
`ls "/c/Program Files/PostgreSQL/"`):
```bash
export PATH="/c/Program Files/PostgreSQL/17/bin:$PATH"
```
Add that same line to `~/.bashrc` (or add the folder to your Windows PATH via System Properties →
Environment Variables) if you don't want to repeat it in every new Git Bash window.

Then, still in Git Bash — each `psql -U postgres`/`createdb -U postgres` call below prompts for
the `postgres` superuser password interactively (there's no way around that prompt, and no way to
script around it without hardcoding the password in a file, which isn't worth it for a local dev
DB — just type it each time, or `export PGPASSWORD='...'` for the session if you'd rather not):
```bash
createdb -U postgres wtb_pdm
psql -U postgres -d wtb_pdm -c "CREATE USER wtb_pdm WITH PASSWORD 'wtb_pdm_local';"
psql -U postgres -d wtb_pdm -c "GRANT ALL PRIVILEGES ON DATABASE wtb_pdm TO wtb_pdm;"
psql -U postgres -d wtb_pdm <<'SQL'
CREATE TABLE IF NOT EXISTS sensor_readings (
    turbine_id TEXT NOT NULL,
    time TIMESTAMPTZ NOT NULL,
    sensor TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    unit TEXT
);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_turbine_time
    ON sensor_readings (turbine_id, time DESC);
ALTER TABLE sensor_readings OWNER TO wtb_pdm;
SQL
```
**That `ALTER TABLE ... OWNER TO wtb_pdm` line matters — don't skip it.** The table above is created
as the `postgres` superuser, and the earlier `GRANT ALL PRIVILEGES ON DATABASE` only grants
database-level privileges (connect/create) — it does **not** cascade to table-level privileges
(SELECT/INSERT/TRUNCATE) on a table owned by a different user. Without this line,
`04_sync_timescale.py` fails with `psycopg2.errors.InsufficientPrivilege: permission denied for
table sensor_readings` the moment it tries to `TRUNCATE` the table, and `telemetry-api` would hit
the same wall reading it. (The Linux/Docker guide never hits this because there, `wtb_pdm` *is*
the Postgres superuser inside that container from the start — this only bites the native,
no-Docker install here where `postgres` and `wtb_pdm` are genuinely separate roles.) If you already
created the table without this line, fix it after the fact with:
```bash
psql -U postgres -d wtb_pdm -c "ALTER TABLE sensor_readings OWNER TO wtb_pdm;"
```

This is the same `sensor_readings` schema as `local-stack/init/timescale-init.sql`, minus
`CREATE EXTENSION timescaledb` and `create_hypertable(...)`. That's a deliberate, safe drop: both
`services/telemetry-api/src/postgresClient.ts` and `local-stack/pipeline/04_sync_timescale.py`
only ever run plain `SELECT`/`INSERT`/`TRUNCATE` against this table — no Timescale-specific SQL
(`time_bucket`, etc.) anywhere in the app. The hypertable exists purely as a performance
optimization at real production scale; a plain Postgres table is functionally identical for this
single-box local setup.

Note the connection string is now on port **5432** (Postgres' default), not the Linux guide's
5433 (that was only to dodge a port clash with an existing host Postgres, which doesn't apply
here since you're installing it fresh):
```
postgresql://wtb_pdm:wtb_pdm_local@localhost:5432/wtb_pdm
```

**3b. DynamoDB Local (LocalStack's DynamoDB piece, minus S3/SNS)**

```bash
mkdir -p /d/wtb-pdm/dynamodb-local && cd /d/wtb-pdm/dynamodb-local
curl -o dynamodb_local.zip https://s3.us-west-2.amazonaws.com/dynamodb-local/dynamodb_local_latest.zip
unzip dynamodb_local.zip

# In its own Git Bash window (leave running):
java -Djava.library.path=./DynamoDBLocal_lib -jar DynamoDBLocal.jar -sharedDb -port 8000
```
This is AWS's own official standalone DynamoDB emulator — genuinely the same DynamoDB API
LocalStack's DynamoDB piece wraps, just without the container. Create the same three tables
`local-stack/init/localstack-init.sh` would have created, against port 8000 instead of 4566:
```bash
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
for table in wtb-pdm-local-assets wtb-pdm-local-alerts wtb-pdm-local-config; do
  aws --endpoint-url=http://localhost:8000 dynamodb create-table \
    --table-name "$table" \
    --attribute-definitions AttributeName=id,AttributeType=S \
    --key-schema AttributeName=id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
done
```

**What's genuinely missing without Docker: SNS and S3.**
- **S3** was already optional — the pipeline defaults to writing Delta tables to local disk
  (`local-stack/pipeline/common.py`'s `DATA_LAKE_ROOT`); the init script only created S3 buckets
  "if you route pipeline storage through S3 instead," which nothing here does. Skip it, no
  substitute needed.
- **SNS** has no standalone no-Docker emulator. `alerting-service`'s write path
  (`services/alerting-service/src/handler.ts`) calls `putAlert(alert)` (DynamoDB — works fine
  above) and *then* `publishAlert(alert)` (SNS — will throw, since nothing is listening at
  whatever `ALERTS_TOPIC_ARN`/endpoint you configure). Because `putAlert` already succeeded by
  the time `publishAlert` throws, **the alert is already durably written to DynamoDB** — which is
  the only thing `Query.activeAlerts` (what the dashboard actually reads) depends on. The
  practical effect is a logged `UpstreamError` in the gateway's scheduler output on every new
  breach, not a missing alert on the dashboard. Leave `ALERTS_TOPIC_ARN` at its `.env.example`
  placeholder value and treat that log line as expected noise, same spirit as the other
  documented simplifications in [ADR-0004](adr/0004-local-hosting-substitutions.md). If you want
  it silenced instead of just harmless, say so and I can add a tiny local SNS stub — not included
  by default so this guide doesn't fork the app's code beyond what Docker's absence strictly
  requires.

Verify:
```bash
psql "postgresql://wtb_pdm:wtb_pdm_local@localhost:5432/wtb_pdm" -c '\dt'
aws --endpoint-url=http://localhost:8000 dynamodb list-tables
```

## 4. Python environment + local MLflow server

**Note the `cd` below is absolute, not relative to wherever §3b left you** (`dynamodb-local/` is a
sibling of the platform repo, not inside it — adjust the path if you didn't clone to `D:\wtb-pdm`):

**Use Python 3.10–3.12, not whatever the newest installed Python is.** `requirements.txt` pins
`pandas==2.2.3`/`numpy==1.26.4`, which have no prebuilt wheels for very new interpreters (3.13+) —
`pip install` then tries to compile them from source and fails with a Meson/`vswhere.exe not found`
error unless you have a full MSVC toolchain installed. If `python --version` reports 3.13 or newer,
install 3.11 alongside it (`winget install --id Python.Python.3.11 -e`) and create the venv with
`py -3.11 -m venv .venv` instead of the plain `python -m venv .venv` below.
```bash
cd /d/wtb-pdm/wind-turbine-pdm-platform/local-stack/pipeline
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt

# In its own Git Bash window (leave running):
mlflow server --host 127.0.0.1 --port 5000 \
  --backend-store-uri "sqlite:///$(pwd -W)/../mlflow.db" \
  --default-artifact-root "file:///$(pwd -W)/../mlruns"
```
Note `source .venv/Scripts/activate`, not `.venv/bin/activate` — Windows' `venv` module still
writes a POSIX-compatible `Scripts/activate` alongside the `.bat`/`.ps1` ones, specifically so
Git Bash can use it.

**Use `pwd -W`, not plain `pwd`, in any path handed to a native Windows executable like `mlflow`.**
Plain `pwd` in Git Bash prints the MSYS-style path (`/d/wtb-pdm/...`), which native (non-MSYS)
programs don't translate — `mlflow` reads `/c/...` literally as `C:\c\...`, a folder that doesn't
exist, and fails with `sqlite3.OperationalError: unable to open database file` while endlessly
retrying. `pwd -W` prints the Windows-native form (`D:/wtb-pdm/...`) instead, which both `mlflow`
and SQLite understand correctly.

Open http://localhost:5000 to confirm the MLflow UI loads.

## 5. Run the pipeline

In the `pipeline` venv from step 4:

**`JAVA_HOME` must be a Windows-native path, not Git Bash's `/c/...` form.** PySpark launches
`java.exe` directly via `$JAVA_HOME/bin/java` as a subprocess — Windows' process launcher can't
resolve `/c/Program Files/...` (no drive letter) and fails with
`The system cannot find the path specified`, the same class of bug as §4's `pwd` vs. `pwd -W`.
Use the drive-letter form with forward slashes (adjust the version folder name to match what you
installed — check with `ls "/c/Program Files/Eclipse Adoptium/"`).

**Spark also needs `winutils.exe` + `hadoop.dll` — Windows-only, and not part of the `pyspark` pip
package.** Spark bundles Hadoop 3.3.4's client libraries (check yours with
`ls .venv/Lib/site-packages/pyspark/jars/ | grep hadoop-client`), and Hadoop's Windows shell layer
needs a native `winutils.exe` for file-permission emulation that only Linux/Mac skip — without it
you'll hit `HADOOP_HOME and hadoop.home.dir are unset` (see
[wiki.apache.org/hadoop/WindowsProblems](https://wiki.apache.org/hadoop/WindowsProblems), which is
also what the error message itself points to). There's no official Apache build of this for
Windows; the community-standard source nearly every PySpark-on-Windows guide uses is
[cdarlint/winutils](https://github.com/cdarlint/winutils) on GitHub — grab the closest available
3.3.x folder (3.3.4 itself isn't hosted there, but 3.3.5/3.3.6 are binary-compatible for this
shim's purposes):
```bash
mkdir -p /c/hadoop/bin
curl -sSL -o /c/hadoop/bin/winutils.exe \
  https://raw.githubusercontent.com/cdarlint/winutils/master/hadoop-3.3.5/bin/winutils.exe
curl -sSL -o /c/hadoop/bin/hadoop.dll \
  https://raw.githubusercontent.com/cdarlint/winutils/master/hadoop-3.3.5/bin/hadoop.dll
```
This is a third-party binary, not an Apache release — if you'd rather not run an unverified `.exe`,
source it yourself from wherever you trust and just point `HADOOP_HOME` at it below.

```bash
export MLFLOW_TRACKING_URI=http://localhost:5000
export TIMESCALE_URL="postgresql://wtb_pdm:wtb_pdm_local@localhost:5432/wtb_pdm"
export JAVA_HOME="C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot"   # adjust to your install
export HADOOP_HOME="C:/hadoop"
export PATH="/c/hadoop/bin:$PATH"

./run_pipeline.sh
```
Same script, same steps as the Linux guide: bronze ingest → silver clean → gold
features/fault-events/RUL-labels → sync a bounded real slice into Timescale → train real
LightGBM/ETS models per component. First run downloads Delta Lake's JAR via Ivy (cached under
`~/.ivy2` after that, same as Linux).

**If Spark/Ivy chokes on the space in `Program Files`**, use the legacy short-path form instead:
```bash
export JAVA_HOME="C:/PROGRA~1/Eclipse Adoptium/jdk-17.0.20.101-hotspot"
```
or just install the JDK to a no-space path like `C:\jdk-17` to sidestep the issue entirely.

**`run_pipeline.sh` can silently stop after one step, on Windows only, because of `set -euo
pipefail` combined with how Spark tears itself down.** Each script's `finally: spark.stop()`
sometimes has Spark force-kill its own process tree via `taskkill /F /T` during Windows cleanup
(you'll see `SUCCESS: The process with PID ... has been terminated` lines after a step's normal
output) — and that kill can end the `python ...` process itself in a way bash's strict mode treats
as a failure, aborting the whole script before the next farm/step ever runs, even though the step
that "failed" already wrote its output correctly. Check `ls ../data-lake/bronze/` (or `silver/`,
`gold/`) against what you expect after each run; if you're missing steps, just run the rest of
`run_pipeline.sh`'s lines manually, one at a time, in the same terminal (env vars are still
exported):
```bash
python 01_bronze_ingest.py --farm B
python 01_bronze_ingest.py --farm C
python 02_silver_clean.py --farm A
python 02_silver_clean.py --farm B
python 02_silver_clean.py --farm C
python 03_gold_features.py
python 04_sync_timescale.py
python 05_train_models.py
```
Each returning you to a `$` prompt after its own "complete"/summary line (rather than a Python
traceback) means that step genuinely succeeded — the taskkill noise afterward is cosmetic.

Verify (note `data-lake/` is a sibling of `pipeline/`, one level up — not inside it):
```bash
ls ../data-lake/gold/                    # gold.*_features, fault_events, rul_labels
psql "postgresql://wtb_pdm:wtb_pdm_local@localhost:5432/wtb_pdm" -c "SELECT count(*) FROM sensor_readings;"
cat ../data-lake/turbine_id_map.json | head # real (farm, asset_id) -> display id map
# open http://localhost:5000 - registered models per component should now be listed
```

## 6. Start the local inference server

```bash
cd ../inference
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env   # adjust DATA_LAKE_ROOT if you didn't clone to D:\wtb-pdm
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
An empty `predictions` array is a legitimate answer (no trained model for that turbine/component
yet) — same as the Linux guide.

## 7. Start the local gateway

```bash
cd ../gateway
npm install
cp .env.example .env
```
Edit `.env` for the no-Docker substitutes from §3 before starting:
```
TIMESCALE_URL=postgresql://wtb_pdm:wtb_pdm_local@localhost:5432/wtb_pdm
AWS_ENDPOINT_URL=http://localhost:8000
# ALERTS_TOPIC_ARN can stay at its placeholder value — see §3's note on SNS being
# the one piece with no no-Docker substitute; publishAlert will log-and-throw but
# the alert itself is already durably written to DynamoDB by then.
```
```bash
npx dotenv -e .env -- npm start
```
Verify:
```bash
curl -s http://localhost:4000/health
curl -s -X POST http://localhost:4000/graphql -H "Content-Type: application/json" \
  -d '{"query":"query{ activeAlerts { id turbineId component severity } }"}'
```
The scheduler (`src/scheduler.ts`) starts automatically and walks every real turbine × component
with a trained model through prediction-api → alerting-service once a minute by default.

## 8. Build and serve the frontend

```bash
cd ../../frontend/dashboard-app
npm install
VITE_APPSYNC_URL=http://localhost/graphql npm run build
```

nginx for Windows has no `sites-available`/`sites-enabled` convention and no `systemctl` — extract
the nginx zip (e.g. to `C:\nginx`) and either edit `C:\nginx\conf\nginx.conf` directly or copy
`local-stack/nginx/wtb-pdm.conf`'s `server { ... }` block into it (inside the existing `http {}`
block, removing the stock default `server {}` so it doesn't compete on `:80`). Two Windows-specific
edits to that block:
- **Use forward slashes in `root`**, even though it's a Windows path:
  `root D:/wtb-pdm/wind-turbine-pdm-platform/frontend/dashboard-app/dist;`
- Nothing else changes — the `/graphql` and `/health` proxy blocks are identical to Linux.

Start / reload nginx (from `C:\nginx`, in Git Bash or cmd):
```bash
./nginx.exe -t          # validate config
./nginx.exe             # start (or: start nginx  from cmd, to background it)
./nginx.exe -s reload   # after any config change
```
Open `http://localhost/` — Fleet Overview, Asset Detail, Forecasts/RUL, and Alerts should show
real locally-computed data. Digital Twin still runs its own mock ticker (see ADR-0004 — nothing
populates a real twin-state table yet, in either the cloud or local architecture).

## 9. Expose it to the internet with ngrok

This is the piece the Linux guide doesn't have. `ngrok` tunnels nginx's port 80 to a public HTTPS
URL — no router port-forwarding, no firewall rule changes, no static IP needed. Useful for
demoing off-box, sharing a link with teammates, or testing from a phone.

1. Sign up free at ngrok.com and copy your authtoken from the dashboard.
2. Install ngrok (download the zip, or `winget install ngrok.ngrok` / `choco install ngrok`).
3. One-time setup: `ngrok config add-authtoken <your-token>`
4. With nginx already running on port 80 (step 8): `ngrok http 80`

ngrok prints a forwarding line like:
```
Forwarding    https://ab12-203-0-113-5.ngrok-free.app -> http://localhost:80
```
Open that URL from any device — it's the exact same nginx-served dashboard and `/graphql` proxy
that `http://localhost/` serves locally.

**Things worth knowing before you rely on this:**

- **The free-tier URL changes every time you restart the tunnel.** For a stable link, claim
  ngrok's one free static domain from the dashboard, then run
  `ngrok http --url=your-chosen-name.ngrok-free.app 80` instead of the bare `ngrok http 80`.
- **This puts your dev box on the open internet with no login** (Cognito is skipped locally per
  ADR-0004 — nothing else is guarding it). Don't leave a tunnel open unattended. For casual
  protection while testing: `ngrok http --basic-auth="user:pass" 80` requires that login before
  ngrok forwards any request at all.
- **WebSocket subscriptions work through the tunnel unmodified** — ngrok proxies WS upgrades
  transparently, so the `/graphql` subscription path nginx already proxies to the gateway
  (`wtb-pdm.conf`'s `Upgrade`/`Connection` headers) keeps working with zero extra config.
- **No rebuild needed for the tunnel to work.** The frontend was built with
  `VITE_APPSYNC_URL=http://localhost/graphql` — a *relative-to-origin* proxy path, not an absolute
  host. Whatever origin the browser loaded the page from (your ngrok URL included) is the origin
  it calls `/graphql` on, and nginx on your box still proxies that to the gateway. Same-origin the
  whole way through, so there's nothing to reconfigure and no CORS headers to add.
- Closing the `ngrok http 80` terminal drops the tunnel. See §10 to keep it running persistently.

## 10. Persistence across reboots (optional)

Windows has no systemd, so the Linux guide's unit files don't translate directly — use
[NSSM](https://nssm.cc/) instead, which wraps any executable as a real Windows service (auto-start,
auto-restart on crash).

```bash
# Inference server
nssm install wtb-pdm-inference "D:\wtb-pdm\wind-turbine-pdm-platform\local-stack\inference\.venv\Scripts\uvicorn.exe" "serve:app --host 127.0.0.1 --port 8080"
nssm set wtb-pdm-inference AppDirectory "D:\wtb-pdm\wind-turbine-pdm-platform\local-stack\inference"
nssm start wtb-pdm-inference

# Gateway
nssm install wtb-pdm-gateway "C:\Program Files\nodejs\npx.cmd" "tsx src/server.ts"
nssm set wtb-pdm-gateway AppDirectory "D:\wtb-pdm\wind-turbine-pdm-platform\local-stack\gateway"
nssm start wtb-pdm-gateway

# nginx
nssm install wtb-pdm-nginx "C:\nginx\nginx.exe"
nssm set wtb-pdm-nginx AppDirectory "C:\nginx"
nssm start wtb-pdm-nginx
```
For each service, load its `.env` file's variables via `nssm set <service> AppEnvironmentExtra`
(one `VAR=value` per line) instead of the Linux guide's `EnvironmentFile=`.

**ngrok as a service is optional and lower-stakes to automate than the rest** — for a personal demo
box it's reasonable to do the same:
```bash
nssm install wtb-pdm-ngrok "C:\path\to\ngrok.exe" "http --url=your-chosen-name.ngrok-free.app 80"
nssm start wtb-pdm-ngrok
```
but for anything meant to stay up long-term and unattended, an always-on tunnel to an unauthenticated
dev box is more exposure than most setups want — prefer adding `--basic-auth` (§9) at minimum.

PostgreSQL needs no extra step here — the EDB installer already registered it as an
auto-starting Windows service (check via `services.msc`, name starts with `postgresql-x64-`).
DynamoDB Local does, since it's just a bare `java -jar` process:
```bash
nssm install wtb-pdm-dynamodb "C:\Program Files\Eclipse Adoptium\jdk-17.x.x-hotspot\bin\java.exe" "-Djava.library.path=./DynamoDBLocal_lib -jar DynamoDBLocal.jar -sharedDb -port 8000"
nssm set wtb-pdm-dynamodb AppDirectory "D:\wtb-pdm\dynamodb-local"
nssm start wtb-pdm-dynamodb
```

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `./run_pipeline.sh: $'\r': command not found` or `bad interpreter` | Repo checked out with CRLF line endings on the `.sh` files | `git config core.autocrlf input` then re-clone, or run `dos2unix local-stack/**/*.sh` once |
| `run_pipeline.sh` fails with a ClassNotFoundException for Delta | `JAVA_HOME` unset/wrong, or the space in `Program Files` confuses the Spark launcher | Set `JAVA_HOME` correctly; if the space is the issue, use the `/c/PROGRA~1/...` short-path form or a no-space JDK install path |
| `nginx: [emerg] ... CreateFile() failed` on start | `root`/path directives in the config use backslashes | nginx on Windows requires forward slashes even for Windows paths (`D:/wtb-pdm/...`) |
| `04_sync_timescale.py` inserts 0 rows for a farm | That farm's silver table has no `train_test == 'prediction'` rows yet | Re-run `01`/`02` for that farm before `04` |
| `serve.py`'s `/invocations` always returns empty `predictions` | No model trained yet for that component, or `MLFLOW_TRACKING_URI` mismatch | Check the MLflow UI's registered models; confirm training and serving point at the same tracking URI |
| Gateway logs `no turbines found yet` | Gateway started before the pipeline ran | Run `run_pipeline.sh` first — it writes `data-lake/turbine_id_map.json` |
| ngrok forwards to a blank page / 502 | nginx isn't actually up on port 80 yet | Confirm `curl http://localhost/` works locally *before* starting the tunnel |
| ngrok URL loads the dashboard but every GraphQL call fails | Frontend was rebuilt with an absolute `VITE_APPSYNC_URL` (e.g. the gateway's `:4000` or the ngrok URL itself) instead of the relative `http://localhost/graphql` | Rebuild with `VITE_APPSYNC_URL=http://localhost/graphql` — nginx's same-origin proxy is what makes the ngrok tunnel work with zero extra config |
| ngrok session immediately errors `ERR_NGROK_...` about auth | Authtoken not configured, or a free-tier session limit hit | Re-run `ngrok config add-authtoken <token>`; free tier allows one agent session at a time |
| `createdb: command not found` / `psql: command not found` | PostgreSQL's installer didn't add its `bin` folder to `PATH` | `export PATH="/c/Program Files/PostgreSQL/17/bin:$PATH"` (adjust the version number) — see §3a |
| `psql: error: connection to server ... failed` | PostgreSQL's Windows service isn't running, or the port/password doesn't match what you set at install | Check `services.msc` for `postgresql-x64-...` and start it; re-run the `createdb`/`CREATE USER` steps in §3a if the user/db were never created |
| `psycopg2.errors.InsufficientPrivilege: permission denied for table sensor_readings` (in `04_sync_timescale.py`, or from `telemetry-api`) | `sensor_readings` is owned by `postgres`, not `wtb_pdm` — a database-level `GRANT` doesn't cascade to table-level privileges | `psql -U postgres -d wtb_pdm -c "ALTER TABLE sensor_readings OWNER TO wtb_pdm;"` — see §3a |
| `aws dynamodb create-table` hangs or refuses the connection on port 8000 | The `java -jar DynamoDBLocal.jar` window was closed, or Java isn't on PATH | Reopen a Git Bash window in `dynamodb-local/` and re-run the `java -jar` command from §3b; confirm with `java -version` |
| Gateway/scheduler logs `Failed to write or publish the alert` repeatedly | Expected — see §3's note on SNS having no no-Docker substitute | Harmless: the alert was already written to DynamoDB before this error fires, so `activeAlerts`/the dashboard is unaffected. Only matters if you want clean logs, not for functionality |
| `01_bronze_ingest.py`/`02_silver_clean.py` appears to hang right after Spark starts, near-zero CPU, for minutes | A hidden Windows Defender Firewall prompt (often behind other windows or just flashing in the taskbar) is waiting for you to allow `java.exe` network access for Spark's local driver | Find and click "Allow access" on the firewall dialog; the JVM resumes immediately once answered |
| `java.lang.OutOfMemoryError: Java heap space` while writing a bronze/silver/gold step, usually on a bigger farm (B/C) after a smaller one (A) succeeded | Spark's local-mode driver defaults to a 1GB heap, unset anywhere in `common.py` | `export PYSPARK_SUBMIT_ARGS="--driver-memory 2g pyspark-shell"` and `export SPARK_MASTER="local[2]"` before re-running that farm's step (bump to `3g`+ if it still OOMs and you have the free RAM — check with `Get-CimInstance Win32_OperatingSystem` in PowerShell first); delete that farm's partial output directory first if it has no `_delta_log`, since a crashed write leaves orphaned parquet files behind |

## 12. What's real vs. simplified

Don't re-derive this from the code — see [ADR-0004](adr/0004-local-hosting-substitutions.md)'s
table, which is the maintained source of truth for that question. Nothing about adding ngrok
changes what's real vs. simplified underneath it — it's purely a public entry point in front of
the same nginx `:80` the Linux guide serves locally.

## 13. Moving everything to a different drive (if you run out of space)

The raw dataset (§2) plus the repo's virtual environments and `node_modules` easily total 25GB+
(§1), and it's easy to only notice a drive is full partway through §5's pipeline run, mid-farm.
Everything under your chosen root (this guide uses `D:\wtb-pdm`) can be moved to any other drive
with room (e.g. `E:\wtb-pdm`, if `D:` itself later fills up) without starting over — Delta tables
store relative paths in their transaction logs, and `common.py` derives every path
(`RAW_DATASET_ROOT`, `DATA_LAKE_ROOT`) from the script's own file location at runtime rather than a
hardcoded string, so a same-structure move just works. Two things do need care, though.

**Stop anything holding an open file handle under the folder first**, or the copy can fail or
silently skip locked files:
- PostgreSQL needs no action — its data directory lives under its own install path (e.g.
  `C:\Program Files\PostgreSQL\17\`), never under your cloned repo, so it's unaffected either way.
- DynamoDB Local (§3b) and the MLflow server (§4) both need stopping — find them by command line
  first, since multiple `java.exe`/`python.exe`/`mlflow.exe` processes can be running at once and
  killing the wrong one is easy to do by PID alone:
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name = 'java.exe' OR Name = 'mlflow.exe'" |
    Select-Object ProcessId, CommandLine
  Stop-Process -Id <the matching PID(s)> -Force
  ```

**Move with `robocopy /MOVE`, not Explorer drag-and-drop or plain `mv`** — it's far more reliable
for tens of thousands of files across drives and reports a clean success/failure count:
```powershell
robocopy "D:\wtb-pdm\wind-turbine-pdm-platform" "E:\wtb-pdm\wind-turbine-pdm-platform" /E /MOVE /MT:8 /R:2 /W:2
robocopy "D:\wtb-pdm\dynamodb-local" "E:\wtb-pdm\dynamodb-local" /E /MOVE /MT:8 /R:2 /W:2
robocopy "D:\wtb-pdm\wind-turbine-scada-data-for-early-fault-detection" "E:\wtb-pdm\wind-turbine-scada-data-for-early-fault-detection" /E /MOVE /MT:8 /R:2 /W:2
```
(Substitute whichever source/destination drives are actually yours — `D:`/`E:` here are just this
guide's own before/after example.) Check the summary block each prints: `FAILED : 0` across all
three is success. **Robocopy's exit code is not a normal 0-means-success code** — 1 specifically
means "files were copied successfully," not an error; only codes ≥8 indicate real failures. Don't
treat a non-zero exit code alone as failure — read the `FAILED` count in the summary instead. The
old root folder (`D:\wtb-pdm` in this example) is left behind empty after `/MOVE`; it's harmless to
leave as-is.

**Any venv created before the move needs a workaround, not a fresh install.** Windows venv
console-script wrappers (`pip.exe`, `mlflow.exe`, and every other `Scripts\*.exe`) *and* the
`activate` script itself embed the venv's absolute path at creation time — after the move, running
`pip.exe`/`mlflow.exe` directly does nothing (silently), and `source .venv/Scripts/activate` sets
`VIRTUAL_ENV` to the old, now-nonexistent path, making `python`/`pip` resolve to the wrong
interpreter entirely instead of erroring loudly. The venv's `python.exe` itself is unaffected —
work around the wrappers by calling it directly instead of relying on `activate`:
```bash
cd /e/wtb-pdm/wind-turbine-pdm-platform/local-stack/pipeline
alias python=".venv/Scripts/python.exe"   # instead of `source .venv/Scripts/activate`
python -m pip list                        # instead of `pip list`
python -m mlflow server --host 127.0.0.1 --port 5000 \
  --backend-store-uri "sqlite:///$(pwd -W)/../mlflow.db" \
  --default-artifact-root "file:///$(pwd -W)/../mlruns"   # instead of bare `mlflow server ...`
```
This only affects venvs that existed *before* the move (the pipeline one, if you'd already reached
§4). Any venv you create *after* moving (inference in §6, if you haven't gotten there yet) bakes in
the correct new path from the start and needs no workaround. Recreating the affected venv from
scratch (delete `.venv`, redo §4's `py -3.11 -m venv .venv` + `pip install`) also fixes it
permanently, at the cost of re-downloading/rebuilding everything in `requirements.txt` — the
`alias`/`python -m` workaround is faster and just as correct if you'd rather not wait.

Every path you export in later sections (`JAVA_HOME`, `HADOOP_HOME`, `TIMESCALE_URL`,
`MLFLOW_TRACKING_URI`, etc.) is a plain value, not something stored in a file relative to the old
location — just re-export the same values in a fresh terminal `cd`'d to the new path, same as any
new terminal window already needs per §4–§5.
