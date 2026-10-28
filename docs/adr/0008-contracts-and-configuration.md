# 0008. Contracts and configuration: Pydantic v2 models and JSON Schema 2020-12

- Status: Accepted. Amended by [0011](0011-contract-resolution.md): contract references are
  now resolved at validate and publish time.
- Date: 2026-10-20

## Context

Factories and agents are defined by people in files that live in Git and are reviewed in pull
requests. Those files need one typed definition that the runtime, the CLI, editors and (later)
the registry and API all agree on, and mistakes in them must be caught before a run starts.

## Decision

- **Pydantic v2 models are the source of truth** for configuration (`conveyor.model`). Every
  model is frozen and forbids unknown fields; collections are tuples so instances are fully
  immutable. Booleans and numbers are strict, so `"true"` or `"0.5"` are rejected rather than
  coerced.
- **Rules live with the models.** Field constraints, cross-field rules (routing only with
  OpenRouter, at least one trigger) and stage-graph rules (unique ids, rework loops that only
  point backwards) are validators, so a model instance is always valid however it was built.
  Rules that need the filesystem (agent folders, referenced files) are separate checks, keeping
  the models free of IO.
- **Stages are a discriminated union** keyed on which of `agent`, `operation` or `human_gate`
  is present, not a model with optional fields, so "exactly one" is structural.
- **References are validated as dotted identifiers only** (`contracts.TaskList`,
  `scorers.tests_pass`); resolving them to Python objects belongs to execution.
- **JSON Schema 2020-12** is generated from the models with `$schema` and `$id`, committed under
  `schemas/` for editor validation and autocomplete, and regenerated with `make schemas`. A test
  fails if the committed files drift from the models.

## Alternatives considered

- **JSON Schema as the source, models generated from it** — loses Pydantic's validators and
  error messages, and adds a code-generation step.
- **dataclasses or attrs with a separate validator** — no built-in JSON Schema and weaker
  error reporting; Pydantic is already the contract layer for Pydantic AI.
- **Schemas generated at publish time only** — editors would have nothing to point at.

## Consequences

Error messages come from Pydantic plus Conveyor's own wording for custom types; field
descriptions double as schema documentation. Any model change must be followed by
`make schemas`, which CI enforces through the drift test.
