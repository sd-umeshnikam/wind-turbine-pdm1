# Developer Setup Guide (Windows)

This walks a new developer from a fresh clone to a running dashboard on their own Windows
machine. It covers only the **local, no-AWS-account-needed** pieces (EDA, backend service tests,
frontend dashboard). For deploying to real AWS/Databricks environments, see
[`infra/terraform/README.md`](../infra/terraform/README.md) (Terraform path) or
[`manual-setup/RUNBOOK.md`](manual-setup/RUNBOOK.md) (console path) instead — do that only after
this local setup is working.

**On Linux or macOS?** The same lightweight path works via `./scripts/setup-all.sh` (bash ports of
every script below, same flags). If you want the *full* stack self-hosted — real Spark/Delta
pipeline, real model training, real local serving, no AWS account at all — see
[`LINUX_HOSTING_GUIDE.md`](LINUX_HOSTING_GUIDE.md) instead, this doc's scope is the mock-data path only.

## 1. Prerequisites

| Tool | Minimum version | Check with | Get it from |
|---|---|---|---|
| Python | 3.10+ | `python --version` | https://www.python.org/downloads/ (check "Add to PATH" during install) |
| Node.js (includes npm) | 18 LTS+ | `node --version` / `npm --version` | https://nodejs.org/ |
| Git | any recent | `git --version` | https://git-scm.com/download/win |
| PowerShell | 5.1+ (ships with Windows) | `$PSVersionTable.PSVersion` | already on Windows |

You do **not** need an AWS account, Databricks workspace, or Terraform CLI for local setup — those
are only needed if you go on to actually deploy something (§5 below).

**A note on the repo path.** If you cloned this next to the raw dataset folder under a path
containing spaces (e.g. `...\OneDrive - Some Company\...`), that's fine — every script here quotes
paths correctly — but if you hit a strange "file not found" error, check whether it's a
third-party tool that doesn't handle spaces well, and prefer running these scripts from inside the
repo folder rather than passing long absolute paths around manually.

## 2. Fastest path: run everything with one script

From the repo root, in PowerShell:

```powershell
.\scripts\setup-all.ps1
```

Or double-click **`scripts\setup.bat`** in File Explorer if you'd rather not open a terminal —
it runs the same script with a relaxed execution policy for just that one run (see §6 if you hit
an execution-policy error running the `.ps1` directly instead).

