---
name: add-package
description: Add a new top-level package under src/conveyor/ and place it in the import-linter layers contract, with docs, ADR and tests. Use when a feature needs a new conveyor.<name> package rather than a module in an existing one.
---

# Add a top-level package

Top-level packages are the architecture: `cli → registry → model | storage → contracts`
(highest first), enforced by import-linter. A new package is a design decision; agree it with
the human first.

## 1. Choose its layer

- List what it must import (from `conveyor` and outside) and what will import it.
- It goes below everything that imports it and above everything it imports. Packages that
  never import each other can share a layer, separated by `|`.
- Interface libraries (typer) stay in `conveyor.cli`; database libraries (sqlalchemy, alembic)
  stay in `conveyor.storage`. Forbidden contracts enforce both.
- If it would create a cycle, move the shared code down a layer or pass it in as a parameter.

## 2. Create it

1. `src/conveyor/<name>/__init__.py` with a module docstring saying what the package owns, and
   an `__all__` of its public API. Absolute imports only.
2. Add it to the `layers` contract in `pyproject.toml` (`[[tool.importlinter.contracts]]`,
   `id = "layers"`). If the layer is written as optional, `(conveyor.<name>)`, drop the
   parentheses once the package exists.
3. Update the Architecture section of `AGENTS.md` and the repository layout block.

## 3. Local rules

If the package has invariants an agent must know (owned data, error conventions, where things
go), add `src/conveyor/<name>/AGENTS.md` (at most 80 lines, local rules only, with a module
map) and a `CLAUDE.md` next to it containing exactly `@AGENTS.md`. Link it from the Start here
table in the root `AGENTS.md`.

## 4. Dependencies

A new third-party dependency needs the human's approval and an ADR (the `add-adr` skill). Add
it with `uv add <pkg>` (runtime) or `uv add --dev <pkg>`; never edit `uv.lock`.

## 5. Tests

Add `tests/test_<name>.py` (offline, deterministic) so branch coverage stays at or above 90%.

## 6. Check

```bash
uv run lint-imports
uv run pytest tests/test_repository.py   # fails if a package is missing from the contract
make check
```
