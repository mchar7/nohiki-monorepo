#!/bin/sh
set -eu

export UV_PYTHON=${UV_PYTHON:-$(command -v python)}

# The same closure as scripts/dev/sync-ci-environment.sh without its `skylos` exclusion, so the
# only work left is fetching and building the private fork itself. Needs GIT_SSH_COMMAND pointing
# at the Skylos deploy key; the caller supplies it.
exec scripts/dev/env-lock.sh exclusive venv -- \
    uv sync --locked --all-packages --no-default-groups --group ci --group deadcode -q
