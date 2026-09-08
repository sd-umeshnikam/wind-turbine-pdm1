#!/usr/bin/env bash
# Stops LocalStack + TimescaleDB. Pass -v to also delete their volumes (wipes all
# local data - DynamoDB tables, SNS topic, Timescale rows - and starts clean next
# time `up.sh` runs).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ "${1:-}" = "-v" ]; then
  docker compose down -v
else
  docker compose down
fi
