# 0014. Agent-ready repository: enforce, don't instruct

- Status: Accepted
- Date: 2026-10-29

## Context

Much of Conveyor's code is written by coding agents. Instruction files such as `AGENTS.md` are
advisory: agents follow them unevenly, and long ones lower adherence because the rules that
matter are diluted by everything else. Conveyor's own thesis applies to its repository:
containment over instruction.

Published guidance and practitioner reports converge on a few practices:

- `AGENTS.md` as a short map (roughly 100–150 lines) that routes to deeper context, with nested
  `AGENTS.md` files carrying local rules next to the code they govern;
- every rule that can be checked mechanically is checked by a linter, test or hook, and the
  failure message tells the agent how to fix the problem;
- a layered architecture that is enforced, not just described;
- execution plans versioned in the repository, so agents and humans work from the same plan;
- hooks for actions that must happen every time (protecting generated files, formatting after
  an edit), since a hook runs deterministically and an instruction may not.

The repository already had a strong base (ADR 0003): `make check`, Ruff, Pyright strict,
pre-commit with gitleaks, zizmor and Conventional Commits, SHA-pinned Actions and a Claude Code
allow-list. The gaps were architecture, test isolation, repository-level consistency and
agent-facing procedures.

## Decision

1. **Root `AGENTS.md` is a map** of at most 150 lines: a Start here routing table, the package
   layers, commands, the definition of done and Boundaries in three tiers (Always, Ask first,
   Never). `CLAUDE.md` stays exactly `@AGENTS.md`.
2. **Nested `AGENTS.md` files** (at most 80 lines, local rules only) in `src/conveyor/model/`,
   `tests/`, `ui/` and `examples/prd-to-pr/`, each with a sibling `CLAUDE.md` containing
   `@AGENTS.md`, because Claude Code does not read nested `AGENTS.md` files on its own.
3. **Plans in `docs/plans/`**, one per milestone (`milestone-N-<slug>.md`), updated as work
   packages land and kept as history.
4. **More Ruff rules** aimed at typical agent mistakes (blind excepts, prints, commented-out
   code, leftover TODOs, naive datetimes, blanket ignores, private access, shadowed builtins,
   namespace packages, boolean traps, complexity above 10, among others) and **banned APIs**
   with remediation messages (PyYAML, `pydantic.v1`, `typing.Any`, `typing.cast`, `unittest`).
5. **Stricter Pyright**: implicit overrides, import cycles, property type mismatches and
   uninitialised instance variables are errors, and `# type: ignore` is disabled in favour of
   rule-scoped `# pyright: ignore[rule]`.
6. **import-linter** enforces the layers `cli → registry → model | storage → contracts`, keeps
   typer in `conveyor.cli` and keeps sqlalchemy and alembic in `conveyor.storage`. It runs in
   `make lint`, `make quick` and pre-commit. Contract names say how to fix a violation.
7. **Test isolation**: pytest-socket (no network unless a test opts in), pytest-timeout (60 s
   per test) and pytest-randomly (random order every run). `make quick` is the fast Python
   loop.
8. **Repository tests** (`tests/test_repository.py`) check the ADR index, relative Markdown
   links, `AGENTS.md` sizes and `CLAUDE.md` pointers, `make` targets named in `AGENTS.md`
   files, that every top-level package is in the layers contract, skill frontmatter, and the
   protect-files hook.
9. **Claude Code configuration**: a PreToolUse hook blocks edits to lockfiles, generated
   schemas, release-please files, UI build output and `.env` files with a message saying how to
   make the change; a PostToolUse hook formats and lints each edited file and hands remaining
   problems back to the agent. `settings.json` adds deny rules for reading `.env` files, force
   pushes, pushing `main` and `--no-verify`.
10. **Skills** in `.claude/skills/` (`add-adr`, `add-config-rule`, `add-package`,
    `ship-change`) hold step-by-step procedures, so `AGENTS.md` stays a map. They are plain
    Markdown and readable by any agent.

New development dependencies: `import-linter`, `pytest-socket`, `pytest-timeout` and
`pytest-randomly`. The UI's Biome configuration also makes `noExplicitAny`, `noConsole` and
`noNonNullAssertion` errors and fails CI on warnings.

## Alternatives considered

- **One large `AGENTS.md`** — simpler to find, but adherence drops as the file grows and local
  rules are far from the code they govern.
- **Architecture rules as prose only** — cheapest, but nothing stops a violation; the
  layering would erode one convenient import at a time.
- **Custom AST-based architecture tests instead of import-linter** — no dependency, but we
  would maintain import resolution, indirect-import detection and error reporting ourselves;
  import-linter is established, configured declaratively and reports full import chains.
- **A Stop hook running `make check` after every turn** — strongest feedback, but the full
  check includes a UI build and is too slow per turn; CI and the definition of done cover it.
- **`deny` rules without hooks** — deny rules block silently or by pattern only; a hook can
  explain the correct way to make the change, which is what lets an agent recover.

## Consequences

- Feedback is stricter for humans too: more lint rules, random test order and no sockets in
  tests apply to everyone.
- Milestone 2 branches must merge `main` and fix any new violations; ADRs 0011–0013 are
  reserved by milestone 2, so this decision is 0014.
- Every new top-level package must be placed in the layers contract; a test fails otherwise.
- Hook scripts run on the system `python3`, so they use the standard library only and are
  linted and type-checked against Python 3.12.
- When an agent repeats a mistake, the fix goes into the harness (lint rule, test or hook)
  first and into prose last.
