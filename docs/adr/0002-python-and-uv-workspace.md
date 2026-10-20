# 0002. Python 3.14 with a uv workspace and committed lockfile

- Status: Accepted
- Date: 2026-10-20

## Context

Conveyor is AI-engineering infrastructure; its key dependencies (Pydantic, Pydantic AI,
Pydantic Evals, DBOS, OpenTelemetry) are Python-first. Builds must be fast and reproducible on
any machine and in CI. The repository also hosts a reference factory in `examples/` that
depends on the package.

## Decision

- Target **Python 3.14** only (`requires-python = ">=3.14"`). Add 3.15 to CI once the
  dependency stack supports it.
- Manage the project with **uv** (≥ 0.13): `pyproject.toml` as the single source of metadata,
  `uv_build` as the build backend, and a committed `uv.lock`. CI installs with
  `uv sync --locked`, so an out-of-date lockfile fails the build.
- Use a **uv workspace**: the repository root is the `conveyor-harness` package (`src/` layout)
  and `examples/*` are workspace members. Examples are virtual members (`package = false`)
  and are never published.

## Alternatives considered

- **Poetry / PDM / pip-tools** — slower, and uv is now the standard for new projects.
- **Hatchling backend** — capable, but `uv_build` keeps the toolchain to one vendor with zero
  configuration for a pure-Python package.
- **Supporting older Pythons** — no installed base to support yet; a single version keeps
  typing and CI simple.

## Consequences

Contributors need uv ≥ 0.13 (enforced by `required-version`). New dependencies are added with
`uv add`, never by editing the lockfile.
