#!/usr/bin/env bash
# One-shot local setup for the Wind Turbine PdM platform scaffold on Linux.
# Linux port of setup-all.ps1 - same behavior: checks prerequisites, then runs
# EDA, backend service install+test, and frontend build. Does NOT touch AWS/
# Databricks, and does NOT set up the local-stack/ full pipeline+gateway - see
# docs/LINUX_HOSTING_GUIDE.md for that.
#
# Usage: ./scripts/setup-all.sh [--skip-eda] [--skip-services] [--skip-frontend]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKIP_EDA=false
SKIP_SERVICES=false
SKIP_FRONTEND=false
for arg in "$@"; do
  case "$arg" in
    --skip-eda) SKIP_EDA=true ;;
    --skip-services) SKIP_SERVICES=true ;;
    --skip-frontend) SKIP_FRONTEND=true ;;
    *) echo "Unknown flag: $arg" >&2; exit 1 ;;
  esac
done

assert_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "'$1' was not found on PATH. $2" >&2
    exit 1
  fi
  echo "Found $1: $(command -v "$1")"
}

echo "=== Checking prerequisites ==="
assert_command python3 "Install via your distro's package manager (e.g. apt install python3)."
assert_command node "Install Node.js 18+ (nvm or NodeSource, not a stale distro package)."
assert_command npm "npm ships with Node.js - reinstall Node.js if this is missing."

if [ "$SKIP_EDA" = false ]; then
  echo ""
  echo "=== EDA ==="
  "$SCRIPT_DIR/setup-eda.sh"
else
  echo ""
  echo "Skipping EDA (--skip-eda)"
fi

if [ "$SKIP_SERVICES" = false ]; then
  echo ""
  echo "=== Backend services ==="
  "$SCRIPT_DIR/setup-services.sh"
else
  echo ""
  echo "Skipping backend services (--skip-services)"
fi

if [ "$SKIP_FRONTEND" = false ]; then
  echo ""
  echo "=== Frontend ==="
  "$SCRIPT_DIR/setup-frontend.sh"
else
  echo ""
  echo "Skipping frontend (--skip-frontend)"
fi

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  - Read docs/DEVELOPER_SETUP.md for the full walkthrough"
echo "  - For the full pipeline + local hosting, read docs/LINUX_HOSTING_GUIDE.md"
echo "  - cd frontend/dashboard-app && npm run dev   (to browse the dashboard against mock data)"
