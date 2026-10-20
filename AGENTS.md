# AGENTS.md

Guidance for coding agents (and humans) working on Conveyor itself. This file is the single
source of truth; tool-specific files such as `CLAUDE.md` only point here.

## What Conveyor is

An open-source foundation layer for harness engineering: the infrastructure to define an
agent-driven software factory, build and version its agents, gate each agent on evals, and
measure how changes affect the factory's output. Read
[`docs/project-overview.md`](docs/project-overview.md) before making design decisions.

## Repository layout

```
src/conveyor/        Python package (import name `conveyor`, distribution `conveyor-harness`)
tests/               pytest suite for src/conveyor
ui/                  React + TypeScript web interface (pnpm, Vite, Biome, Vitest)
examples/prd-to-pr/  Reference factory (uv workspace member, not published)
docs/                Concepts, guides and architecture decision records (docs/adr/)
```

## Commands

Run everything from the repository root.

| Task | Command |
|---|---|
| Install deps and git hooks | `make install` |
| Format and auto-fix | `make format` |
| Everything CI runs | `make check` |
| Python lint / types / tests | `make lint` / `make typecheck` / `make test` |
| UI lint, types, tests, build | `make ui-check` |
| Single Python test | `uv run pytest tests/test_package.py::test_name` |
| Add a Python dependency | `uv add <pkg>` (or `uv add --dev <pkg>`) |
| Add a UI dependency | `pnpm -C ui add <pkg>` |

## Definition of done

A change is done only when **`make check` passes** and:

- new or changed behaviour has tests;
- public functions, classes and modules have Google-style docstrings;
- docs (and this file) are updated if commands, layout or conventions changed;
- any new dependency or architectural decision has an ADR in `docs/adr/`.

Do not report work as complete if any check fails. Fix the cause; never weaken a check to pass.

## Conventions

**Python**
- Python 3.14, `src/` layout, absolute imports only.
- Pyright runs in strict mode. Avoid `Any`, `cast` and `# type: ignore`; when one is
  unavoidable, scope it to a single line and add a comment explaining why.
- Use Pydantic v2 models for data that crosses a boundary (config, contracts, artifacts,
  API payloads). Configuration models forbid extra fields.
- Prefer small, pure functions and explicit dependencies over globals and hidden state.
- Raise specific exceptions; never swallow errors silently.

**Tests**
- pytest only. Tests must be deterministic and make **no network calls**.
- Use Pydantic AI's `TestModel` or recorded cassettes for model interactions.
- Tests that call real model providers are marked `@pytest.mark.live`; they are excluded by
  default and run nightly under a spend cap.
- Use Hypothesis for parsers, hashing and diffing; inline-snapshot for structured outputs.

**UI**
- TypeScript strict; Biome is the only linter and formatter.
- The UI is built into `src/conveyor/_ui/` (gitignored) and served by the Python package.

**Git and releases**
- Conventional Commits for every commit and PR title (`feat:`, `fix:`, `docs:`, `build:`,
  `ci:`, `refactor:`, `test:`, `chore:`). PRs are squash-merged; release-please reads the
  titles to version and write the changelog. Do not edit versions or `CHANGELOG.md` by hand.
- Work on a branch and open a PR; never push directly to `main`.

## Boundaries

- Never commit secrets, API keys or `.env` files. Credentials come from the environment.
- Never hand-edit `uv.lock` or `ui/pnpm-lock.yaml`; change dependencies with `uv` / `pnpm`.
- Never bypass hooks (`--no-verify`) or disable a lint rule, type check or test to get green.
- Do not add a dependency without an ADR explaining why the established tool fits.
- Pin every GitHub Action to a full commit SHA with a version comment.

## Engineering principles

- Clear separation between orchestration, agent execution, evals, artifacts, the registry,
  observability and the interface.
- Human-readable, Git-friendly configuration; typed contracts between every stage.
- Runs, artifacts and agent versions are immutable.
- Durable by default: every run can stop and resume without losing completed work.
- Containment over instruction: permissions are enforced by the runtime and sandbox, never by
  the prompt. Every agent has explicit permissions and secret handling.
- Local-first: runs on one machine with no hosted dependencies.
- Adopt before building: use the established tool unless Conveyor's core purpose requires
  something new.
- One implementation of each thing until a second is genuinely needed.
