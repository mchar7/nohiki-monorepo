# syntax=docker/dockerfile:1.16@sha256:e2dd261f92e4b763d789984f6eab84be66ab4f5f08052316d8eb8f173593acf7
FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS builder


COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY backend/libs ./backend/libs/
COPY infra/shared/qdrant-init ./infra/shared/qdrant-init/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package qdrant-init --no-dev --no-editable

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

COPY --from=builder /opt/venv /opt/venv


RUN groupadd -r app && useradd -r -g app app
USER app

ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["qdrant-init"]
CMD ["init", "--wait"]
