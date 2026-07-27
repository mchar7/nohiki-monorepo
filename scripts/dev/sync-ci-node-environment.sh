#!/bin/sh
set -eu

exec scripts/dev/env-lock.sh exclusive node_modules -- \
    pnpm --store-dir "$HOME/.cache/pnpm-store" install --frozen-lockfile
