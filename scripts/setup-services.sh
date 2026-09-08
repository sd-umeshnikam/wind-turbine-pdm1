#!/usr/bin/env bash
# Installs dependencies and runs the test suite for each backend Lambda service
# under services/. Linux port of setup-services.ps1 - same behavior.
#
# Usage: ./scripts/setup-services.sh [service-name]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ALL_SERVICES=(telemetry-api prediction-api alerting-service digital-twin-service ingestion-trigger)

if [ -n "${1:-}" ]; then
  SERVICES=("$1")
else
  SERVICES=("${ALL_SERVICES[@]}")
fi

for service in "${SERVICES[@]}"; do
  path="services/$service"
  if [ ! -d "$path" ]; then
    echo "Unknown service '$service' (expected one of: ${ALL_SERVICES[*]})" >&2
    exit 1
  fi

  echo ""
  echo "=== $service ==="
  (cd "$path" && npm install && npm test)
done

echo ""
echo "All backend services installed and tested."
