#!/bin/sh
set -eu

effective_cpus() {
    if [ -n "${NOHIKI_TEST_NPROC:-}" ]; then
        available=$NOHIKI_TEST_NPROC
    elif command -v nproc >/dev/null 2>&1; then
        available=$(nproc)
    else
        available=$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1')
    fi
    case "$available" in
        ''|*[!0-9]*|0)
            available=1
            ;;
    esac

    cgroup_root=${NOHIKI_TEST_CGROUP_ROOT:-/sys/fs/cgroup}
    if [ -n "${NOHIKI_TEST_CGROUP_PATH:-}" ]; then
        cgroup_path=$NOHIKI_TEST_CGROUP_PATH
    else
        cgroup_path=
        while IFS=: read -r hierarchy _ path; do
            if [ "$hierarchy" = 0 ]; then
                cgroup_path=$path
                break
            fi
        done </proc/self/cgroup
    fi

    current=$cgroup_root$cgroup_path
    while [ -n "$current" ] && [ "${current#"$cgroup_root"}" != "$current" ]; do
        if [ -r "$current/cpu.max" ]; then
            read -r quota period <"$current/cpu.max"
            case "$quota:$period" in
                max:*|*[!0-9:]*|*:0)
                    ;;
                *)
                    quota_cpus=$((quota / period))
                    [ "$quota_cpus" -ge 1 ] || quota_cpus=1
                    if [ "$quota_cpus" -lt "$available" ]; then
                        available=$quota_cpus
                    fi
                    ;;
            esac
        fi
        [ "$current" = "$cgroup_root" ] && break
        current=${current%/*}
    done
    printf '%s\n' "$available"
}

nix_bounds() {
    cpus=$1
    best_jobs=1
    best_cores=1
    best_total=1
    jobs=1
    while [ "$jobs" -le 4 ] && [ "$jobs" -le "$cpus" ]; do
        cores=$((cpus / jobs))
        [ "$cores" -le 5 ] || cores=5
        total=$((jobs * cores))
        if [ "$total" -ge "$best_total" ]; then
            best_jobs=$jobs
            best_cores=$cores
            best_total=$total
        fi
        jobs=$((jobs + 1))
    done
    printf '%s %s\n' "$best_jobs" "$best_cores"
}

run_with_oom_priority() {
    # Prefer forkful test descendants as OOM victims so memory pressure spares the calling harness.
    # 900 clears the harness's 200 with ceiling headroom and is inherited by every worker.
    if command -v choom >/dev/null 2>&1 && choom -n 900 -- true >/dev/null 2>&1; then
        exec choom -n 900 -- "$@"
    fi
    exec "$@"
}

case "${1:-}" in
    gate)
        shift
        if [ "${1:-}" != "--" ] || [ "$#" -lt 2 ]; then
            printf 'usage: %s gate -- <command> [args...]\n' "$0" >&2
            exit 64
        fi
        shift
        if command -v systemd-run >/dev/null 2>&1; then
            scope_marker=$(mktemp "${TMPDIR:-/tmp}/nohiki-gate-scope.XXXXXX")
            rm -f -- "$scope_marker"
            if NOHIKI_GATE_SCOPE_MARKER=$scope_marker systemd-run --user --scope --quiet --collect --expand-environment=no \
                -p CPUWeight=50 -p IOWeight=50 -p MemoryHigh=50% \
                "$0" gate-body -- "$@"; then
                rm -f -- "$scope_marker"
                exit 0
            else
                scope_status=$?
                if [ -e "$scope_marker" ]; then
                    rm -f -- "$scope_marker"
                    exit "$scope_status"
                fi
            fi
        fi
        printf 'pre-push gate: systemd user scope unavailable; using plain execution\n' >&2
        exec "$0" gate-body -- "$@"
        ;;
    gate-body)
        shift
        if [ "${1:-}" != "--" ] || [ "$#" -lt 2 ]; then
            printf 'usage: %s gate-body -- <command> [args...]\n' "$0" >&2
            exit 64
        fi
        shift
        if [ -n "${NOHIKI_GATE_SCOPE_MARKER:-}" ]; then
            : >"$NOHIKI_GATE_SCOPE_MARKER"
        fi
        gate_cpus=$(effective_cpus)
        bounds=$(nix_bounds "$gate_cpus")
        export NOHIKI_GATE_CPUS=$gate_cpus
        export NOHIKI_NIX_MAX_JOBS=${bounds% *}
        export NOHIKI_NIX_CORES=${bounds#* }
        NIX_CONFIG="${NIX_CONFIG:-}
max-jobs = $NOHIKI_NIX_MAX_JOBS
cores = $NOHIKI_NIX_CORES"
        export NIX_CONFIG
        exec "$@"
        ;;
    workers)
        effective_cpus
        exit 0
        ;;
esac

run_with_oom_priority "$@"
