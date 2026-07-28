#!/bin/sh
set -eu

export UV_PYTHON=${UV_PYTHON:-$(command -v python)}
export UV_PROJECT_ENVIRONMENT=.venv-lint

exec scripts/dev/env-lock.sh exclusive venv_lint -- \
    uv sync --locked --only-group lint -q
