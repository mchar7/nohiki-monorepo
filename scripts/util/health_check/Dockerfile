# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY backend/libs ./backend/libs/
COPY scripts/util/health_check ./scripts/util/health_check/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_INSTALLER_METADATA=1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package health-check --no-dev --no-editable

FROM public.ecr.aws/docker/library/python:3.14.6-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6
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
