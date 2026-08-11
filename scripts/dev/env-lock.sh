#!/bin/sh
set -eu

if [ "$#" -lt 4 ] || [ "$3" != "--" ]; then
    printf 'usage: %s <shared|exclusive|gate> <lockname> -- <command> [args...]\n' "$0" >&2
    exit 64
fi

case "$1" in
    shared)
        lock_mode=-s
        gate_lock=0
        ;;
    exclusive)
        lock_mode=-x
        gate_lock=0
        ;;
    gate)
        lock_mode=-x
        gate_lock=1
        ;;
    *)
        printf 'error: lock mode must be shared, exclusive, or gate\n' >&2
        exit 64
        ;;
esac

lock_name=$2
case "$lock_name" in
    ''|.|..|*[!A-Za-z0-9_-]*)
        printf 'error: invalid lock name: %s\n' "$lock_name" >&2
        exit 64
        ;;
esac
if [ "$gate_lock" = 1 ]; then
    marker_name=NOHIKI_GATE_LOCK
else
    marker_name=NOHIKI_ENV_LOCK_${lock_name}
fi
marker_value=
eval "marker_value=\${$marker_name-}"
if [ "$marker_value" = 1 ]; then
    shift 3
    exec "$@"
fi

shift 3
runtime_dir=${XDG_RUNTIME_DIR:-/tmp/nohiki-$(id -u)}
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH='' cd -- "$script_dir/../.." && pwd -P)
umask 077
export "$marker_name=1"

