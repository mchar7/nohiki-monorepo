# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS builder


COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY backend/libs ./backend/libs/
COPY infra/shared/qdrant-init ./infra/shared/qdrant-init/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package qdrant-init --no-dev --no-editable

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

COPY --from=builder /opt/venv /opt/venv


RUN groupadd -r app && useradd -r -g app app
USER app

ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["qdrant-init"]
CMD ["init", "--wait"]
