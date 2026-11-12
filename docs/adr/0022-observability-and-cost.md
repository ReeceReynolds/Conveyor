# 0022. Observability and cost: Pydantic AI instrumentation, a local span store, optional OTLP

- Status: Accepted
- Date: 2026-11-11

## Context

Every run must produce a scannable timeline: per stage the agent version, status, duration,
tokens and cost, and on request every model and tool call, including failed calls and retries.
The project overview asks for OpenTelemetry traces using the GenAI semantic conventions "pinned
to a specific version, since they are still in Development status", a local span store plus OTLP
export, and cost that is the provider's reported figure with `genai-prices` as a fallback.

Checked against PyPI and the published wheels on 2026-11-11:

- `opentelemetry-sdk` 1.45.2 supports Python 3.14.
- Core semantic conventions 1.42.0 moved every `gen_ai.*` convention to a new repository,
  `semantic-conventions-genai`. That repository is all Development status, has no release and
  no schema URL. `opentelemetry-semantic-conventions` 0.66b2 marks the names deprecated. There is
  no released GenAI conventions version to pin.
- Pydantic AI's built-in `Instrumentation` capability emits GenAI spans under its own versioned
  format. It also emits two non-standard names, `operation.cost` and `gen_ai.aggregated_usage.*`,
  and the deprecated `gen_ai.system`.
- `genai-prices` 0.2.3 is already a dependency of Pydantic AI, which prices every response with
  it. OpenRouter's billed cost is not put in `usage.cost`; it is in
  `ModelResponse.provider_details['cost']`.

## Decision

**Add `opentelemetry-sdk>=1.45` and `opentelemetry-exporter-otlp-proto-http>=1.45`.** The
OpenTelemetry API and `genai-prices` arrive through Pydantic AI and are not added directly.
`conveyor.observability` is the only package that imports `opentelemetry`
([ADR 0023](0023-execution-package-layering.md)).

**Spans come from Pydantic AI's `Instrumentation` capability, pinned to format version 5.** That
format is Pydantic AI's own versioned contract. Version 5 is its current default and stable;
version 6 exists and is slated to become the next default, so it is left for a later upgrade.
The GenAI attribute names Conveyor stores and reads are pinned by a snapshot test, with core
semantic conventions 1.41.0, the last release that carried the GenAI text, named as the
reference. Conveyor adds its own spans for the run and
each stage around them.

**One trace per run, across processes.** The trace context is stored on the run, so a run that
parks at a gate and is resumed by a later process continues the same trace.

**Every finished span is written to a `spans` table.** A span processor stores the run, the
attempt, the trace, span and parent IDs, the name, start and end times, status, and attributes
and events as JSON. A failed tool call is an error-status `execute_tool` span, and its retry is
a second span under the same stage.

**Tokens come from span attributes.** **Cost is the provider's billed figure when it reports
one**, which for OpenRouter is read from `provider_details['cost']`, and otherwise the figure
Pydantic AI calculated with `genai-prices`. The source of each amount is recorded beside it.

**OTLP export is off unless `CONVEYOR_OTLP_EXPORT=1`.** When it is on, the standard
`OTEL_EXPORTER_OTLP_*` variables configure the exporter. When it is off the exporter is never
constructed and no socket is opened.

**Message content is captured locally.** Prompts, outputs and tool arguments are stored in the
span store, because the timeline and later eval case capture need them. When OTLP export is on,
that content is exported too.

## Alternatives considered

- **Hand-written spans for model and tool calls.** This rebuilds what Pydantic AI maintains, and
  would drift from it.
- **Pin a GenAI semantic-conventions release.** None exists since the conventions moved
  repository. Pinning Pydantic AI's format version and testing the exact names is the pin that
  can be checked.
- **Store only an OTLP export, with no local store.** Conveyor must work on one machine with no
  hosted dependency, and `conveyor run show` must read its own data.
- **Use `genai-prices` only.** Its figure is calculated from a price table, so it can differ from
  what the provider actually billed. The overview asks for real spend first.

## Consequences

- `conveyor run show --calls` and the later web interface read the `spans` table, not an
  external backend.
- An upgrade of Pydantic AI that changes attribute names fails the snapshot test instead of
  silently breaking the timeline. When the GenAI conventions have a release, a new ADR can pin
  it.
- Some stored names are non-standard or deprecated. A backend that only understands the current
  conventions will not show them all.
- Turning on OTLP sends prompt and output content to the configured backend, not only span
  timings and token counts.
- Spend windows across runs (day, month) are not tracked in M3
  ([ADR 0020](0020-agent-runtime-pydantic-ai.md)).
