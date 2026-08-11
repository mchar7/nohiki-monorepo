#!/bin/sh
# Envelope for the pre-push gate's re-entrant Lefthook pass.
#
# Git hands a pre-push hook the remote name and URL as arguments and the ref
# pairs on standard input, one line of `<local ref> <local sha> <remote ref>
# <remote sha>`. Lefthook 2.1.10 reads NEITHER: internal/git/repo.go PushFiles()
# selects files with `git diff --name-only HEAD @{push}`, falling back to
# `git diff --name-only HEAD <head branch> --`, and the only standard-input
# reader in the run path sits behind `--files-from-stdin`. The selection is
# therefore a property of THIS WORKTREE, not of the commits being published.
#
# Two consequences this script exists to contain.
#
# 1. The tree examined can differ from the tree pushed. `git push origin
#    <rev>:refs/heads/<branch>` from a checkout parked on another commit makes
#    Lefthook examine the worktree while git publishes <rev>. Every check then
#    passes against code that is not being published, which is worse than a
#    skip because it leaves a green record that looks like verification. There
#    is no supported way to redirect Lefthook's selection at a different commit,
#    so this script refuses such a push instead of pretending to gate it.
#
# 2. An empty selection skips every job, globbed or not, and exits zero.
#    That is sound only when every published tip is already contained in the
#    validated origin/main history, which this envelope proves directly. Every
#    other push requires an inner-pass liveness marker. `--force` would suppress
#    the empty-selection check for all jobs at once, so it converts silent skips
#    into confident passes over the wrong file set while also running all
#    eighteen jobs on every push. It is deliberately NOT used.
#
# `--no-auto-install` matters more than it looks: a bare `lefthook run`
# regenerates .git/hooks/* from the stock template, which would silently replace
# a hardened hook wrapper with an unverified shim.
set -eu

# Refuse sparse worktrees before any destructive mirror synchronization, then
# refresh the owner-controlled copy from the primary worktree.
scripts/dev/secrets-mirror.sh

zero=0000000000000000000000000000000000000000

