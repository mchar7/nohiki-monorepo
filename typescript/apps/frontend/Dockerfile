# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
FROM docker.io/library/node:26.5.1-alpine@sha256:221f4d1edb150c0ddf3c61c1f053cd3a59ee0fe42f54cb687a7db24e97da6c46 AS build

WORKDIR /workspace

RUN npm install --global pnpm@11.17.0

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY typescript ./typescript
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
RUN pnpm --filter nohiki-frontend build

FROM docker.io/library/caddy:2.11.4-alpine@sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a AS runtime

COPY --chmod=0444 typescript/apps/frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /workspace/typescript/apps/frontend/dist /srv

USER 999:999
EXPOSE 8080
STOPSIGNAL SIGTERM
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
