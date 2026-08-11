# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
FROM docker.io/library/golang:1.26.5-bookworm@sha256:f5b1ea492ad3e465d57c79dcea9393c2f0710ca2dce326078691851fd4307737 AS supercronic-builder
ARG SUPERCRONIC_VERSION=v0.2.47
RUN test "$(go env GOVERSION)" = "go1.26.5" && \
    CGO_ENABLED=0 go install "github.com/aptible/supercronic@${SUPERCRONIC_VERSION}"

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b0c4ec81396588a94b99052caf2f786e6e92e03111991d3d40c68762ee48d2ab AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY backend/libs ./backend/libs/
COPY backend/jobs/sys-tick-job ./backend/jobs/sys-tick-job/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_INSTALLER_METADATA=1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package sys-tick-job --no-dev --no-editable

RUN find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -path "*/dist-info/RECORD" -delete 2>/dev/null; \
    find /opt/venv -path "*/dist-info/LICENSE*" -delete 2>/dev/null; \
    find /opt/venv -name "*.pdb" -delete 2>/dev/null; \
    find /opt/venv -name "*.so" -exec strip --strip-unneeded {} + 2>/dev/null; \
    find /opt/venv -name "*.pyi" -delete 2>/dev/null; \
    true

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b0c4ec81396588a94b99052caf2f786e6e92e03111991d3d40c68762ee48d2ab

COPY --from=builder /opt/venv /opt/venv

COPY --from=supercronic-builder /go/bin/supercronic /usr/local/bin/supercronic
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
USER app

ENV PATH="/opt/venv/bin:$PATH"

STOPSIGNAL SIGTERM
CMD ["python", "-m", "sys_tick_job.publish_schedule_tick"]
