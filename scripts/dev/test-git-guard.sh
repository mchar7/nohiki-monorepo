#!/bin/sh
set -eu

root=$(git rev-parse --show-toplevel)
guard=$root/scripts/dev/git-guard.sh
real_git=$(git --exec-path)
real_git=$real_git/git
[ -x "$real_git" ] || real_git=$(command -v git)
scratch=$(mktemp -d /tmp/nohiki-git-guard.XXXXXX)
trap 'rm -rf "$scratch"' 0 HUP INT TERM

fail() {
    printf 'test-git-guard: %s\n' "$*" >&2
    exit 1
}

run_guard() {
    NOHIKI_GIT_REAL=$real_git "$guard" "$@"
}

assert_blocked() {
    if output=$(run_guard "$@" 2>&1); then
        fail "git $* was allowed"
    else
        status=$?
    fi
    [ "$status" -eq 2 ] || fail "git $* exited $status instead of 2: $output"
    case $output in
        *"git $subcommand"*"$root"*NOHIKI_GIT_DESTRUCTIVE=1*) ;;
        *) fail "git $* refusal omitted required detail: $output" ;;
    esac
}

assert_same() {
    if expected=$("$real_git" "$@" 2>&1); then
        expected_status=0
    else
        expected_status=$?
    fi
    if actual=$(run_guard "$@" 2>&1); then
        actual_status=0
    else
        actual_status=$?
    fi
    [ "$actual_status" -eq "$expected_status" ] ||
        fail "git $* changed exit $expected_status to $actual_status"
    [ "$actual" = "$expected" ] || fail "git $* changed output"
}

cd "$root"
for subcommand in sparse-checkout filter-repo filter-branch; do
    assert_blocked "$subcommand" --help
done

subcommand=clean
assert_blocked clean -n -f
assert_blocked clean -n -ff
assert_blocked clean -n --force
assert_blocked clean -ndf
assert_blocked -C "$root" clean -n -f
assert_blocked --git-dir "$root/.git" --work-tree "$root" clean -n -f

assert_same status --short
assert_same commit --dry-run --no-verify
assert_same clean -n
assert_same rev-parse --verify refs/heads/definitely-missing-git-guard-test
assert_same -C "$scratch" clean -n -f

NOHIKI_GIT_DESTRUCTIVE=1 assert_same clean -n -f

mkdir -p "$scratch/proto/nohiki"
printf '{}\n' >"$scratch/flake.nix"
printf 'pre-commit: {}\n' >"$scratch/lefthook.yml"
"$real_git" -C "$scratch" init -q
assert_same -C "$scratch" clean -n -f

expected=$(printf 'stdin transparency\n' | "$real_git" hash-object --stdin)
actual=$(printf 'stdin transparency\n' | run_guard hash-object --stdin)
[ "$actual" = "$expected" ] || fail 'stdin or stdout was changed'

printf 'git guard tests passed\n'
