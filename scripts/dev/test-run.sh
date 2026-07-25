#!/bin/sh
set -eu

# Prefer forkful test descendants as OOM victims so memory pressure spares the calling harness.
# 900 clears the harness's 200 with ceiling headroom and is inherited by every worker.
if command -v choom >/dev/null 2>&1 && choom -n 900 -- true >/dev/null 2>&1; then
    exec choom -n 900 -- "$@"
fi
exec "$@"
