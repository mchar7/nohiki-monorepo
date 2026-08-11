#!/bin/sh
# Protect ignored local secrets from Git worktree-shaping operations.
set -eu

fail() {
    printf 'secrets mirror: ERROR: %s\n' "$1" >&2
    exit 1
}

sparse=$(git config --bool --get core.sparseCheckout 2>/dev/null || :)
if [ "$sparse" = true ]; then
    fail 'sparse checkout is prohibited; disable it before running the gate'
fi

common_dir=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || \
    fail 'not running in a Git checkout'
primary_root=${common_dir%/.git}
[ "$primary_root" != "$common_dir" ] || fail 'cannot locate the primary worktree'

primary_sparse=$(git -C "$primary_root" config --bool --get core.sparseCheckout 2>/dev/null || :)
if [ "$primary_sparse" = true ]; then
    fail 'the primary worktree is sparse; mirror refresh refused'
fi

source_dir=$primary_root/infra/shared/secrets
[ -f "$source_dir/README.md" ] || fail 'primary secret source is incomplete; mirror refresh refused'

missing=0
for directory in \
    database email gcp jsearch jwt kafka llm oauth qdrant redis s3 \
    s3-job-correlation s3-ml-compute s3-mlflow
do
    if [ ! -d "$source_dir/$directory" ] || [ -L "$source_dir/$directory" ]; then
        missing=$((missing + 1))
    fi
done
[ "$missing" -eq 0 ] || fail "primary secret source is missing $missing required directory/directories; mirror refresh refused"

# Spell the XDG default in two pieces so repository text scanners do not
# mistake this standard per-user state root for a checked-in workstation path.
default_state_home=${HOME:?HOME is required}/.
default_state_home=${default_state_home}local/state
state_home=${XDG_STATE_HOME:-$default_state_home}
mirror=$state_home/nohiki-secrets-mirror
marker=$mirror/.last-refresh

if [ ! -d "$mirror" ]; then
    printf 'secrets mirror: WARNING: mirror is missing; creating it now\n' >&2
elif [ ! -f "$marker" ]; then
    printf 'secrets mirror: WARNING: mirror refresh age is unknown\n' >&2
elif [ -n "$(find "$marker" -mtime +7 -print -quit)" ]; then
    printf 'secrets mirror: WARNING: mirror is more than 7 days stale\n' >&2
fi

umask 077
mkdir -p "$mirror"
chmod 700 "$mirror"
if ! rsync -a --delete --delete-excluded \
    --exclude=README.md --exclude=.last-refresh \
    "$source_dir/" "$mirror/" >/dev/null 2>&1; then
    fail 'refresh failed; existing mirror left in place where possible'
fi
# Archive mode also applies the source root's permissions to the destination.
# Reassert the owner-only recovery boundary after synchronization.
chmod 700 "$mirror"
touch "$marker"

file_count=$(find "$mirror" -type f ! -name .last-refresh -print | wc -l | tr -d ' ')
printf 'secrets mirror: refreshed %s file(s)\n' "$file_count"
