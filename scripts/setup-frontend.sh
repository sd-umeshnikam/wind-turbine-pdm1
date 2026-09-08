#!/usr/bin/env bash
# Installs dependencies and builds (or runs the dev server for) the React
# dashboard at frontend/dashboard-app. Linux port of setup-frontend.ps1.
#
# Usage: ./scripts/setup-frontend.sh [--dev]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../frontend/dashboard-app"

echo "Installing frontend dependencies..."
npm install

if [ "${1:-}" = "--dev" ]; then
  echo "Starting dev server (Ctrl+C to stop) - runs against mock data unless VITE_APPSYNC_URL is set..."
  npm run dev
else
  echo "Building production bundle..."
  npm run build
  echo ""
  echo "Build output: frontend/dashboard-app/dist"
fi
