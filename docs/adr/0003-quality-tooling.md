# 0003. Quality tooling: Ruff, Pyright strict, pre-commit and GitHub Actions

- Status: Accepted
- Date: 2026-10-20

## Context

Much of Conveyor's code will be written by coding agents. Agents need fast, unambiguous
feedback, and the codebase must stay production-ready without relying on reviewer vigilance.

## Decision

- **Ruff** for linting and formatting, with a broad curated rule set (including bugbear,
  bandit, pyupgrade, pylint, pydocstyle with Google convention, and a ban on relative imports).
- **Pyright in strict mode** across `src`, `tests` and `examples`.
- **pre-commit** runs fast checks on each commit: file hygiene, Ruff, `uv lock`, Pyright,
  Biome, gitleaks (secrets), zizmor (workflow security) and a Conventional Commit message check.
- **GitHub Actions** CI runs `make lint`, `make typecheck` and `make test` on Ubuntu and macOS,
  `make ui-check` for the UI, and zizmor. Every action is pinned to a commit SHA and workflows
  default to read-only permissions. Dependabot updates actions, Python and npm dependencies
  weekly with a 7-day cooldown.
- A `Makefile` is the single entry point shared by humans, agents and CI; `make check` is the
  definition of done.

## Alternatives considered

- **mypy** — Pyright is faster and its strict mode is stricter by default.
- **Black + isort + Flake8** — Ruff replaces all three with one fast tool.
- **just / poe** — `make` is preinstalled everywhere and universally understood by agents.

## Consequences

Strict typing raises the bar for third-party libraries without stubs; such cases are handled
with narrowly scoped, commented ignores. CI and local checks run the same commands, so "works
locally" means "passes CI".
