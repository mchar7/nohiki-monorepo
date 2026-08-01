#!/bin/sh
set -eu

export UV_PYTHON=${UV_PYTHON:-$(command -v python)}

# Any pull request can restore this cache from its base branch, so the shared closure must exclude
# the private Skylos source. The credentialed dead-code sync adds only that source afterward.
case ${1-} in
    python)
        exec scripts/dev/env-lock.sh exclusive venv -- \
            uv sync --locked --all-packages --no-default-groups --group ci \
                --no-install-package skylos -q
        ;;
    full)
        exec scripts/dev/env-lock.sh exclusive venv -- \
            uv sync --locked \
                --package nohiki-monorepo \
                --package ci-checks \
                --package bff-service \
                --package user-auth-service \
                --no-default-groups --group ci --group deadcode \
                --no-install-package skylos -q
        ;;
    *)
        printf 'usage: %s {python|full}\n' "$0" >&2
        exit 2
        ;;
esac
