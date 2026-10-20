# 0004. Testing strategy

- Status: Accepted
- Date: 2026-10-20

## Context

Agents are non-deterministic and model calls cost money. CI must be fast and deterministic,
while real-model behaviour still needs regular checking.

## Decision

- **pytest** with `--strict-markers`, `--strict-config`, strict xfail and warnings as errors.
  Coverage is measured with branch coverage and a 90% floor.
- **No network in the default test run.** Model interactions use Pydantic AI's `TestModel` or
  recorded cassettes (added with the first model-calling code).
- **Hypothesis** for property tests of parsers, content hashing and diffs; **inline-snapshot**
  for structured outputs.
- Tests that call real providers are marked **`live`** and are deselected by default
  (`-m "not live"`). They will run in a nightly workflow under a spend cap.
- **testcontainers** will be added with the storage layer to test Postgres in CI.

## Alternatives considered

- **Real models in CI** — slow, flaky and costly.
- **unittest** — more boilerplate and a weaker plugin ecosystem.

## Consequences

Every model-facing feature must be testable with a fake or recorded model. Live behaviour is
checked on a schedule rather than per change.
