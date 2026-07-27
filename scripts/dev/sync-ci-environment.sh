#!/bin/sh
set -eu

export UV_PYTHON=${UV_PYTHON:-$(command -v python)}

# Everything the dead-code lane needs except the one distribution that is private. `skylos` alone
# resolves from a private fork over SSH; its 32 public dependencies resolve from PyPI, so they
# belong in the shared closure and only the fork's own source is withheld. That matters because
# this closure is what the ci-ready cache entry stores, and GitHub lets a pull-request run restore
# its base branch's entries with no credential at all. scripts/dev/sync-ci-deadcode.sh drops the
# exclusion in the one lane that holds the deploy key.
exec scripts/dev/env-lock.sh exclusive venv -- \
    uv sync --locked --all-packages --no-default-groups --group ci --group deadcode \
        --no-install-package skylos -q
