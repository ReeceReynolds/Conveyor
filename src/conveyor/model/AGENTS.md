# conveyor.model

The factory model: typed configuration for agents (`agent.yaml`) and factories (factory files),
how it is loaded from YAML, the checks that need the filesystem, and the published JSON
Schemas. It knows nothing about the CLI, storage or running agents.

## Invariants

- Every configuration model subclasses `ConfigModel` (`base.py`): frozen and
  `extra="forbid"`. Use the constrained types in `types.py` (`Slug`, `DottedRef`,
  `RelativePath`, `StrictBool`, ...) rather than bare `str`/`bool`, so values are never coerced
  and each constraint is published in the schema.
- Messages are written for the person editing the YAML: lowercase, specific, and quoting the
  offending value (`must be a lowercase slug like 'task-planner', got 'Bad'`).
- A rule broken by an otherwise well-typed value is a `RuleViolation(loc, error_type, message,
  value)`. Raise all of them at once with `raise_violations(...)` (one `ValidationError`, so
  every problem is reported in a single pass), or a single one with `custom_error(...)`. Never
  pass user input as a pydantic message template.
- Every reported problem is an `Issue` (`errors.py`) with `file`, 1-based `line`/`column` and a
  field `loc`, rendered as `file:line:column: field.path: message`. Only `loader.py` turns
  pydantic errors into positioned issues (`validate_document`); elsewhere build them with
  `Document.issue(loc, message)` so the position comes from the parsed YAML.
- Rules pydantic skips while other fields are invalid get a raw-data fallback (see
  `raw_stage_graph_violations`), so a person sees every problem the first time.
- Only `loader.py` touches ruamel.yaml (ADR 0009). It rejects duplicate keys, explicit tags,
  merge keys and recursive aliases, and caps alias expansion (`MAX_VALUES`).
- Checks that read the filesystem (agent folders, referenced agents) live in `checks.py`, not in
  the models: a model instance is valid on its own; whether its files exist is a separate check.

## Adding or changing a rule

Follow the [`add-config-rule`](../../../.claude/skills/add-config-rule/SKILL.md) skill. After
any model change run `make schemas` and commit the regenerated `schemas/` (a test fails if they
drift). Changing the configuration format or the schemas needs the human's approval first.

## Module map

| File | Owns |
|---|---|
| `__init__.py` | The public API; re-exports models, errors, loaders and `validate_path` |
| `base.py` | `ConfigModel`, `Loc`, `RuleViolation`, `custom_error`, `raise_violations` |
| `types.py` | Constrained primitives (patterns, unique and non-empty tuples, relative paths) |
| `agent.py` | `Agent` and its blocks: `Brief`, `Capabilities` (`ModelProfile`, `Routing`, `Permissions`), `QualityGate` |
| `factory.py` | `Factory`, stage kinds, `Trigger`, `OnReject`, `Outcome`/scorers, stage-graph rules |
| `errors.py` | `Issue`, `ConfigError` (carries every issue, sorted), `format_loc` |
| `loader.py` | YAML parsing with positions (`Document`), model validation into issues, `dump_yaml` |
| `checks.py` | Agent folder checks and factory → agent reference checks |
| `validate.py` | `validate_path` for an agent folder, a factory file or a project; `ValidationReport` |
| `schema.py` | JSON Schema 2020-12 export; `python -m conveyor.model.schema` behind `make schemas` |
