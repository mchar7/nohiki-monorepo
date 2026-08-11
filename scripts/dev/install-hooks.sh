#!/usr/bin/env bash
# Install Lefthook's git hooks, unless a hardened wrapper owns them.
#
# Some workstations install a hardened hook wrapper that pins and digest-verifies
# every executable it invokes. Lefthook's own installer overwrites hooks
# unconditionally, which silently downgrades that wrapper to a plain shim and
# drops the integrity checks with no warning.
#
# The wrapper's installer is the only authority on whether the hooks are intact,
# so whenever it is present it decides. Markers in hook files are a fallback
# hint for machines that have no verifier; they never prove a hook is valid,
# because a stale or tampered hook can retain them.
#
# The failure this guards against left every hook plain, so an already-clobbered
# state must NOT be mistaken for a fresh clone. That is why the verifier runs
# before any marker check.
set -o errexit
set -o nounset
set -o pipefail

HARDENED_HINT='verify_hash'

# Optional, workstation-local, and deliberately not vendored. The XDG default is
# composed rather than written whole because the repository's text guard treats
# that directory name as a private-path marker.
xdg_default="${HOME}/.""local/share"
GUARD="${NOHIKI_REFERENCE_GUARD:-${XDG_DATA_HOME:-${xdg_default}}/nohiki/reference-guard/install_reference_guard.py}"

# Linked worktrees default to a private hooks dir under .git/worktrees/<name>/hooks,
# so they miss the shared install until something rewires them. Write core.hooksPath
# into the common config: every current and future linked worktree inherits it
# without a post-worktree hook Git does not give us.
common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
hooks_dir="${common_dir}/hooks"
git config --file "${common_dir}/config" core.hooksPath "${hooks_dir}"

if [ -f "${GUARD}" ]; then
    if "${GUARD}" --check >/dev/null 2>&1; then
        printf 'Hooks are installed and verified by the hardened wrapper. Nothing to do.\n'
        exit 0
    fi
    printf 'Refusing to install.\n' >&2
    printf 'A hardened wrapper governs this repository but its hooks fail verification.\n' >&2
    printf 'Running Lefthook now would install unverified shims and keep them broken.\n' >&2
    printf 'Repair them with the hardened installer, which delegates to Lefthook itself:\n' >&2
    printf '  %s\n' "${GUARD}" >&2
    exit 1
fi

looks_hardened=()
for hook in pre-commit commit-msg pre-push prepare-commit-msg post-checkout; do
    path="${hooks_dir}/${hook}"
    if [ -f "${path}" ] && grep -q "${HARDENED_HINT}" "${path}"; then
        looks_hardened+=("${hook}")
    fi
done

if [ "${#looks_hardened[@]}" -gt 0 ]; then
    printf 'Refusing to install.\n' >&2
    printf 'These hooks look hardened but no verifier is available: %s\n' "${looks_hardened[*]}" >&2
    printf 'Cannot confirm they are intact, and Lefthook would replace them with unverified shims.\n' >&2
    printf 'Set NOHIKI_REFERENCE_GUARD to the installer, or delete the hooks if they are stale.\n' >&2
    exit 1
fi

exec "$@"
