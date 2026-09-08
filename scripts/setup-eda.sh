#!/usr/bin/env bash
# Installs the EDA Python dependencies and runs all five EDA scripts against the
# real SCADA CSVs. Linux port of setup-eda.ps1 - same behavior.
#
# Usage: ./scripts/setup-eda.sh [--skip-install]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SKIP_INSTALL=false
if [ "${1:-}" = "--skip-install" ]; then
  SKIP_INSTALL=true
fi

if [ "$SKIP_INSTALL" = false ]; then
  echo "Installing EDA Python dependencies (pandas, matplotlib, numpy, pyarrow)..."
  python3 -m pip install --quiet pandas matplotlib numpy pyarrow
fi

for script in \
  eda/scripts/01_data_quality.py \
  eda/scripts/02_event_analysis.py \
  eda/scripts/03_sensor_profiling.py \
  eda/scripts/04_degradation_trends.py \
  eda/scripts/05_fleet_summary.py
do
  echo ""
  echo "=== Running $script ==="
  python3 "$script"
done

echo ""
echo "EDA complete. See eda/EDA_REPORT.md and eda/outputs/charts/."
