#!/bin/sh
set -eu

export UV_PYTHON=${UV_PYTHON:-$(command -v python)}

exec scripts/dev/env-lock.sh exclusive venv -- \
    uv sync --locked --all-packages --no-default-groups --group ci --group deadcode -q
