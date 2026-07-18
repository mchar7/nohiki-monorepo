#!/bin/bash
# Kafka Connect entrypoint: register connectors, then run a health monitor.
set -euo pipefail

SCRIPTS_DIR="$(dirname "$0")"

# Start the vendored Debezium entrypoint in the background. /docker-entrypoint.sh
# is an image-internal path owned by the Debezium Connect base image; it lives
# only inside this image adapter and is not a host assumption.
/docker-entrypoint.sh start &
CONNECT_PID=$!
MONITOR_PID=""

shutdown() {
    trap - TERM INT
    if [[ -n "${MONITOR_PID}" ]] && kill -0 "${MONITOR_PID}" 2>/dev/null; then
        kill -TERM "${MONITOR_PID}" 2>/dev/null || true
    fi
    if kill -0 "${CONNECT_PID}" 2>/dev/null; then
        kill -TERM "${CONNECT_PID}" 2>/dev/null || true
    fi
    wait "${MONITOR_PID}" 2>/dev/null || true
    wait "${CONNECT_PID}" 2>/dev/null || true
}
trap shutdown TERM INT

# Wait for Connect to be ready (API responding)
echo "Waiting for Kafka Connect REST API..."
until curl -sf http://localhost:8083/ > /dev/null 2>&1; do
    if ! kill -0 "${CONNECT_PID}" 2>/dev/null; then
        wait "${CONNECT_PID}"
        exit $?
    fi
    sleep 5
done
echo "Kafka Connect API is ready"

# Wait for worker to join the connect cluster and stabilize
echo "Waiting for worker to stabilize..."
sleep 10

# Register connectors via REST API (idempotent - safe to run on every restart).
# Startup registers only; destructive legacy cleanup is the explicit
# `register-connectors.sh migrate-legacy` command and never runs here.
"${SCRIPTS_DIR}/register-connectors.sh" register

# Start background health monitor - auto-restarts any FAILED/UNASSIGNED tasks
"${SCRIPTS_DIR}/connector-health-monitor.sh" &
MONITOR_PID=$!

# Wait for Connect process
set +e
wait "${CONNECT_PID}"
status=$?
set -e
if [[ -n "${MONITOR_PID}" ]] && kill -0 "${MONITOR_PID}" 2>/dev/null; then
    kill -TERM "${MONITOR_PID}" 2>/dev/null || true
fi
wait "${MONITOR_PID}" 2>/dev/null || true
exit "${status}"
