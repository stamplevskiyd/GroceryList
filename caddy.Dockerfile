# syntax=docker/dockerfile:1
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
RUN APP_PUBLIC_URL=https://localhost caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null
COPY --from=frontend /app/dist /srv
