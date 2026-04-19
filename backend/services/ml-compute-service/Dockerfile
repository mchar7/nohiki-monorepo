# syntax=docker/dockerfile:1.16
# Accelerator builder selection. Global ARG so it is usable in the `FROM` below:
# sync-cpu (default, +cpu torch) or sync-gpu (+cu130 torch) for the production GPU image.
ARG ML_COMPUTE_BUILDER=sync-cpu
FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS builder-base

COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv

WORKDIR /workspace

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_INSTALLER_METADATA=1
ENV UV_NO_CACHE=1
# py-rust-stemmers lacks cp314 wheels, needs Rust to build from source
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends cargo gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY backend/libs ./backend/libs/
COPY backend/services/ml-compute-service ./backend/services/ml-compute-service/

# CPU-only dependency resolution (default): torch resolves to the +cpu build,
# pulling no NVIDIA/triton wheels. This is the image local/staging deploy.
FROM builder-base AS sync-cpu
RUN uv sync --package ml-compute-service --no-dev --no-editable

# CUDA 13.0 dependency resolution: the `cuda` extra routes torch to the +cu130
# build and pulls the NVIDIA runtime wheels. Used by the production GPU image.
FROM builder-base AS sync-gpu
RUN uv sync --package ml-compute-service --no-dev --no-editable --extra cuda

# Select the resolved environment. Defaults to CPU (byte-identical to the prior
# build); the production GPU image sets --build-arg ML_COMPUTE_BUILDER=sync-gpu.
# BuildKit only builds the selected sync stage, so CPU images never pull CUDA.
FROM ${ML_COMPUTE_BUILDER} AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -path "*/dist-info/RECORD" -delete 2>/dev/null; \
    find /opt/venv -path "*/dist-info/LICENSE*" -delete 2>/dev/null; \
    find /opt/venv -name "*.pdb" -delete 2>/dev/null; \
    TORCH_DIR=$(find /opt/venv -type d -name torch -path "*/site-packages/torch" | head -1); \
    cp "${TORCH_DIR:?}/bin/torch_shm_manager" /tmp/torch_shm_manager; \
    rm -rf "${TORCH_DIR:?}/include" "${TORCH_DIR:?}/bin" "${TORCH_DIR:?}/share"; \
    mkdir -p "${TORCH_DIR:?}/bin"; \
    mv /tmp/torch_shm_manager "${TORCH_DIR:?}/bin/torch_shm_manager"; \
    SITE=$(dirname "$TORCH_DIR"); \
    rm -rf "${SITE:?}"/setuptools "${SITE:?}"/setuptools-*.dist-info \
           "${SITE:?}/pyarrow/include" "${SITE:?}/pyarrow/src"; \
    find /opt/venv -name "*.pyi" -delete 2>/dev/null; \
    true

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/services/ml-compute-service/src/ml_compute_service ./ml_compute_service

RUN groupadd -r app && useradd -r -g app -d /home/app app && \
    mkdir -p /home/app/.cache/huggingface /home/app/.cache/fastembed /home/app/.cache/models && \
    chown -R app:app /app /home/app

USER app

ENV PATH="/opt/venv/bin:$PATH"
ENV HF_HOME="/home/app/.cache/huggingface"
ENV FASTEMBED_CACHE_PATH="/home/app/.cache/fastembed"

EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["uvicorn", "ml_compute_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
