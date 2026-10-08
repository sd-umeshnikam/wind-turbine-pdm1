# server.ts imports the Lambda handlers straight from services/*/src (see its own
# comment) - each service directory needs its own `npm install` (own
# node_modules), not just the gateway's. Those directories are bind-mounted, not
# copied into the image (see docker-compose.yml), so install happens at
# container start via start.sh, not here - an image-time install would just get
# masked by the bind mount's (node_modules-less) host directory at runtime.
FROM node:20-slim

WORKDIR /workspace/wind-turbine-pdm-platform/local-stack/gateway
