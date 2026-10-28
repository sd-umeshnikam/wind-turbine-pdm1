#!/bin/sh
# Run the end-to-end suite in the official Playwright image on the compose network.
# Credentials are read from deploy/compose/.env (git-ignored) unless E2E_PASSWORD is set.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
env_file="$here/../../../deploy/compose/.env"
if [ -z "${E2E_PASSWORD:-}" ] && [ -f "$env_file" ]; then
  E2E_USERNAME=$(sed -n 's/^WTPDM_ADMIN_USERNAME=//p' "$env_file")
  E2E_PASSWORD=$(sed -n 's/^WTPDM_ADMIN_PASSWORD=//p' "$env_file")
fi
export E2E_USERNAME="${E2E_USERNAME:-admin}" E2E_PASSWORD="${E2E_PASSWORD:-}"
mount=$here
command -v cygpath >/dev/null 2>&1 && mount=$(cygpath -w "$here")

MSYS_NO_PATHCONV=1 docker run --rm --network "${E2E_NETWORK:-wtpdm_default}" \
  -e E2E_USERNAME -e E2E_PASSWORD -e E2E_BASE_URL="${E2E_BASE_URL:-http://web:8080}" \
  -v "$mount:/e2e" -v wtpdm-e2e-nm:/e2e/node_modules -w /e2e \
  mcr.microsoft.com/playwright:v1.48.2-jammy \
  sh -c "npm install --no-audit --no-fund --silent && npx playwright test $*"
