# 0023. Execution package layering: six new packages, each heavy dependency in one place

- Status: Accepted
- Date: 2026-11-11

## Context

Milestone 3 adds durable workflows (`dbos`), agent execution (`pydantic_ai`,
`pydantic_ai_harness`), a sandbox, built-in operations and tracing (`opentelemetry`). The layers
today are `cli → registry → model | storage → contracts`, enforced by import-linter
([ADR 0014](0014-agent-ready-repository.md)), with `typer` kept in `conveyor.cli` and
`sqlalchemy` and `alembic` in `conveyor.storage`.

The new components must be built in parallel against agreed interfaces, tested with fakes, and
kept out of commands that do not need them (`--help` and `validate` must not import them, as the
sweep's F-03 fix established). Each heavy dependency should be importable from as few places as
possible, so it can be replaced or upgraded in one package.

## Decision

**Six new top-level packages** (`engine`, `runtime`, `sandbox`, `operations`, `observability`
and `execution`), placed in the `layers` contract at once (parenthesised, so optional, until
each package exists). Highest first:

```
conveyor.cli
conveyor.engine                                            only importer of dbos
conveyor.runtime | conveyor.sandbox | conveyor.operations  runtime and sandbox: only importers
                                                           of pydantic_ai, pydantic_ai_harness
conveyor.observability                                     only importer of opentelemetry
conveyor.execution                                         seams: protocols and value types,
                                                           no heavy imports
conveyor.registry
conveyor.model | conveyor.storage
conveyor.contracts
```

**Why each package sits where it does.**

- `conveyor.cli` stays on top. It wires the real components together and imports them lazily,
  inside the `run` commands.
- `conveyor.engine` drives a run: planning, stage execution and the DBOS workflow
  ([ADR 0018](0018-durable-execution-dbos.md)). It takes every component as a parameter typed by
  the seams, so it sits above the components it calls but never names their implementations
  except through what the CLI passes in.
- `conveyor.runtime`, `conveyor.sandbox` and `conveyor.operations` are the three components the
  engine calls. They share a layer and are independent of each other: the runtime reaches the
  workspace through a `WorkspaceHandle` value, not through `conveyor.sandbox`, and operations
  reach it through the `Workspace` seam.
- `conveyor.observability` is below the components because the runtime uses its tracing object.
  It implements the `Telemetry` seam and writes span records to storage
  ([ADR 0022](0022-observability-and-cost.md)).
- `conveyor.execution` holds the seams: protocols (`AgentRuntime`, `Operation`,
  `OperationRegistry`, `Workspace`, `WorkspaceProvider`, `Telemetry`), value types such as
  `StageInput` and `Artifact`, the tool vocabulary and the stage failure errors. It has no heavy
  imports, so every package above can depend on it and tests can fake it. It sits above
  `conveyor.registry` because the seams refer to agent snapshots.

**Three new `forbidden` contracts.**

- `dbos` may be imported only by `conveyor.engine`.
- `pydantic_ai` and `pydantic_ai_harness` may be imported only by `conveyor.runtime` and
  `conveyor.sandbox`.
- `opentelemetry` may be imported only by `conveyor.observability`.

**The runtime gets the tracer provider without importing OpenTelemetry.** `conveyor.observability`
exposes a tracing object that holds the tracer provider and its settings. The runtime receives
that object and passes its provider to Pydantic AI's `Instrumentation` capability, so no
`opentelemetry` import appears in `conveyor.runtime`.

**`pydantic_ai` is allowed in two packages** because `DockerSandbox` is a Pydantic AI Harness
class ([ADR 0021](0021-workspace-sandbox-and-tools.md)): the sandbox creates, attaches to,
exports and destroys the container, while the runtime builds agents whose `FileSystem` and
`Shell` tools run in it, re-attached by reference through the `WorkspaceHandle`. Keeping them in
separate packages lets the sandbox be built and tested on its own, with Docker, while the
runtime is tested with fake models.

## Alternatives considered

- **One `conveyor.execution` package for everything.** Fewer packages, but the engine, the
  runtime and the sandbox could not be built in parallel or tested against fakes, and `dbos`,
  Pydantic AI and OpenTelemetry would all be importable from the same place.
- **Fold the sandbox into `conveyor.runtime`.** One owner of `pydantic_ai`, but the sandbox could
  only be written after the runtime. This is the named re-cut if re-attaching by reference does
  not work.
- **Seams inside `conveyor.engine`.** The components would then import the engine, which is
  above them.
- **No forbidden contracts, only layers.** Layers order Conveyor's own packages but do not stop
  any of them from importing a third-party library.

## Consequences

- A new heavy import in the wrong package fails `uv run lint-imports` (part of `make lint`).
- import-linter checks Conveyor's own imports. Pydantic AI's use of the OpenTelemetry API, and
  DBOS's use of SQLAlchemy, happen inside those libraries and are not Conveyor imports.
- Seam changes affect several packages at once and are made once, deliberately.
- Each new package carries its own `AGENTS.md` where it has local rules, and the root `AGENTS.md`
  layer diagram is updated by Milestone 3's documentation work.
