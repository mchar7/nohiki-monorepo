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
    lock_dir=$runtime_dir/nohiki-gates
    lock_file=$lock_dir/pre-push.lock
    holder_file=$lock_dir/pre-push.holder
    timeout=${NOHIKI_GATE_LOCK_TIMEOUT:-1800}
    case "$timeout" in
        ''|*[!0-9]*)
            printf 'error: NOHIKI_GATE_LOCK_TIMEOUT must be a non-negative integer\n' >&2
            exit 64
            ;;
    esac
    mkdir -p -- "$lock_dir"
    exec 9>"$lock_file"
    if ! flock -n 9; then
        holder=$(cat -- "$holder_file" 2>/dev/null || printf 'pid=unknown worktree=unknown')
        printf 'pre-push gate queued: holder %s\n' "$holder" >&2
        if ! flock -w "$timeout" 9; then
            printf 'error: timed out after %ss waiting for the pre-push gate held by %s\n' "$timeout" "$holder" >&2
            exit 75
        fi
    fi
    printf 'pid=%s worktree=%s\n' "$$" "$repo_root" >"$holder_file"
    trap 'rm -f -- "$holder_file"' EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    "$@"
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
