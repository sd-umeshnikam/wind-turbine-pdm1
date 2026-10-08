#!/usr/bin/env bash
# server.ts imports Lambda handlers straight from services/*/src, each with its
# own node_modules (see Dockerfile's comment on why install can't happen at
# image build time here). Re-running `npm install` on every start is cheap once
# node_modules already exists (npm no-ops with nothing to do).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

for dir in . ../../services/telemetry-api ../../services/prediction-api ../../services/alerting-service; do
  echo "=== npm install: $dir ==="
  npm install --prefix "$dir"
done

echo "=== Starting gateway ==="
npm start
