# Build the console, check it ships no invented data, and serve it with nginx (which also
# proxies /api to the Platform API, same-origin).
FROM node:20.18.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN sh scripts/check-no-fake-data.sh && npx tsc -b && npx eslint src && npx vitest run && npx vite build

FROM nginxinc/nginx-unprivileged:1.27.2-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
