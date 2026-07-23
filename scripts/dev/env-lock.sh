#!/bin/sh
set -eu

if [ "$#" -lt 4 ] || [ "$3" != "--" ]; then
    printf 'usage: %s <shared|exclusive> <lockname> -- <command> [args...]\n' "$0" >&2
    exit 64
fi

case "$1" in
    shared)
        lock_mode=-s
        ;;
    exclusive)
        lock_mode=-x
        ;;
    *)
        printf 'error: lock mode must be shared or exclusive\n' >&2
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
marker_name=NOHIKI_ENV_LOCK_${lock_name}
marker_value=
eval "marker_value=\${$marker_name-}"
if [ "$marker_value" = 1 ]; then
    shift 3
    exec "$@"
fi

shift 3
runtime_dir=${XDG_RUNTIME_DIR:-/tmp}
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH='' cd -- "$script_dir/../.." && pwd -P)
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
umask 077
export "$marker_name=1"
mkdir -p -- "$lock_dir"
lock_file=$lock_dir/$lock_name.lock
exec 9>"$lock_file"
flock "$lock_mode" 9
exec "$@"
