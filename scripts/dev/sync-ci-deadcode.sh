#!/bin/sh
set -eu

export UV_PYTHON=${UV_PYTHON:-$(command -v python)}

# Match the full cached closure so this credentialed sync adds Skylos without widening the venv.
exec scripts/dev/env-lock.sh exclusive venv -- \
    uv sync --locked \
        --package nohiki-monorepo \
        --package ci-checks \
        --package bff-service \
        --package user-auth-service \
        --no-default-groups --group ci --group deadcode -q
