# 0009. YAML parsing with ruamel.yaml

- Status: Accepted
- Date: 2026-10-20

## Context

Factory and agent files are YAML written by hand. Errors must point at `file:line:column` and
the field path, loading must never construct arbitrary Python objects, and the parser must not
silently change meaning (duplicate keys, YAML 1.1 surprises such as `no` becoming `false`).

## Decision

Use **ruamel.yaml** (pure-Python, safe mode). Conveyor walks the composed node tree, which
records the start position of every key, value and item, and converts it to plain data plus a
position index. While walking it rejects duplicate keys (reporting both lines), explicit tags,
merge keys and recursive aliases. Pydantic validation errors are then mapped back to positions
through that index. Only `conveyor.model.loader` touches ruamel; its unannotated node types are
read through small typed protocols rather than casts or ignores.

## Alternatives considered

- **PyYAML** — YAML 1.1 semantics (`yes`/`no`/`on`/`off` become booleans, `1:30` an integer),
  keeps the last of duplicate keys without warning, and needs `types-PyYAML` for strict typing.
- **strictyaml** — strong guarantees, but its own schema language would duplicate the Pydantic
  models and it does not expose positions for Pydantic errors.
- **pydantic-yaml / pydantic-settings YAML source** — thin wrappers over PyYAML or ruamel that
  discard position information.

## Consequences

Configuration follows YAML 1.2: only `true`/`false` are booleans, and dates stay strings. The
loader owns a small tree walker that must be kept in step with ruamel's composer API, guarded by
the loader tests.
