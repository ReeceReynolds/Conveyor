---
name: ship-change
description: Pre-PR checklist for getting a change merged — checks, commits, branch, target and PR description. Use when work is finished and about to be committed, pushed or opened as a pull request.
---

# Ship a change

## 1. Branch and target

- Never commit to or push `main`. Branch names: `<type>/<short-slug>`, e.g.
  `feat/registry-cli`, `fix/loader-positions`, `docs/adr-index`.
- Milestone work packages branch from, and open their PR against, the milestone's integration
  branch `milestone/<slug>` (see the plan in `docs/plans/`), not `main`. Everything else
  targets `main`.
- Before pushing: `git fetch origin <target>` and rebase onto it.

## 2. Checks

1. `make check` passes locally: lint (including `uv run lint-imports` and `uv lock --check`),
   strict types, tests with 90% branch coverage, and the UI build.
2. Behaviour changes have tests; generated files are regenerated, not hand-edited
   (`make schemas`, `uv lock`, `pnpm -C ui install`).
3. Any `noqa` or ignore you added is rule-scoped and carries a one-line justification; list
   each one in the PR description.
4. Docs, the relevant `AGENTS.md` and the milestone plan reflect the change. A new dependency or
   design decision has an ADR (the `add-adr` skill).

## 3. Commits

- Conventional Commits (`feat:`, `fix:`, `docs:`, `build:`, `ci:`, `refactor:`, `test:`,
  `chore:`), optionally scoped: `feat(registry): add structured agent diffs`.
- The pre-commit hooks run on every commit (ruff, uv lock, gitleaks, zizmor, pyright,
  import-linter, Biome, commit message). Never use `--no-verify`; fix what they report.

## 4. Pull request

- Title: a Conventional Commit; it becomes the squash-merge commit that release-please reads.
- Fill in `.github/pull_request_template.md`: what and why, and tick only the items that are
  true. If the change fixes a mistake a check could have caught, add that check (lint rule,
  test or hook) in the same PR.
- Say what you verified and what you could not.

## 5. After review

Address comments with new commits (the PR is squashed on merge). For milestone work, update the
work package's state and PR number in the milestone plan.
