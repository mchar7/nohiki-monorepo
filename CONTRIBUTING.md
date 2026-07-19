# Contributing

This repo follows trunk-based development with short-lived feature branches,
git worktrees for parallel work, and machine-enforced quality gates.

## Worktrees

Run parallel work in separate worktrees, kept as siblings of the main
checkout (not nested inside it):

```bash
git worktree add ../worktrees/<feature-domain-kebab> -b feat/<feature-domain-kebab>
```

The sibling layout keeps build tooling (`uv`, `pnpm`, `just`, `ty`,
`semgrep`, etc.) from accidentally recursing into worktree checkouts. Each
worktree carries its own venv / `node_modules` / build caches.

When a branch lands on `main`, remove the worktree:

```bash
git worktree remove ../worktrees/<feature-domain-kebab>
```

## Branches

Branch names match this regex:

```regex
^(feat|fix|chore|refactor|docs|test|ci|perf|build|revert)/[a-z0-9][a-z0-9-]{2,49}$
```

Type prefixes mirror Conventional Commits. The slug after the `/` describes
what the change does in feature-domain terms (a service, a library, a
function, a user-visible behaviour). Examples: `feat/user-profile-avatar`,
`fix/login-redirect-loop`, `refactor/extract-payment-validator`,
`chore/upgrade-dependencies`.

`main` only moves through pull requests; branch protection blocks direct
pushes. Even a one-line fix rides a short-lived branch.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/) format,
enforced by `commitlint` via the `commit-msg` hook. Scope is the affected
service or library (`feat(correlation): ...`, `chore(ml-manifest): ...`).

One logical behaviour per commit. Tests live with the implementation they
exercise.

## Merging

Merge pull requests through GitHub's **Create a merge commit** option. Required
checks and review must pass before merge. Do not squash; the merge commit
preserves the reviewed branch tip and its semantic commits as ancestry.

Branches are short-lived (target ≤1 week). Long-running branches rebase on
`main` weekly.

## Hooks

Lefthook hooks run on every commit and every push. **Bypass mechanisms
(`LEFTHOOK=0`, `SKIP_PREPUSH=1`, `git --no-verify`, branch-name skip
patterns) are not honoured.** Pre-commit catches lint/format/secrets plus
workflow and Dockerfile lint; pre-push catches typecheck/tests/dead
code/dependency drift/proto breaking changes.

When a hook fails on a file unrelated to the current change, fix the
failing issue as part of the same branch in a separate atomic commit.
The merge commit preserves both repairs as reviewable semantic commits.
