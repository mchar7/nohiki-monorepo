# syntax=docker/dockerfile:1.16@sha256:e2dd261f92e4b763d789984f6eab84be66ab4f5f08052316d8eb8f173593acf7
FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY backend/libs ./backend/libs/
COPY backend/services ./backend/services/
COPY scripts/ci ./scripts/ci/
COPY scripts/util/health_check ./scripts/util/health_check/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_INSTALLER_METADATA=1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package health-check --no-dev --no-editable

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1
ADD --chmod=0555 --checksum=sha256:ab60ca5f0fd60c1eb81b52909e67060e3ba0bd27e55a8ac147cbc2172ff14212 \
    https://dl.k8s.io/release/v1.34.3/bin/linux/amd64/kubectl /usr/local/bin/kubectl
COPY --from=builder /opt/venv /opt/venv
RUN groupadd --system health && useradd --system --gid health --uid 65532 health
USER 65532:65532
ENV PATH="/opt/venv/bin:$PATH" \
    K8S_LOCAL_MODE=false \
    K8S_NAMESPACE=nohiki
STOPSIGNAL SIGTERM
ENTRYPOINT ["health-check"]
CMD ["inventory", "--target", "k8s"]
