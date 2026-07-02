# syntax=docker/dockerfile:1.16
FROM docker.io/library/node:26.5.0-alpine@sha256:c9f02360d2bc66e709b300214395588acd2d3603f600db8141117e67c0faf4ff AS build

WORKDIR /workspace

RUN npm install --global pnpm@11.13.1

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY typescript ./typescript
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
RUN pnpm --filter nohiki-frontend build

FROM docker.io/library/caddy:2.10.2-alpine@sha256:d8c17a862962def15cde69863a3a463f25a2664942eafd7bdbf050e9c3116b83 AS runtime

COPY typescript/apps/frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /workspace/typescript/apps/frontend/dist /srv

USER 999:999
EXPOSE 8080
STOPSIGNAL SIGTERM
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