refs=$(mktemp "${TMPDIR:-/tmp}/nohiki-prepush-refs.XXXXXX")
liveness=$(mktemp "${TMPDIR:-/tmp}/nohiki-prepush-live.XXXXXX")
rm -f -- "$liveness"
cleanup() {
    rm -f -- "$refs" "$liveness"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cat >"$refs"

head_sha=$(git rev-parse HEAD)
head_tree=$(git rev-parse 'HEAD^{tree}')
# The jobs read the working tree, not a commit, so uncommitted edits to tracked
# files mean the content examined is not the content published. Untracked files
# cannot hide a finding in the published tree, so they only warrant a note.
dirty=$(git status --porcelain --untracked-files=no)
untracked=$(git ls-files --others --exclude-standard | wc -l)
validated_main=$(git rev-parse --quiet --verify 'refs/remotes/origin/main^{commit}' 2>/dev/null || true)
inspectable=0
refs_seen=0
requires_gate=0

# Refuse before taking the gate lock: a push we cannot honestly examine must not
# also pay the queue wait.
while IFS=' ' read -r local_ref local_sha remote_ref remote_sha; do
    [ -n "${local_ref:-}" ] || continue
    refs_seen=$((refs_seen + 1))
    if [ -z "${local_sha:-}" ] || [ -z "${remote_ref:-}" ] || [ -z "${remote_sha:-}" ]; then
        printf 'pre-push gate: malformed ref line for %s\n' "$local_ref" >&2
        exit 1
    fi
    # A deletion publishes no tree, so there is nothing for the gate to examine.
    if [ "$local_sha" = "$zero" ]; then
        printf 'pre-push gate: %s is a deletion; no tree to examine\n' "$remote_ref" >&2
        continue
    fi
    # Identity is the wrong test: `git push origin HEAD:refs/heads/x` and a
    # detached HEAD parked on the tip are both honest, and the property the gate
    # actually needs is that the tree it reads is the tree being published.
    local_tree=$(git rev-parse --quiet --verify "${local_sha}^{tree}" 2>/dev/null || true)
    if [ -z "$local_tree" ] || [ "$local_tree" != "$head_tree" ]; then
        printf 'pre-push gate: refusing to gate %s\n' "$remote_ref" >&2
        printf '  publishing commit: %s (tree %s)\n' "$local_sha" "${local_tree:-unknown}" >&2
        printf '  worktree HEAD:     %s (tree %s)\n' "$head_sha" "$head_tree" >&2
        printf 'Lefthook selects the files it checks from this worktree, so the\n' >&2
        printf 'jobs would examine a tree that is not the one being published and\n' >&2
        printf 'report a pass that verifies nothing. Check out %s and push from\n' "$local_sha" >&2
        printf 'there.\n' >&2
        exit 1
    fi
    if [ -n "$dirty" ]; then
        printf 'pre-push gate: refusing to gate %s\n' "$remote_ref" >&2
        printf 'Tracked files are modified, so the jobs would examine your\n' >&2
        printf 'uncommitted content rather than the commit being published, and a\n' >&2
        printf 'local fix you have not committed would pass for the pushed tree.\n' >&2
        printf 'Commit or stash them, then push:\n' >&2
        printf '%s\n' "$dirty" >&2
        exit 1
    fi
    if [ -n "$validated_main" ] && git merge-base --is-ancestor "$local_sha" "$validated_main"; then
        printf 'pre-push gate: passing %s without checks; merge-base with validated origin/main equals outgoing tip %s (origin/main %s), so there are no commits beyond origin/main\n' \
            "$remote_ref" "$local_sha" "$validated_main" >&2
        inspectable=1
        continue
    fi
    requires_gate=1
    inspectable=1
    printf 'pre-push gate: examining %s at %s, tree %s (remote %s at %s)\n' \
        "$local_ref" "$local_sha" "$head_tree" "$remote_ref" "$remote_sha" >&2
    if [ "$untracked" -gt 0 ]; then
        printf 'pre-push gate: note, %s untracked file(s) are also present in the tree being examined\n' \
            "$untracked" >&2
    fi
done <"$refs"

if [ "$refs_seen" -eq 0 ]; then
    # Invoked outside a real push, e.g. by hand. There is no ref pair to check
    # the worktree against, so say which tree is being examined and continue.
    printf 'pre-push gate: no ref pairs on standard input; examining worktree HEAD %s\n' \
        "$head_sha" >&2
    requires_gate=1
    inspectable=1
fi

if [ "$inspectable" -eq 0 ]; then
    printf 'pre-push gate: every pushed ref is a deletion; nothing to inspect\n' >&2
    exit 0
fi

if [ "$requires_gate" -eq 0 ]; then
    exit 0
fi

# The inner pass's stdout is redirected to stderr because Lefthook captures a
# job's stdout and prints it only when the job fails. That is what hid the inner
# pass all along: on a green push the developer saw one tick for the wrapper and
# never learned which of the eighteen jobs ran, which were skipped, or why.
# Stderr streams through, so this makes `(skip) no matching push files` and
# `✓ <job>` visible on every push, not just failing ones.
status=0
scripts/dev/env-lock.sh gate pre-push -- \
    scripts/dev/test-run.sh gate -- \
    env NOHIKI_GATE_ACTIVE=1 "NOHIKI_GATE_LIVENESS=$liveness" \
    lefthook run pre-push --no-auto-install "$@" <"$refs" >&2 || status=$?

# Order matters. A genuine failure inside the inner pass also leaves no liveness
# marker, and reporting that as "inspected nothing" would send the developer
# hunting an empty selection instead of reading the real error.
if [ "$status" -ne 0 ]; then
    exit "$status"
fi

if [ ! -e "$liveness" ]; then
    printf 'pre-push gate: FAILED, the gate inspected nothing.\n' >&2
    printf 'Every job was skipped and the gate exited zero, so it would have\n' >&2
    printf 'reported success having verified nothing. Lefthook selects pre-push\n' >&2
    printf 'files with `git diff --name-only HEAD @{push}`, falling back to a diff\n' >&2
    printf 'against the head branch. This empty selection provides no evidence\n' >&2
    printf 'that the outgoing commits were inspected, so the push is refused.\n' >&2
    exit 1
fi

exit 0
