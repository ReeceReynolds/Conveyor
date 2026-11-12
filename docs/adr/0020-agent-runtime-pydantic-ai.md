# 0020. Agent runtime: Pydantic AI v2 and parts of Pydantic AI Harness, behind `AgentRuntime`

- Status: Accepted
- Date: 2026-11-11

## Context

An agent stage turns a pinned agent version ([ADR 0017](0017-run-version-pinning.md)) and a
`StageInput` ([ADR 0016](0016-run-model-and-handoff-routing.md)) into an output that satisfies
the agent's output contract. That needs a model client for several providers, structured output
typed by a Pydantic class, tool calling, usage limits and tracing. The project overview names
Pydantic AI v2 for agent execution, behind a small `AgentRuntime` interface, and Pydantic AI
Harness for coding agents ("Coder, Guardrails, Spend Limits").

Checked against PyPI and the published wheels on 2026-11-11:

- `pydantic-ai-slim` 2.67.0 supports Python 3.14 (classifiers 3.14 and 3.15). Its v2 API has
  capabilities, first-class workspaces (`pydantic_ai.workspaces`), `UsageLimits` with a
  `cost_limit`, and a built-in `Instrumentation` capability. It has the extras `anthropic`,
  `openai` and `openrouter`, and depends on `opentelemetry-api` and `genai-prices`.
- `pydantic-ai-harness` 0.67.0 supports Python 3.14. It is the current name; `pydantic-harness`
  is a deprecated rename. It is **alpha** ("API may change between minor releases"), pins
  `pydantic-ai-slim==2.67.0` exactly and is released in lockstep with it. It ships `FileSystem`,
  `Shell`, `Coder`, `DockerSandbox`, `guardrails`, `spend` and `permissions`.

## Decision

**Add `pydantic-ai-slim[anthropic,openai,openrouter]>=2.67` and `pydantic-ai-harness>=0.67` as
runtime dependencies.** The slim distribution with three extras installs only the providers
Conveyor supports.

**`AgentRuntime` is the seam.** It is a protocol in `conveyor.execution`
([ADR 0023](0023-execution-package-layering.md)) with one implementation, `PydanticAIRuntime` in
`conveyor.runtime`. The engine depends on the protocol only, and tests use a scripted fake.

**An agent is built from its `AgentSnapshot`.** The instructions, model profile, tools and
permissions all come from the pinned snapshot, never from files on disk. The `StageInput`
envelope is rendered as the user input: primary input, context artifacts and, on rework, the
`rework` block.

**Output is structured and typed by `brief.output`.** The runtime passes the resolved contract
class as Pydantic AI's output type. An output that fails validation is retried and, if retries
run out, the attempt fails.

**Providers: OpenRouter (the default), Anthropic and OpenAI.** `capabilities.model` selects the
provider and model ID and sets the sampling settings. For OpenRouter, the profile's `routing`
maps to `OpenRouterModelSettings(openrouter_provider=...)`: `only` restricts the upstream
providers and `allow_fallbacks` controls fallback. An unknown provider is a clear error.

**Credentials come from the environment only**: `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`. They are never part of an agent definition or a run record. A missing key is
reported with the name of the variable.

**Usage limits.** Each stage runs under Pydantic AI's core `UsageLimits`. In M3 the CLI sets
only its request limit, with `--max-stage-requests`; Pydantic AI's default `request_limit` is
50. There are no per-stage token or cost flags. The per-run limit (`--max-run-tokens`) is
enforced by the engine from the usage recorded for each attempt, since one run spans many agent
runs and several processes. `UsageLimits.cost_limit` would apply to `usage.cost`, which is the
`genai-prices` estimate rather than OpenRouter's billed cost
([ADR 0022](0022-observability-and-cost.md)), and a model `genai-prices` cannot price raises
`CostNotFoundWarning`, an error under the test suite's `filterwarnings = error`.

**From Pydantic AI Harness, M3 adopts `FileSystem`, `Shell` and `DockerSandbox`.** They provide
the file and shell tools and the container backend
([ADR 0021](0021-workspace-sandbox-and-tools.md)). The runtime registers only the tools an agent
declares.

**M3 does not adopt `Coder`, Guardrails or Spend Limits.**

- `Coder` bundles sub-agents, repository-context loading and compaction. A stage has one
  responsibility and a contract to meet, and should not have them.
- Guardrails are content policies that an owner writes: they check and redact content, and do
  not limit what an agent can do. `agent.yaml` has no field for them, and adding one is a
  configuration format change outside M3's approved list. Containment comes from tool
  registration and the sandbox, and the shape of output from contracts.
- Spend Limits supports `run`, `conversation`, `day`, `month` and `total` windows, but its
  stores are in-memory, Postgres, Redis and batch only: none is local and lasts across
  processes, while a Conveyor run spans several processes. Per-stage limits use core
  `UsageLimits`, and the per-run limit is enforced by the engine.

**MCP tools are out of M3.** No M3 stage needs them.

## Alternatives considered

- **Call provider SDKs directly.** This means writing structured output, retries, tool calling,
  usage accounting and tracing for each provider, which Pydantic AI already maintains.
- **Hand-built file and shell tools.** Against "adopt before building", when the Harness ships
  them.
- **Adopt `Coder` for the implementer.** It would give one stage sub-agents and context
  management that the factory model does not show and Conveyor cannot version or measure.
- **Harness Spend Limits for budgets.** None of its stores is local and lasting across
  processes, which a run that parks at a gate and resumes in another process needs.
- **Pydantic AI's per-model-call DBOS durability.** Not used in M3; see
  [ADR 0018](0018-durable-execution-dbos.md).

## Consequences

- The Harness is alpha and pins `pydantic-ai-slim` exactly, so the two always move together and
  any upgrade may change the Harness API. `uv.lock` holds both versions; upgrades are deliberate
  and tested.
- Pydantic AI brings `opentelemetry-api` and `genai-prices` transitively
  ([ADR 0022](0022-observability-and-cost.md)).
- `conveyor.runtime` and `conveyor.sandbox` both import Pydantic AI. ADR 0023 records why.
- The overview's row for coding agents ("Coder, Guardrails, Spend Limits") no longer matches
  and is reworded by Milestone 3's documentation work.
- A declared secret can appear in tool output, for example a command that prints its
  environment, and so reach the model, the span store and OTLP export. A follow-up is a Harness
  `ToolGuardrail` using `detectors.secret_data` on tool output.
- Guardrails, Spend Limits, `Coder` and MCP tools can each be adopted later with their own ADR.
