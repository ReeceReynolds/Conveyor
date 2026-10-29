---
name: add-config-rule
description: Add or change a validation rule in the factory model (agent.yaml or factory files) end to end, from the pydantic model to positioned issues, fixtures, snapshots, schemas and docs. Use when conveyor validate should accept, reject or report something new.
---

# Add a configuration rule

Read [`src/conveyor/model/AGENTS.md`](../../../src/conveyor/model/AGENTS.md) first. Changing
what the configuration format accepts, or the published schemas, needs the human's approval.

## 1. Put the rule in the right place

| The rule is about | Put it in |
|---|---|
| The shape of one value (pattern, range, uniqueness) | a constrained type in `types.py`, or `Field(...)` constraints |
| Several fields of one model | a `@model_validator(mode="after")` on that model |
| Several stages, or another field that may itself be invalid | a `@field_validator`, plus a raw-data fallback as `raw_stage_graph_violations` does |
| Files on disk (agent folders, referenced agents) | `checks.py`, returning `Issue`s via `document.issue(...)` |

## 2. Report it well

- Raise `RuleViolation`s through `raise_violations(title, [...])`, or one error through
  `custom_error(error_type, message)`. Give each a short `error_type` and a precise `loc`.
- The message is lowercase, says what is expected and quotes what was found, e.g.
  `must be a lowercase slug like 'task-planner', got 'Planner'`.
- The loader turns the error into an `Issue` with file, line, column and field path. Check
  the position points at the offending key or value, not at the document root.

## 3. Fixture and snapshot

1. Add `tests/fixtures/agents/invalid-<rule>.yaml` or `tests/fixtures/factories/invalid-<rule>.yaml`
   that breaks only this rule (or a project under `tests/fixtures/projects/` for folder checks).
2. `test_model_files.py` globs `invalid-*.yaml`; run
   `uv run pytest tests/test_model_files.py --inline-snapshot=fix` and review the new entry:
   `(line:column, field path, message)`.
3. If a valid file should exercise the new field, extend `valid-full.yaml`. Add a Python-level
   test in `test_model_python.py` for edge cases, and a Hypothesis property in
   `test_properties.py` if the rule is on a parser or the stage graph.

## 4. Schemas, example and docs

1. `make schemas`, then review and commit the `schemas/` diff (a test fails if it is stale).
2. `uv run conveyor validate examples/prd-to-pr` must still pass.
3. Update the field descriptions (they are published in the schema) and any doc that describes
   the format: `README.md`, `docs/project-overview.md`, `examples/prd-to-pr/README.md`.

## 5. Check

`make quick`, then `make check` before opening the PR.
