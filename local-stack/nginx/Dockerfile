# Multi-stage: Vite bakes VITE_APPSYNC_URL into the built JS at build time (not
# runtime-configurable), so the frontend has to actually be built here rather
# than bind-mounted+served live like the other services in this compose file.
# nginx then only ever serves the static output - no Node needed in the final
# image.
#
# Build context is the platform repo root (../.. from docker-compose.yml, see
# its build.context), not this directory - the frontend source lives outside
# local-stack/, and Docker can't COPY from outside the build context.
FROM node:20-slim AS build

WORKDIR /app
COPY frontend/dashboard-app/package.json frontend/dashboard-app/package-lock.json ./
RUN npm install

COPY frontend/dashboard-app/ ./
# Same origin as nginx itself - see docker.conf's comment on why. The browser
# runs on the host, so "localhost" here means the host's mapped port, not
# anything inside the Docker network.
ENV VITE_APPSYNC_URL=http://localhost/graphql
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY local-stack/nginx/docker.conf /etc/nginx/conf.d/default.conf