if [ "$gate_lock" = 1 ]; then
    # The pre-push gate is a MACHINE lock, not a checkout lock, and that is deliberate:
    # scripts/dev/test-run.sh sizes the gate body to the whole machine (effective_cpus ->
    # nproc, nix_bounds -> max-jobs x cores up to nproc) and was introduced in the same
    # commit as this lock (ac10541b). Keying by repository, as the env locks below do,
    # would let every worktree claim the whole machine at once. So it stays global.
    #
    # It is a bounded semaphore rather than a mutex because the confinement is
    # per-invocation: `systemd-run --user --scope -p MemoryHigh=50%` creates a TRANSIENT
    # scope per gate, so N concurrent gates soft-cap at N x 50% of MemTotal, not 50%.
    # Two slots is exactly 100% of MemTotal, which is the ceiling; three is 150% and
    # thrashes. CPUWeight/IOWeight are relative weights, so concurrent gates degrade
    # each other rather than starve anything else.
    # ponytail: 2 is derived from that arithmetic, not a tuner. Raise it only if
    # MemoryHigh drops or the gate body stops sizing itself to the full machine.
    slots=${NOHIKI_GATE_SLOTS:-2}
    lock_dir=$runtime_dir/nohiki-gates
    waiter_dir=$lock_dir/waiters
    waiter_file=$waiter_dir/$$
    # 1800s was the original default (ac10541b); 69c06835 raised it to 21600 to stop a
    # watchdog firing, which hid the queue instead of reporting it. A gate that has
    # queued for half an hour is broken, not busy, so the human-scale value is restored.
    timeout=${NOHIKI_GATE_LOCK_TIMEOUT:-1800}
    notice_interval=${NOHIKI_GATE_LOCK_NOTICE_INTERVAL:-60}
    poll_interval=${NOHIKI_GATE_LOCK_POLL_INTERVAL:-5}
    # 400s is the measured cost of a real push with real glob selection (394.98s), not the
    # guide's stale 180s warm figure. That measurement was taken on a loaded workstation and
    # is an upper bound, which is the right side to err on: overstating a wait costs patience,
    # understating it by threefold tells a developer the gate is wedged and makes bypassing
    # it rational, which is the behaviour this lock exists to stop.
    gate_estimate=${NOHIKI_GATE_ESTIMATED_SECONDS:-400}
    case "$slots" in
        ''|*[!0-9]*|0)
            printf 'error: NOHIKI_GATE_SLOTS must be a positive integer\n' >&2
            exit 64
            ;;
    esac
    case "$timeout" in
        ''|*[!0-9]*)
            printf 'error: NOHIKI_GATE_LOCK_TIMEOUT must be a non-negative integer\n' >&2
            exit 64
            ;;
    esac
    case "$notice_interval" in
        ''|*[!0-9]*|0)
            printf 'error: NOHIKI_GATE_LOCK_NOTICE_INTERVAL must be a positive integer\n' >&2
            exit 64
            ;;
    esac
    case "$poll_interval" in
        ''|*[!0-9]*|0)
            printf 'error: NOHIKI_GATE_LOCK_POLL_INTERVAL must be a positive integer\n' >&2
            exit 64
            ;;
    esac
    case "$gate_estimate" in
        ''|*[!0-9]*)
            printf 'error: NOHIKI_GATE_ESTIMATED_SECONDS must be a non-negative integer\n' >&2
            exit 64
            ;;
    esac

    # Slot 1 deliberately keeps the pre-semaphore file names. Worktrees on this machine
    # sit on many different commits, so a rename would leave old single-mutex code and
    # this semaphore contending on nothing at all: an old holder plus both slots is three
    # machine-wide gates, the very case the bound exists to prevent. Sharing slot 1 makes
    # the two interlock, so the worst combined concurrency stays at the bound.
    slot_file() {
        if [ "$1" = 1 ]; then
            printf '%s/pre-push.lock' "$lock_dir"
        else
            printf '%s/pre-push.slot%s.lock' "$lock_dir" "$1"
        fi
    }

    holder_file_for() {
        if [ "$1" = 1 ]; then
            printf '%s/pre-push.holder' "$lock_dir"
        else
            printf '%s/pre-push.slot%s.holder' "$lock_dir" "$1"
        fi
    }

    read_holder() {
        holder=$(cat -- "$(holder_file_for "$1")" 2>/dev/null || printf '')
        holder_pid=${holder%% *}
        holder_pid=${holder_pid#pid=}
    }

    # A holder killed mid-gate loses its flock the moment the kernel closes its fd, so a
    # slot never leaks: see the `9>&-` on the body below, without which an orphaned gate
    # descendant inherits the lock and wedges the slot for as long as it lives. Only the
    # metadata file survives a SIGKILL, and only until it is reaped here by pid liveness.
    # No cleanup is required for correctness.
    clear_stale_holder() {
        read_holder "$1"
        case "$holder_pid" in
            ''|*[!0-9]*)
                return 1
                ;;
        esac
        if kill -0 "$holder_pid" 2>/dev/null; then
            return 1
        fi
        rm -f -- "$(holder_file_for "$1")"
        printf 'pre-push gate: reclaimed stale holder metadata pid=%s\n' "$holder_pid" >&2
        return 0
    }

    reap_stale_holders() {
        rs_i=1
        while [ "$rs_i" -le "$slots" ]; do
            clear_stale_holder "$rs_i" || true
            rs_i=$((rs_i + 1))
        done
    }

    describe_holders() {
        holders=
        dh_i=1
        while [ "$dh_i" -le "$slots" ]; do
            read_holder "$dh_i"
            if [ -n "$holder" ]; then
                if [ -z "$holders" ]; then
                    holders="slot$dh_i $holder"
                else
                    holders="$holders; slot$dh_i $holder"
                fi
            fi
            dh_i=$((dh_i + 1))
        done
        [ -n "$holders" ] || holders='none recorded'
    }

    busy_slots() {
        busy=0
        bs_i=1
        while [ "$bs_i" -le "$slots" ]; do
            if ! (exec 8>"$(slot_file "$bs_i")" && flock -n 8) 2>/dev/null; then
                busy=$((busy + 1))
            fi
            bs_i=$((bs_i + 1))
        done
    }

    queue_depth() {
        depth=0
        for waiter in "$waiter_dir"/*; do
            [ -e "$waiter" ] || continue
            waiter_pid=${waiter##*/}
            case "$waiter_pid" in
                ''|*[!0-9]*)
                    rm -f -- "$waiter"
                    continue
                    ;;
            esac
            if kill -0 "$waiter_pid" 2>/dev/null; then
                depth=$((depth + 1))
            else
                rm -f -- "$waiter"
            fi
        done
    }

    # 0 acquired, 1 every slot busy, 2 the slot files themselves are unusable.
    acquire_slot() {
        aq_i=1
        while [ "$aq_i" -le "$slots" ]; do
            exec 9>"$(slot_file "$aq_i")" || return 2
            flock -n 9 && { slot=$aq_i; return 0; }
            aq_status=$?
            [ "$aq_status" -le 1 ] || return 2
            aq_i=$((aq_i + 1))
        done
        return 1
    }

    fail_unusable() {
        printf 'error: pre-push gate slot files under %s are unusable; refusing to run unserialised\n' "$lock_dir" >&2
        exit 70
    }

    mkdir -p -- "$lock_dir" "$waiter_dir"
    reap_stale_holders
    slot=
    acquire_status=0
    acquire_slot || acquire_status=$?
    [ "$acquire_status" -le 1 ] || fail_unusable

    queued_seconds=0
    estimate=0
    if [ "$acquire_status" = 1 ]; then
        : >"$waiter_file"
        trap 'rm -f -- "$waiter_file"' EXIT
        queue_depth
        estimate=$((((depth + slots - 1) / slots) * gate_estimate))
        describe_holders
        printf 'pre-push gate queued: all %s slots busy; queue depth %s including you; estimated wait ~%ss (gate ~%ss / %s slots); giving up after %ss\n' \
            "$slots" "$depth" "$estimate" "$gate_estimate" "$slots" "$timeout" >&2
        printf 'pre-push gate holders: %s\n' "$holders" >&2
        since_notice=0
        while :; do
            if [ "$queued_seconds" -ge "$timeout" ]; then
                describe_holders
                printf 'error: pre-push gate timed out after %ss with all %s slots busy; a gate queued this long is broken, not busy. Holders: %s\n' \
                    "$queued_seconds" "$slots" "$holders" >&2
                exit 75
            fi
            sleep "$poll_interval"
            queued_seconds=$((queued_seconds + poll_interval))
            since_notice=$((since_notice + poll_interval))
            # Checked immediately before the acquire: a wiped XDG_RUNTIME_DIR would
            # otherwise let this shell recreate the slot files and run unserialised.
            if [ ! -d "$lock_dir" ]; then
                printf 'error: pre-push gate lock directory %s disappeared while queued; refusing to run unserialised\n' "$lock_dir" >&2
                exit 70
            fi
            reap_stale_holders
            acquire_status=0
            acquire_slot || acquire_status=$?
            [ "$acquire_status" -le 1 ] || fail_unusable
            if [ "$acquire_status" = 0 ]; then
                break
            fi
            if [ "$since_notice" -ge "$notice_interval" ]; then
                since_notice=0
                queue_depth
                describe_holders
                printf 'pre-push gate still queued after %ss of %ss; queue depth %s; holders: %s\n' \
                    "$queued_seconds" "$timeout" "$depth" "$holders" >&2
            fi
        done
        rm -f -- "$waiter_file"
    fi

    holder_file=$(holder_file_for "$slot")
    printf 'pid=%s worktree=%s\n' "$$" "$repo_root" >"$holder_file"
    trap 'rm -f -- "$holder_file" "$waiter_file"' EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    busy_slots
    if [ "$queued_seconds" = 0 ]; then
        printf 'pre-push gate: took slot %s of %s with no wait; %s of %s slots now busy\n' \
            "$slot" "$slots" "$busy" "$slots" >&2
    else
        printf 'pre-push gate: took slot %s of %s after %ss queued (estimated ~%ss); %s of %s slots now busy\n' \
            "$slot" "$slots" "$queued_seconds" "$estimate" "$busy" "$slots" >&2
    fi
    # 9>&- keeps the slot bound to THIS shell's lifetime. Without it the body and every
    # descendant inherit the locked descriptor, so killing the holder frees nothing and a
    # single orphan wedges a slot for every worktree on the machine.
    "$@" 9>&-
    exit $?
fi

if ! command -v sha256sum >/dev/null 2>&1; then
    printf 'error: sha256sum is required to identify the repository checkout\n' >&2
    exit 69
fi
repo_hash=$(printf '%s' "$repo_root" | sha256sum | cut -d ' ' -f 1)
if [ -z "$repo_hash" ]; then
    printf 'error: unable to identify the repository checkout\n' >&2
    exit 69
fi
lock_dir=$runtime_dir/nohiki-env-locks/$repo_hash
mkdir -p -- "$lock_dir"
lock_file=$lock_dir/$lock_name.lock
exec 9>"$lock_file"
flock "$lock_mode" 9
exec "$@"
