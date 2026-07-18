#!/bin/bash
# Background monitor: restart FAILED or UNASSIGNED connector tasks.

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
CHECK_INTERVAL_SECONDS="${HEALTH_MONITOR_INTERVAL:-30}"

# Exit promptly and cleanly when the entrypoint signals shutdown. The sleep in
# the loop is interruptible, so the trap fires without waiting a full interval.
trap 'echo "[health-monitor] Shutting down"; exit 0' TERM INT

restart_unhealthy_tasks() {
    local connectors_json
    connectors_json=$(curl -sf "${CONNECT_URL}/connectors" 2>/dev/null) || return

    local connectors
    connectors=$(echo "${connectors_json}" | python3 -c "import sys,json; [print(c) for c in json.load(sys.stdin)]" 2>/dev/null) || return

    while IFS= read -r connector; do
        [[ -z "${connector}" ]] && continue

        local status_json
        status_json=$(curl -sf "${CONNECT_URL}/connectors/${connector}/status" 2>/dev/null) || continue

        local connector_state task_states needs_restart
        connector_state=$(echo "${status_json}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('connector', {}).get('state', 'UNKNOWN'))
" 2>/dev/null || echo "UNKNOWN")

        task_states=$(echo "${status_json}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('tasks', []):
    print(t.get('state', 'UNKNOWN'))
" 2>/dev/null || echo "")

        needs_restart=false
        if [[ "${connector_state}" == "FAILED" || "${connector_state}" == "UNASSIGNED" ]]; then
            needs_restart=true
        fi
        while IFS= read -r state; do
            [[ -z "${state}" ]] && continue
            if [[ "${state}" == "FAILED" || "${state}" == "UNASSIGNED" ]]; then
                needs_restart=true
                break
            fi
        done <<< "${task_states}"

        if [[ "${needs_restart}" == "true" ]]; then
            echo "[health-monitor] Restarting unhealthy connector: ${connector} (state=${connector_state})"
            curl -sf -X POST \
                "${CONNECT_URL}/connectors/${connector}/restart?includeTasks=true&onlyFailed=false" \
                > /dev/null 2>&1 || true
        fi
    done <<< "${connectors}"
}

echo "[health-monitor] Starting connector health monitor (interval=${CHECK_INTERVAL_SECONDS}s)"

while true; do
    sleep "${CHECK_INTERVAL_SECONDS}"
    restart_unhealthy_tasks
done
