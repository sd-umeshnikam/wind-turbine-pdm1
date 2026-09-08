#!/usr/bin/env bash
# Brings up LocalStack + TimescaleDB and runs the one-time init (DynamoDB tables,
# SNS topic, Timescale hypertable - the SQL init runs automatically via
# docker-entrypoint-initdb.d on first start).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose up -d

echo "Waiting for containers to be healthy..."
for _ in $(seq 1 30); do
  status=$(docker compose ps --format json 2>/dev/null | grep -c '"Health":"healthy"' || true)
  if [ "$status" -ge 2 ]; then break; fi
  sleep 2
done

bash init/localstack-init.sh

echo ""
echo "Up. Timescale: postgresql://wtb_pdm:wtb_pdm_local@localhost:5433/wtb_pdm"
echo "LocalStack:    http://localhost:4566"
