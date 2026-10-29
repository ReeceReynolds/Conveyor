# AGENTS.md

Guidance for coding agents (and humans) working on Conveyor itself. This file is a map: it
routes you to deeper context and states the rules. Tool-specific files such as `CLAUDE.md` only
point here. Rules that can be checked mechanically are checked by lint rules, tests and hooks
whose failure messages say how to fix the problem.

## What Conveyor is

An open-source foundation layer for harness engineering: the infrastructure to define an
agent-driven software factory, build and version its agents, gate each agent on evals, and
measure how changes affect the factory's output.

## Start here

| To | Read |
|---|---|
| Understand the product, factory model and scope (before any design decision) | [`docs/project-overview.md`](docs/project-overview.md) |
| See the current milestone and its work packages | [`docs/plans/`](docs/plans/README.md) |
| Work in a folder with local rules | [`src/conveyor/model/`](src/conveyor/model/AGENTS.md), [`tests/`](tests/AGENTS.md), [`ui/`](ui/AGENTS.md), [`examples/prd-to-pr/`](examples/prd-to-pr/AGENTS.md) (each `AGENTS.md`) |
| Know why a tool or design was chosen | [`docs/adr/`](docs/adr/README.md) |
| Follow a procedure step by step | `.claude/skills/<name>/SKILL.md`: [`add-adr`](.claude/skills/add-adr/SKILL.md), [`add-config-rule`](.claude/skills/add-config-rule/SKILL.md), [`add-package`](.claude/skills/add-package/SKILL.md), [`ship-change`](.claude/skills/ship-change/SKILL.md) |

Skills are plain Markdown; any agent can read and follow them.

## Repository layout

```
src/conveyor/        Python package (import name `conveyor`, distribution `conveyor-harness`)
  model/             Factory model: config models, YAML loading, checks, JSON Schema export
  cli.py             `conveyor` command line (Typer)
tests/               pytest suite for src/conveyor; YAML fixtures in tests/fixtures/
schemas/             Published JSON Schemas for agent.yaml and factory files (generated)
ui/                  React + TypeScript web interface (pnpm, Vite, Biome, Vitest)
examples/prd-to-pr/  Reference factory (uv workspace member, not published)
docs/                Project overview, milestone plans (docs/plans/) and ADRs (docs/adr/)
.claude/             Claude Code settings, hooks (hooks/) and skills (skills/)
```

## Architecture

Top-level packages form layers, highest first. A package may import from layers below it,
never from layers above; packages in the same layer (`|`) are independent of each other.

```
conveyor.cli                          command line; the only package that imports typer
conveyor.registry                     agent snapshots, diffs and versions (milestone 2)
conveyor.model | conveyor.storage     factory model | local state (storage arrives in milestone 2)
conveyor.contracts                    contract resolution (milestone 2)
```

This is enforced by import-linter (`uv run lint-imports`, part of `make lint`), which also keeps
`sqlalchemy` and `alembic` inside `conveyor.storage`. A new top-level package must be added to
the layers contract in `pyproject.toml`; a test fails until it is (see the `add-package` skill).

## Commands

Run everything from the repository root.

| Task | Command |
|---|---|
| Install deps and git hooks | `make install` |
| Fast Python loop while iterating (no UI, no coverage) | `make quick` |
| Everything CI runs | `make check` |
| Format and auto-fix | `make format` |
| Python lint / types / tests | `make lint` / `make typecheck` / `make test` |
| Check the import layers | `uv run lint-imports` |
| UI lint, types, tests, build | `make ui-check` |
| Single Python test | `uv run pytest tests/test_package.py::test_name` |
| Regenerate JSON Schemas after a model change | `make schemas` |
| Validate agents and factories | `uv run conveyor validate <path>` |
| Update inline snapshots | `uv run pytest --inline-snapshot=fix` |
| Add a Python dependency (ask first) | `uv add <pkg>` (or `uv add --dev <pkg>`) |
| Add a UI dependency (ask first) | `pnpm -C ui add <pkg>` |

## Definition of done

A change is done only when **`make check` passes** and:

- new or changed behaviour has tests;
- public functions, classes and modules have Google-style docstrings;
- docs (and the relevant `AGENTS.md`) are updated if commands, layout or conventions changed;
- any new dependency or architectural decision has an ADR in `docs/adr/`.

Do not report work as complete if any check fails. Fix the cause; never weaken a check to pass.

## Conventions

- Python 3.14, `src/` layout, absolute imports only. Pyright runs in strict mode: model types
  precisely instead of using `Any`, `cast` or ignores.
- Pydantic v2 models for data that crosses a boundary (config, contracts, artifacts, API
  payloads). Configuration models forbid extra fields.
- Small, pure functions and explicit dependencies over globals and hidden state. Raise specific
  exceptions; never swallow errors silently.
- Tests are deterministic and offline; see [`tests/AGENTS.md`](tests/AGENTS.md).
- Conventional Commits for every commit and PR title (`feat:`, `fix:`, `docs:`, `build:`,
  `ci:`, `refactor:`, `test:`, `chore:`). PRs are squash-merged; release-please reads the
  titles to version and write the changelog.
- Pin every GitHub Action to a full commit SHA with a version comment.

## Boundaries

**Always**
- Run `make quick` while iterating and `make check` before declaring work done.
- Add or update tests with every behaviour change.
- Keep docs and the relevant `AGENTS.md` in sync with the code.
- Use Conventional Commits; work on a branch and open a PR.

**Ask first** (stop and ask the human before you)
- add a dependency (it also needs an ADR);
- change the public CLI, the configuration format or the published JSON Schemas;
- change lint, type, test or CI configuration, or the rules in this file;
- edit an accepted ADR (supersede it with a new one instead);
- touch release automation (release-please config, release workflow).

**Never**
- commit secrets, API keys or `.env` files; credentials come from the environment;
- hand-edit `uv.lock`, `ui/pnpm-lock.yaml`, `schemas/`, `CHANGELOG.md` or versions;
- bypass hooks with `--no-verify`, or push to `main`;
- weaken or disable a check: every `noqa` or ignore is rule-scoped, on one line, with a
  one-line comment justifying it;
- make network calls in tests.

## Improving the harness

When an agent makes the same mistake twice, encode the fix as a lint rule, test or hook whose
failure message says how to fix it, before adding prose here. Keep this file a short map.

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
