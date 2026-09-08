#!/usr/bin/env bash
# Runs the full local medallion pipeline end to end: bronze -> silver -> gold ->
# sync to Timescale -> train real models. Re-run any time the raw CSVs change;
# every step overwrites its output, so this is idempotent.
#
# Prerequisites: Java 17 on PATH, `pip install -r requirements.txt` done, the
# TimescaleDB container up (docker compose, see ../docker-compose.yml) and
# TIMESCALE_URL exported, the local MLflow server running and MLFLOW_TRACKING_URI
# exported. See docs/LINUX_HOSTING_GUIDE.md for the full sequence.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== Bronze ingest ==="
for farm in A B C; do
  python 01_bronze_ingest.py --farm "$farm"
done

echo "=== Silver clean ==="
for farm in A B C; do
  python 02_silver_clean.py --farm "$farm"
done

echo "=== Gold features, fault events, RUL labels ==="
python 03_gold_features.py

echo "=== Sync a bounded slice into Timescale (telemetry-api's local backend) ==="
python 04_sync_timescale.py

echo "=== Train real local models (fault classifier, RUL, trend forecaster) ==="
python 05_train_models.py

echo "=== Pipeline complete ==="
