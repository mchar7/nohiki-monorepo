# syntax=docker/dockerfile:1.16
FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY backend/libs ./backend/libs/
COPY backend/services/job-storage-service ./backend/services/job-storage-service/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_INSTALLER_METADATA=1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package job-storage-service --no-dev --no-editable

RUN find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -path "*/dist-info/RECORD" -delete 2>/dev/null; \
    find /opt/venv -path "*/dist-info/LICENSE*" -delete 2>/dev/null; \
    find /opt/venv -name "*.pdb" -delete 2>/dev/null; \
    find /opt/venv -name "*.so" -exec strip --strip-unneeded {} + 2>/dev/null; \
    find /opt/venv -name "*.pyi" -delete 2>/dev/null; \
    true

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/services/job-storage-service/src/job_storage_service ./job_storage_service
COPY backend/services/job-storage-service/alembic.ini .
COPY backend/services/job-storage-service/alembic ./alembic

RUN groupadd -r app && useradd -r -g app app && chown -R app:app /app
USER app

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["uvicorn", "job_storage_service.main:app", "--host", "0.0.0.0", "--port", "8000"]