This will, in order:
1. Verify Python/Node/npm are on PATH (fails fast with a clear message if not).
2. Install `pandas`/`matplotlib`/`numpy`/`pyarrow` and run all 5 EDA scripts against the real
   SCADA CSVs in `../wind-turbine-scada-data-for-early-fault-detection/` (sibling folder — make
   sure that folder exists alongside this repo; see §7 if it's somewhere else).
3. `npm install && npm test` for each of the 5 backend Lambda services under `services/`.
4. `npm install && npm run build` for the React dashboard under `frontend/dashboard-app/`.

Expect this to take a few minutes the first time (Farm C's EDA read is the slowest single step,
~2-3 minutes) and be much faster on repeat runs (npm/pip skip already-satisfied installs).

Flags, if you want to skip a piece:
```powershell
.\scripts\setup-all.ps1 -SkipEda          # skip if eda/outputs/ is already populated
.\scripts\setup-all.ps1 -SkipServices     # skip backend service install/test
.\scripts\setup-all.ps1 -SkipFrontend     # skip frontend install/build
```

## 3. Or run each piece individually

**EDA** — regenerates every chart and number in `eda/EDA_REPORT.md` from the real CSVs:
```powershell
.\scripts\setup-eda.ps1
# or, if pandas/matplotlib/numpy/pyarrow are already installed:
.\scripts\setup-eda.ps1 -SkipInstall
```
Outputs land in `eda/outputs/` (JSON/CSV data) and `eda/outputs/charts/` (PNGs). Open
`eda/EDA_REPORT.md` in any Markdown viewer to see the findings with charts embedded.

**Backend services** — install + test all five, or just one:
```powershell
.\scripts\setup-services.ps1
.\scripts\setup-services.ps1 -Only telemetry-api
```
Each service under `services/<name>/` is independent (own `package.json`, own tests) — read
`services/telemetry-api/README.md` first, it's the fully-built reference the other four follow.

**Frontend** — build a production bundle, or run the dev server:
```powershell
.\scripts\setup-frontend.ps1          # production build -> frontend/dashboard-app/dist
.\scripts\setup-frontend.ps1 -Dev     # dev server at http://localhost:5173, Ctrl+C to stop
```
The dashboard runs entirely against realistic mock data matching the real GraphQL schema when
`VITE_APPSYNC_URL` isn't set (see `frontend/dashboard-app/src/api/client.ts`), so `-Dev` gives you
a fully click-through-able app with zero AWS setup. Open http://localhost:5173 once it starts.

## 4. What "done" looks like

After `setup-all.ps1` finishes without errors, you should have:
- `eda/outputs/charts/*.png` — 17 chart images, plus `eda/outputs/*.json`/`*.csv`
- `services/*/dist/` and green test output for all 5 services
- `frontend/dashboard-app/dist/index.html` + built JS/CSS assets

If you then run `.\scripts\setup-frontend.ps1 -Dev` and open http://localhost:5173, you should see
the Fleet Overview page with real numbers (36 turbines, 44 anomaly / 51 normal events) and be able
to navigate to Asset Detail, Digital Twin (a rotating 3D turbine), Forecasts/RUL, and Alerts.

## 5. Going further: deploying to real AWS/Databricks

This local setup does not touch any cloud account. Once you're ready to actually deploy:
- **Read [`docs/architecture/BLUEPRINT.md`](architecture/BLUEPRINT.md) first** — the full
  architecture and why it's built this way.
- **Terraform path**: [`infra/terraform/README.md`](../infra/terraform/README.md) — you'll need
  the Terraform CLI, an AWS account (or three, one per environment — see
  [ADR-0001](adr/0001-cloud-and-iac-choice.md)), and a Databricks account.
- **Manual console path**: [`docs/manual-setup/RUNBOOK.md`](manual-setup/RUNBOOK.md) — click-ops
  equivalent, also useful for the one-time account/SSO bootstrap even if you'll use Terraform for
  everything after.
- **Data platform**: [`data-platform/README.md`](../data-platform/README.md) — deploying the
  Databricks Asset Bundle (`databricks bundle deploy`) once a workspace exists.

## 6. Troubleshooting

**`.\scripts\setup-all.ps1 : File ... cannot be loaded because running scripts is disabled on this
system.`**
Your PowerShell execution policy is blocking local scripts. Either:
- Double-click `scripts\setup.bat` instead (bypasses the policy for that one run only), or
- Run once per session: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then
  re-run the `.ps1` directly in that same terminal (this doesn't change your permanent policy).

**`'python' was not found on PATH` / `'node' was not found on PATH`**
Reinstall from the links in §1 and make sure "Add to PATH" is checked, then close and reopen your
terminal (PATH changes don't apply to already-open terminals).

**EDA script fails to find the raw CSVs**
The EDA scripts expect the raw dataset at
`../wind-turbine-scada-data-for-early-fault-detection/` relative to this repo (see
`eda/scripts/_common.py`). If you cloned this repo somewhere the sibling folder doesn't exist,
either move this repo so it does, or edit the paths in `_common.py` to point at wherever you have
the raw `Wind Farm A/B/C` folders.

**`npm install` is slow or reports vulnerabilities**
The vulnerability warnings from `npm audit` are expected in a fresh scaffold with pinned starter
versions - they don't block install/test/build. Don't run `npm audit fix --force` reflexively;
review what it would change first, especially for the Lambda services where a major-version bump
could change the AWS SDK's API shape.

**Long OneDrive-synced paths / file lock errors**
If this repo lives inside a OneDrive-synced folder (as this one does), OneDrive can occasionally
hold a brief file lock during sync that causes a one-off `npm install`/build error. Re-running the
command almost always succeeds; pausing OneDrive sync during heavy local development avoids it
entirely.

**Port 5173 already in use**
Another Vite dev server (from this repo or another project) is already running. Stop it, or Vite
will automatically try 5174/5175/etc. — check the terminal output for which port it actually
picked.
