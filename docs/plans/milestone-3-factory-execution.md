# Milestone 3 — Factory execution

- Status: In progress
- Integration branch: `milestone/factory-execution`

**Goal:** `conveyor run` executes a factory end to end as a durable workflow: pinned agent
versions, typed content-addressed handoffs, bounded rework, human gates that hold no process,
crash resume, sandboxed file and shell agents, and stored OpenTelemetry traces.

Approved by the project owner on 2026-11-11. Each work package is built by its own sub-agent;
the orchestrator owns this file and records status here at every wave checkpoint.

| Work package | Wave | Branch | State |
|---|---|---|---|
| WP-00 Decision records (ADRs 0016–0024) | 0 | `docs/m3-decisions` | In progress |
| WP-01 Dependencies and layer contracts | 1 | `build/m3-dependencies` | Planned |
| WP-02 Guarded migrations (F-05) | 1 | `fix/guarded-migrations` | Planned |
| WP-03 Operation stage parameters | 1 | `feat/operation-stage-params` | Planned |
| WP-04 Run schema and records | 1 | `feat/run-schema` | Planned |
| WP-05 Execution seams | 2 | `feat/execution-seams` | Planned |
| WP-06 Run and span repositories | 2 | `feat/run-repositories` | Planned |
| WP-07 Reference factory content | 2 | `feat/reference-factory` | Planned |
| WP-08 Observability | 3 | `feat/observability` | Planned |
| WP-09 Model providers | 3 | `feat/model-providers` | Planned |
| WP-10 Workspace sandbox | 3 | `feat/sandbox` | Planned |
| WP-11 Built-in operations | 3 | `feat/operations` | Planned |
| WP-12 Engine planning | 3 | `feat/engine-planning` | Planned |
| WP-13 Agent runtime | 4 | `feat/agent-runtime` | Planned |
| WP-14 Stage execution | 4 | `feat/stage-execution` | Planned |
| WP-15 Durable workflow | 5 | `feat/durable-workflow` | Planned |
| WP-16 `conveyor run` CLI | 6 | `feat/run-cli` | Planned |
| WP-17 End-to-end acceptance tests | 6 | `test/e2e-factory-run` | Planned |
| WP-18 Docs pass | 6 | `docs/m3-docs` | Planned |
| WP-19 Independent verification | 7 | none (reports only) | Planned |

## 0. Stack verification (checked 11 Nov 2026 against PyPI and the published wheels)

| Package | Latest | Python 3.14 | Finding |
|---|---|---|---|
| `pydantic-ai-slim` | 2.67.0 (11 Nov) | yes (classifier 3.14, 3.15) | v2 API: capabilities, first-class workspaces (`pydantic_ai.workspaces`), `UsageLimits` incl. `cost_limit`, built-in `Instrumentation` capability, extras `anthropic`, `openai`, `openrouter`. Depends on `opentelemetry-api` and `genai-prices`. |
| `pydantic-ai-harness` | 0.67.0 (11 Nov) | yes | Exists (the old `pydantic-harness` is a deprecated rename). **Alpha**: "API may change between minor releases". Pins `pydantic-ai-slim==2.67.0` exactly. Ships `FileSystem`, `Shell`, `Coder`, `DockerSandbox`, `guardrails`, `spend`, `permissions`. |
| `dbos` | 3.5.0 | yes (`>=3.10`, MIT) | SQLite system database supported. Parking a waiting workflow without a thread (`recv/sleep(suspend=True)`) is **Transact Enterprise only**. Recovery at launch is filtered by executor ID and application version. |
| `opentelemetry-sdk` | 1.45.2 | yes | Core semconv 1.42.0 **moved every `gen_ai.*` convention to a new repository** (`semantic-conventions-genai`), which is all Development status, has no release and no schema URL. `opentelemetry-semantic-conventions` 0.66b2 marks the names deprecated. |
| `genai-prices` | 0.2.3 | yes | Already a dependency of Pydantic AI, which prices every response with it. OpenRouter's billed cost is **not** put in `usage.cost`; it is in `ModelResponse.provider_details['cost']`. |
| `docker` (SDK) | 7.2.0 | no 3.14 classifier, stubs separate | Not needed (see below). |

**Findings that change choices in `docs/project-overview.md`** (raised here rather than substituted silently):

1. **Harness: adopt `FileSystem`, `Shell` and `DockerSandbox`; do not adopt `Coder`, Guardrails
   or Spend Limits in M3.** `Coder` bundles sub-agents, repo-context loading and compaction,
   which a contract-bound single-responsibility stage should not have. Per-stage limits use
   core `UsageLimits` (requests, tokens, cost); the per-run limit is enforced by the engine from
   recorded usage. Spend windows (day/month) belong with self-hosting. The overview row
   "Pydantic AI Harness (Coder, Guardrails, Spend Limits)" would be reworded by the docs pass.
2. **Docker SDK vs CLI is settled by the Harness**: `DockerSandbox` drives the `docker` CLI, so
   no Docker dependency is added. It is POSIX-only, so **sandboxed stages are not supported on
   Windows hosts in M3** (clear preflight error; those tests skip on the Windows CI runner).
3. **DBOS cannot park a waiting workflow in the open-source edition.** A gate therefore waits
   by the process exiting and a later CLI process explicitly resuming the workflow (decision 4).
   This is the highest technical risk in the milestone.
4. **Pydantic AI has its own DBOS integration** (per-model-call durability). M3 does not use it:
   the durable unit is the stage attempt, which is what the definition of done requires and
   keeps `dbos` in one package. Recorded as a follow-up in the ADR.
5. **`genai-prices` and the OTel API arrive through Pydantic AI.** No direct `genai-prices`
   dependency; Conveyor adds only the OTel SDK and OTLP exporter.
6. **MCP tools** (overview: "MCP, 2026-07-28 revision") are not needed by any M3 stage and stay out.
7. **There is no released GenAI semantic-conventions version to pin.** The overview says
   "pinned to a specific version". The honest pin is: Pydantic AI's instrumentation **format
   version 5** (its own versioned contract), plus a Conveyor snapshot test of the exact
   attribute names it stores and reads, with core semconv **1.41.0** (the last release that
   carried the GenAI text) named as the reference. Pydantic AI also emits two non-standard
   names (`operation.cost`, `gen_ai.aggregated_usage.*`) and the deprecated `gen_ai.system`.
8. **Provider-reported cost needs code for OpenRouter.** The runtime reads
   `provider_details['cost']` first and falls back to the `genai-prices` figure, recording
   which source was used.

Not verified: none of this was run on Python 3.14 here (support is from package metadata and
source), and pydantic.dev / docs.dbos.dev were unreachable, so API facts come from the wheels.
WP-01's acceptance test closes the first gap.

---

## 2. Where things stand

M0 (bootstrap), M1 (factory model), M2 (agent registry, #24 and #31) and the pre-M3 sweep
(F-01 to F-04 and F-14, #33 to #36 and #41) are done. Sweep finding F-05 is open. Layers today:
`cli → registry → model | storage → contracts`. Nothing executes; operations are a bare slug;
example agents have `tools: []` and placeholder prompts. `docs/add-xerj-recognition` and
F-06–F-13 are left alone.

## 3. Why this milestone now

Evals at runtime (M4), change sets (M5) and the UI (M6) all read run records. Until runs exist
with pinned versions, stored inputs and traces there is nothing for them to read.

## 4. Scope

**In:** run model and storage (runs, stage attempts, artifacts, pinned versions, statuses,
spans) in one new migration; a fix for sweep finding F-05; an `AgentRuntime` interface with one
Pydantic AI implementation (OpenRouter by default, Anthropic, OpenAI; credentials from the
environment; usage limits per stage and per run); durable execution on DBOS Transact with
bounded rework, escalation, human gates and resume; built-in operations `fetch-prd` and
`run-tests` with declared contracts; a hardened, no-network Docker workspace per run with file
and shell tools exposed only when declared; OpenTelemetry spans stored against the run with
opt-in OTLP export and per-call cost; the `conveyor run` command group; the reference factory
made runnable with an end-to-end test on scripted models.

**Out (later milestones):** eval suites and Quality Gate thresholds at runtime (M4; in M3 the
only gate on an agent's output is contract validation); outcome scorers, change sets and
before/after comparison (M5); the API server, SSE and web UI (M6); event triggers and webhook
listeners; GitHub network access (fetching issues, pushing branches, opening PRs); Postgres as
a supported production store, gVisor, parallel stages, diagnostic scorers and replay
benchmarks (M7); MCP tools.

Two additions that execution needs and that are named here rather than pulled in quietly:

- **Exporting the result.** With no GitHub access the run's branch would be stranded in a
  Docker volume. On completion the engine writes the branch as a Git bundle to
  `.conveyor/runs/<run>/` and `run show` prints the `git fetch` line. Nothing is pushed.
- **Cloning in.** The workspace is cloned from a Git bundle of the target repository's `HEAD`,
  so untracked and ignored files (for example `.env`) never enter the sandbox.

## 5. Decisions (each becomes an ADR in wave 0; none is TBD)

| # | ADR | Decision (recommended) | Main alternative rejected |
|---|---|---|---|
| 1 | 0016 Run model and handoff routing | A stage's input is **the most recent artifact in the run whose contract equals the stage's declared input contract**, not "the previous stage's output". Artifacts produced after that artifact and before the stage are passed as read-only **context**. So `review` receives the latest `CodeChanges` as input and `TestResults` as context. Operations declare input and output contracts in code, the way agents do in YAML. A preflight check proves every stage's input is produced earlier, before any model call. Artifacts are RFC 8785 canonical JSON in the existing object store, by digest; no collector in M3 (artifacts are small JSON; code lives in Git). | Explicit `inputs:` per stage in the factory file: more config surface for what the contracts already say. |
| 2 | 0016 (same) Rework input | On rejection the `return_to` stage gets the same envelope: its **original input** (unchanged digest), plus a `rework` block (iteration, rejecting stage, the verdict artifact) and context (its own previous output, later test results). The envelope `StageInput` is Conveyor-owned; `brief.input` still validates only the primary input, so the contracts format does not change. A stage "rejects" when its output has `decision: "reject"`; preflight requires that field on any agent stage with `on_reject`. Every execution of a stage is a `stage_attempts` row with `attempt` and `iteration`; `max_iterations: 3` means the 4th rejection escalates. | A dedicated rework contract per agent: changes every agent's contract pair. |
| 3 | 0017 Version pinning | A run pins the **latest published version** of every agent at start, all at once, before any stage runs; rework reuses the pins. It **refuses to start** if an agent has no published version or its working copy differs from the latest version (message names the agents and the `conveyor agent publish` fix). Agents are built from the stored snapshot, never the working copy. Contract classes are resolved from the project at each stage and their schema must equal the snapshot's, or the stage fails. No override flag in M3. | Warn and run the published version: silently ignores the edit the user just made. Auto-publish: hides a versioning step. |
| 4 | 0018 Durable execution (DBOS) | `conveyor.engine` is the only package importing `dbos`. System database: its own file `.conveyor/dbos.sqlite` (DBOS owns that schema; never Conveyor's Alembic chain). **One durable step = one stage attempt** (agent run, operation, or gate decision). A gate or escalation is `DBOS.recv` on the run's workflow; the CLI process then exits. `approve`/`reject` send the decision and **explicitly resume** that workflow in the foreground. Each process uses a unique executor ID and a pinned `application_version`, so nothing is recovered implicitly and an upgrade does not strand runs. `resume` after a crash replays checkpoints, marks the in-flight attempt `interrupted`, resets the workspace to that attempt's start commit and re-runs only that stage. A per-run file lock stops two processes driving one run. Run status: `pending, running, waiting, escalated, completed, rejected, failed`. Attempt status: `running, succeeded, rejected, failed, interrupted`; gates `waiting, approved, rejected`. `escalated` parks like a gate: `approve` accepts the latest work and continues, `reject` ends the run. | Shared database: schema coupling and lock contention. Pydantic AI's DBOS capability: finer resume, but `dbos` in two packages and replay constraints inside agents. Fallback if `recv` + explicit resume misbehaves: one workflow per segment between waits. |
| 5 | 0019 Operations | Built-ins live in a registry in new package `conveyor.operations`, keyed by slug. Each declares typed I/O and a strict params model. Stage configuration comes from one new optional field on operation stages, `with:` (**configuration format change**): `fetch-prd` takes `with: {output: contracts.PRD}` and validates the run's input file against it; `run-tests` takes `with: {command: [...], timeout_seconds: N}`, needs no input and outputs Conveyor-owned `TestResults` (exit code, passed, output tail, tested commit). Operations reach the workspace only through the `Workspace` seam handed to them by the engine. The factory file is stored by digest with the run, so operation config is pinned too. | Separate `operations/<name>.yaml` files: a second new file type and schema for two built-ins. Project `operations.py`: not declarative. |
| 6 | 0020 Agent runtime, 0021 Sandbox and tools | `AgentRuntime` seam with one Pydantic AI implementation; providers OpenRouter (default, honouring `routing`), Anthropic, OpenAI; credentials from the environment only. Sandbox: Harness `DockerSandbox` via the `docker` CLI, one hardened container per run over a named volume: `--network none --read-only --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --memory 2g --cpus 2 --tmpfs /tmp`, workspace volume the only writable mount. Default image built from a Dockerfile shipped in the package (Python, git, non-root user); `--sandbox-image` overrides. **Tool vocabulary** for `capabilities.tools`: `fs.read_file`, `fs.write_file`, `fs.edit_file`, `fs.list_directory`, `fs.search_files`, `fs.find_files`, `fs.create_directory`, `fs.file_info`, `shell.run_command`. The runtime registers only declared tools; an undeclared call never executes. `permissions.secrets`: only named variables are passed, per agent, to that agent's commands. `permissions.network`: the container never has a network; preflight rejects a tool-using agent with `network: true` in M3. **Who commits:** the agent commits with git through `shell.run_command`; Conveyor creates the branch, sets the identity, refuses output while the tree is dirty (retry prompt) and records the real base and head commit on every attempt. | Docker SDK: untyped, extra dependency. Hand-built tools: against "adopt before building". Conveyor committing: the model cannot then report `head_commit`. |
| 7 | 0022 Observability | Pydantic AI's `Instrumentation` capability pinned to **format version 5**; the GenAI attribute names Conveyor stores and reads are pinned by a snapshot test, with core semconv **1.41.0** as the named reference (no GenAI release exists to pin since the conventions moved repository). One trace per run across processes (trace context stored on the run). A span processor writes every finished span to a `spans` table (run, attempt, trace/span/parent IDs, name, times, status, attributes and events as JSON). A failed tool call is an error-status `execute_tool` span and its retry is a second span under the same stage. Tokens come from span attributes. Cost is the provider's billed figure when it reports one (OpenRouter: `provider_details['cost']`), else Pydantic AI's `genai-prices` calculation; the source is recorded beside the amount. OTLP export is off unless `CONVEYOR_OTLP_EXPORT=1`, then standard `OTEL_EXPORTER_OTLP_*` variables apply. Content is captured locally; the ADR notes it is exported when OTLP is on. | Hand-written spans: rebuilds what Pydantic AI maintains. |
| 8 | 0023 Layering | See below. | |
| – | 0024 Guarded migrations | F-05: `pg_advisory_xact_lock` on the migrating connection plus a module lock around Alembic. Closes the gap ADR 0012 records; ADR 0012 is not edited. | |

**Layers after M3** (highest first), all new packages added to the `layers` contract at once:

```
conveyor.cli
conveyor.engine                                            only importer of dbos
conveyor.runtime | conveyor.sandbox | conveyor.operations  runtime and sandbox: only importers of pydantic_ai, pydantic_ai_harness
conveyor.observability                                     only importer of opentelemetry
conveyor.execution                                         seams: protocols and value types, no heavy imports
conveyor.registry
conveyor.model | conveyor.storage
conveyor.contracts
```

New `forbidden` contracts: `dbos` → engine only; `pydantic_ai`, `pydantic_ai_harness` →
runtime and sandbox only; `opentelemetry` → observability only (the runtime receives the tracer
provider through a `conveyor.observability` object, never importing OTel itself).

## 6. Work packages

Every WP: one sub-agent, one branch off `milestone/factory-execution`, one PR, `make check`
green on its own. "Lines" is an estimate of non-test, non-generated lines. Seams are named as
`package.Name`.

### Wave 0 — decisions (serial, before anything else)

- **Plan PR** (orchestrator, `docs/m3-plan`): this plan as
  `docs/plans/milestone-3-factory-execution.md` plus the `docs/plans/README.md` row. Creates the
  integration branch.
- **WP-00 Decision records** (`docs/m3-decisions`). Goal: ADRs 0016–0024 from section 5, each
  with context, decision, alternatives, consequences. Owns `docs/adr/0016…0024-*.md`,
  `docs/adr/README.md`. Acceptance: `tests/test_repository.py` passes; the owner accepts by merging.
  Out of scope: any code. Depends on: plan approval.

### Wave 1 — foundations (parallel)

- **WP-01 Dependencies and layer contracts** (`build/m3-dependencies`, ~60 lines). Owns
  `pyproject.toml`, `uv.lock`. Adds the five dependencies, the `layers` entries (optional,
  parenthesised until each package exists), the three `forbidden` contracts, the `docker` pytest
  marker and its default exclusion. Acceptance: `make check`; `uv run lint-imports` lists the
  new contracts; importing each new dependency on 3.14 raises no warning under
  `filterwarnings = error`. Depends on: WP-00.
- **WP-02 Guarded migrations (F-05)** (`fix/guarded-migrations`, ~40 lines). Owns
  `src/conveyor/storage/migrate.py`, `tests/test_storage_migrate.py`. Acceptance:
  `test_concurrent_first_open_from_threads` (SQLite and Postgres) and
  `test_concurrent_first_open_from_processes` (`postgres` marker). Depends on: WP-00.
- **WP-03 Operation stage parameters** (`feat/operation-stage-params`, ~70 lines). Owns
  `src/conveyor/model/factory.py`, `schemas/factory.schema.json` (regenerated),
  `tests/fixtures/factories/*with*`, `tests/test_model_files.py`. Provides `OperationStage.with_`.
  Follows the `add-config-rule` skill. Acceptance: valid and invalid `with:` fixtures snapshot;
  schema drift test passes. Out of scope: interpreting the params. Depends on: WP-00.
- **WP-04 Run schema and records** (`feat/run-schema`, ~330 lines + generated migration). Owns
  `src/conveyor/storage/schema.py`, `storage/migrations/versions/0002_*.py`,
  `storage/records.py`, `tests/test_storage_store.py`, `tests/test_storage_run_schema.py`.
  Tables: `runs`, `run_pins`, `stage_attempts`, `artifacts`, `spans`. Provides
  `storage.records.{RunRecord, PinRecord, StageAttemptRecord, ArtifactRecord, SpanRecord,
  RunStatus, AttemptStatus}`. Acceptance: model/migration drift test on both backends;
  upgrade from `0001` keeps registry data. **Sole owner of the migration chain and `schema.py`
  for the milestone.** Depends on: WP-00.

### Wave 2 — seams, repositories, reference content (parallel)

- **WP-05 Execution seams** (`feat/execution-seams`, ~350 lines). New package
  `conveyor.execution` (+ its `AGENTS.md`/`CLAUDE.md`) and `tests/fakes/`. Provides value types
  `Artifact`, `StageInput`, `ReworkContext`, `WorkspaceFacts`, `AgentResult`, `Usage`,
  `UsageBudget`, `WorkspaceHandle`, `CommandResult`, the tool vocabulary constants, the
  `StageFailure` error family, and protocols `AgentRuntime`, `Operation`, `OperationRegistry`,
  `Workspace`, `WorkspaceProvider`, `Telemetry`. Fakes: `ScriptedRuntime` (counts calls),
  `FakeWorkspaceProvider`, `FakeOperations`, `RecordingTelemetry`. Acceptance: each fake passes
  a protocol conformance test; pyright strict proves the fakes satisfy the protocols.
  Out of scope: any behaviour. Depends on: WP-01.
- **WP-06 Run and span repositories** (`feat/run-repositories`, ~500 lines). Owns
  `storage/runs.py`, `storage/spans.py`, `storage/store.py`, `storage/__init__.py`,
  `storage/errors.py`, `tests/test_storage_runs.py`, `tests/test_storage_spans.py`. Provides
  `Store.runs` (create run with pins, idempotent attempt upsert keyed by run/stage/attempt,
  artifacts, status transitions, list, get by ID prefix) and `Store.spans`. Acceptance:
  parametrised over SQLite and Postgres; replaying the same attempt write is a no-op; illegal
  status transitions raise. Depends on: WP-04.
- **WP-07 Reference factory content** (`feat/reference-factory`, 0 Python lines). Owns
  `examples/prd-to-pr/**`: real prompts for the four agents, the implementer's and reviewer's
  toolkits, `with:` on both operation stages, `inputs/sample-prd.yaml`, a tiny `sample-app/`
  target, README and `AGENTS.md`. Acceptance: `conveyor validate examples/prd-to-pr` clean;
  the existing example tests pass; the sample PRD validates against `contracts.PRD`.
  **Sole owner of `examples/prd-to-pr/`.** Depends on: WP-03.

### Wave 3 — components against seams and fakes (parallel)

- **WP-08 Observability** (`feat/observability`, ~350 lines). New package
  `conveyor.observability`. Consumes `execution.Telemetry`, `storage.records.SpanRecord`.
  Provides `Tracing` (tracer provider, pinned settings, stage spans, cross-process trace
  context) and the span-to-sink processor, plus the OTLP switch. Acceptance: spans from an
  in-memory run land as `SpanRecord`s with run and attempt attribution; error status and
  exception event preserved; OTLP exporter is not constructed unless the variable is set (no
  socket opened). Depends on: WP-04, WP-05.
- **WP-09 Model providers** (`feat/model-providers`, ~220 lines). Creates package
  `conveyor.runtime` (`__init__`, `AGENTS.md`, `providers.py`). Provides
  `runtime.providers.build_model(ModelProfile) -> Model`. Acceptance: OpenRouter routing
  (`only`, `allow_fallbacks`) and sampling settings map exactly (inline snapshot of the built
  settings); a missing key names the environment variable; an unknown provider is a clear
  error; no test opens a socket; one `live`-marked smoke test, not run. Depends on: WP-01, WP-05.
- **WP-10 Workspace sandbox** (`feat/sandbox`, ~400 lines). New package `conveyor.sandbox`,
  its Dockerfile, `tests/conftest.py` (Docker fixture), `.github/workflows/ci.yml` (new
  Linux-only `docker` job, like the Postgres job). Provides `DockerWorkspaceProvider`
  implementing `execution.WorkspaceProvider`: create from a bundle, attach by handle, run,
  export branch bundle, destroy. Acceptance: offline unit tests snapshot the exact hardening
  arguments; `docker`-marked tests prove non-root, read-only root, writable workspace, and that
  an outbound connection fails. Depends on: WP-01, WP-05.
- **WP-11 Built-in operations** (`feat/operations`, ~300 lines). New package
  `conveyor.operations`. Provides the registry, `fetch-prd`, `run-tests`, `TestResults`.
  Consumes `execution.{Operation, Workspace}`, `OperationStage.with_`, `conveyor.contracts`.
  Acceptance (with `FakeWorkspaceProvider`): `fetch-prd` rejects a file that violates the
  contract with a positioned message; `run-tests` records exit code, pass/fail, output tail
  and timeout; unknown slug and bad params are preflight errors. Depends on: WP-03, WP-05.
- **WP-12 Engine planning** (`feat/engine-planning`, ~450 lines). Creates package
  `conveyor.engine` with pure modules only (`plan.py`, `machine.py`; no `dbos`). Provides
  `preflight(...) -> RunPlan` (pins, routing table, every check in decisions 1–3, 5, 6) and
  `next_action(plan, history) -> Action` (run stage, wait at gate, escalate, complete, fail).
  Acceptance: the reference factory plans with `review ← CodeChanges + TestResults`; Hypothesis
  properties: the machine never loops past `max_iterations`, always terminates, never re-runs a
  succeeded stage outside a rework loop; unpublished or dirty agents, missing producer and
  undeclared tools are reported together. Depends on: WP-03, WP-05.

### Wave 4 — execution (parallel)

- **WP-13 Agent runtime** (`feat/agent-runtime`, ~450 lines). Owns `runtime/agent.py`,
  `runtime/__init__.py`. Provides `PydanticAIRuntime` implementing `execution.AgentRuntime`:
  agent from `AgentSnapshot`, instructions, output typed by `brief.output`, input envelope
  rendering, declared-tools-only registration, usage limits, tracing, output checks. Consumes
  `build_model`, `observability.Tracing`, `WorkspaceHandle`. Acceptance (`TestModel` /
  `FunctionModel`): output validates against the contract and a violation retries then fails;
  **a model calling an undeclared tool gets an error and nothing executes**; a deliberately
  failing tool call and its retry both appear as spans; request and token limits stop the run;
  provider-reported cost wins over the calculated one and the source is recorded; secrets not
  declared are absent from the command environment. Depends on: WP-08, WP-09.
- **WP-14 Stage execution** (`feat/stage-execution`, ~350 lines). Owns `engine/stages.py`.
  Executes one planned action: builds `StageInput` from stored artifacts, calls the runtime or
  operation, validates and stores the output artifact, writes the attempt, enforces the run
  budget, checks the worktree. Acceptance (fakes + real store): artifacts are stored by digest
  and re-running the same attempt is idempotent; rework input carries the verdict; a
  contract-invalid output fails the attempt, not the process. Depends on: WP-06, WP-12.

### Wave 5 — durability

- **WP-15 Durable workflow** (`feat/durable-workflow`, ~450 lines). Owns `engine/workflow.py`,
  `engine/service.py`, `engine/__init__.py`. Provides `Engine` (`start`, `resume`, `decide`,
  `get`, `list`), taking every component as a parameter. Acceptance, all with fakes and a real
  SQLite store: the first test is the spike — start, park at the gate, tear DBOS down, relaunch,
  approve, complete; a subprocess killed after `tasks` resumes at `implement` with the
  `requirements` and `tasks` call counts unchanged; four rejections end `escalated`; a second
  process cannot drive a locked run. Depends on: WP-14, WP-13 (types only), WP-01.

### Wave 6 — interface, acceptance, docs (parallel)

- **WP-16 `conveyor run` CLI** (`feat/run-cli`, ~350 lines). Owns `src/conveyor/cli.py`,
  `tests/test_cli_run.py`, `tests/test_cli.py`. Commands: `run start <factory> --input FILE
  [--repo PATH] [--sandbox-image IMAGE] [--max-stage-requests N] [--max-run-tokens N]
  [--project PATH]`, `run list`, `run show <run> [--calls]`, `run approve <run> [-m NOTE]`,
  `run reject <run> -m REASON`, `run resume <run>`. Wires the real components (lazy imports;
  `--help` and `validate` still import none of them). Acceptance: `CliRunner` over the example
  with scripted models: exit codes 0/1/2 per ADR 0010, `show` prints per stage the pinned
  version, status, attempts, artifact digests, duration, tokens and cost, and with `--calls`
  every model and tool call. **Sole owner of `cli.py`.** Depends on: WP-15, WP-10, WP-11, WP-13.
- **WP-17 End-to-end acceptance tests** (`test/e2e-factory-run`, tests only). Owns
  `tests/test_e2e_prd_to_pr.py`, `tests/e2e/`. Real engine, runtime, operations, telemetry and
  store with scripted `FunctionModel`s; local workspace by default, real sandbox under the
  `docker` marker. Covers definition-of-done items 2–7. Finds bugs, fixes none: failures go
  back to the owning WP through the orchestrator. Depends on: WP-15, WP-07, WP-10, WP-11, WP-13.
- **WP-18 Docs pass** (`docs/m3-docs`). Owns `README.md`, root `AGENTS.md`, `tests/AGENTS.md`,
  `docs/project-overview.md`. Moves "Running factories as durable workflows" to Available with
  a `conveyor run` quickstart; new layout, layers and commands; the Harness wording from
  section 0. Depends on: WP-15 (shapes are fixed by this plan and ADRs).

### Wave 7 — independent verification

- **WP-19 Verification** (fresh sub-agent that built nothing, no branch). Checks each
  definition-of-done item and the four-step expected result on a clean checkout of the
  integration branch, reports evidence per item, changes nothing. Findings return to the
  owning WP. The orchestrator then opens the milestone PR to `main`.

## 7. Ask-first items (the approved list; anything beyond it stops and asks)

- **Dependencies (runtime):** `pydantic-ai-slim[anthropic,openai,openrouter]` ≥ 2.67,
  `pydantic-ai-harness` ≥ 0.67 (alpha), `dbos` ≥ 3.5, `opentelemetry-sdk` ≥ 1.45,
  `opentelemetry-exporter-otlp-proto-http` ≥ 1.45. No new dev dependencies.
- **CLI:** the `conveyor run` group as listed under WP-16.
- **Configuration format and schemas:** optional `with:` mapping on operation stages
  (`schemas/factory.schema.json` regenerated). Nothing else; `agent.yaml` is unchanged.
- **Lint/type/test/CI configuration:** import-linter layers and three forbidden contracts; the
  `docker` pytest marker (excluded by default); a Linux-only `docker` CI job.
- **ADRs:** new 0016–0024. No accepted ADR is edited; `docs/adr/README.md` gains rows.
- **New on-disk state and environment:** `.conveyor/dbos.sqlite`, `.conveyor/runs/<run>/`;
  `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CONVEYOR_OTLP_EXPORT`.

**Two deliberate exceptions to the cutting rules, for the same reason** (a test requires every ADR to
be indexed in the PR that adds it): `docs/adr/README.md` is owned by WP-00, not the final docs
pass; and WP-00 carries nine ADRs although a work package normally carries at most one, because the decisions must
all be accepted before parallel work starts. Later WPs write no ADRs.

## 8. Definition of done

Checked by WP-19:

1. `make check` passes on `milestone/factory-execution`, branch coverage stays at or above 90%,
   and the default test suite opens no network socket.
2. An end-to-end test runs `prd-to-pr` with scripted models from the sample PRD through every
   stage, including one review rejection and rework, and stops waiting at `approve`. Approving
   it completes the run.
3. A test kills the run after `tasks` completes and resumes it. `implement` continues, and the
   scripted models for `requirements` and `tasks` are not called again (asserted by call count).
4. A test where `review` rejects four times ends with the run `escalated`, not failed and not
   looping.
5. The run record holds the pinned version ID of every agent, every artifact by digest, and
   every model and tool call, including a deliberately failing tool call and its retry, with
   tokens and cost.
6. In the Docker test job, the implementer's workspace has no network. An attempted connection
   fails, and the failure is recorded on the trace.
7. An agent whose toolkit does not declare a tool cannot call it. A test proves the runtime
   enforces this, not the prompt.
8. Every new dependency and design decision has an ADR, F-05 is closed by a new ADR, and this
   file shows every work package done with its PR.
9. `README.md` moves "Running factories as durable workflows" from Planned to Available, with a
   quickstart for `conveyor run`. Root `AGENTS.md` reflects the new layout, layers and commands.
10. The milestone lands on `main` as one PR from the integration branch, opened by the
    orchestrator and reviewed and merged by the project owner.

## 9. Delivery

Work packages land as PRs into `milestone/factory-execution`; the milestone then lands on
`main` as one reviewed PR so release-please records a single `feat` entry. No `live` test is
run and no provider credit is spent without the owner's say-so.

---

## 10. Dependency graph

```
W0  plan ── WP-00 ADRs
W1  WP-01 deps   WP-02 F-05   WP-03 op params   WP-04 run schema
       │                          │      │           │
W2  WP-05 seams ◄─┘               │   WP-07 example  WP-06 repositories
       │                          │                     │
W3  WP-08 observability  WP-09 providers  WP-10 sandbox  WP-11 operations  WP-12 planning
       │        (04,05)      │   (01,05)      (01,05)        (03,05)          │ (03,05)
W4  WP-13 agent runtime ◄────┘                                WP-14 stage execution ◄─ 06,12
       └───────────────────────────────┬──────────────────────────┘
W5                              WP-15 durable workflow
W6  WP-16 CLI (15,10,11,13)   WP-17 e2e (15,07,10,11,13)   WP-18 docs (15)
W7  WP-19 verification → milestone PR to main
```

## 11. File ownership (no path appears twice in a wave)

| Wave | WP | Owned paths |
|---|---|---|
| 0 | plan | `docs/plans/**` (orchestrator, whole milestone) |
| 0 | WP-00 | `docs/adr/**` (whole milestone) |
| 1 | WP-01 | `pyproject.toml`, `uv.lock` (whole milestone) |
| 1 | WP-02 | `storage/migrate.py`, `tests/test_storage_migrate.py` |
| 1 | WP-03 | `model/factory.py`, `schemas/factory.schema.json`, `tests/fixtures/factories/`, `tests/test_model_files.py` |
| 1 | WP-04 | `storage/schema.py`, `storage/migrations/**` (whole milestone), `storage/records.py`, `tests/test_storage_store.py`, `tests/test_storage_run_schema.py` |
| 2 | WP-05 | `src/conveyor/execution/**`, `tests/fakes/**`, `tests/test_execution.py` |
| 2 | WP-06 | `storage/{runs,spans,store,errors,__init__}.py`, `tests/test_storage_{runs,spans}.py` |
| 2 | WP-07 | `examples/prd-to-pr/**` (whole milestone) |
| 3 | WP-08 | `src/conveyor/observability/**`, `tests/test_observability.py` |
| 3 | WP-09 | `src/conveyor/runtime/{__init__,providers}.py`, `runtime/AGENTS.md`, `runtime/CLAUDE.md`, `tests/test_runtime_providers.py` |
| 3 | WP-10 | `src/conveyor/sandbox/**`, `tests/conftest.py`, `tests/test_sandbox*.py`, `.github/workflows/ci.yml` (whole milestone) |
| 3 | WP-11 | `src/conveyor/operations/**`, `tests/test_operations.py` |
| 3 | WP-12 | `src/conveyor/engine/{__init__,plan,machine}.py`, `engine/AGENTS.md`, `engine/CLAUDE.md`, `tests/test_engine_{plan,machine}.py` |
| 4 | WP-13 | `runtime/agent.py`, `runtime/__init__.py`, `tests/test_runtime_agent.py` |
| 4 | WP-14 | `engine/stages.py`, `tests/test_engine_stages.py` |
| 5 | WP-15 | `engine/{workflow,service,__init__}.py`, `tests/test_engine_workflow.py` |
| 6 | WP-16 | `src/conveyor/cli.py` (whole milestone), `tests/test_cli_run.py`, `tests/test_cli.py` |
| 6 | WP-17 | `tests/test_e2e_prd_to_pr.py`, `tests/e2e/**` |
| 6 | WP-18 | `README.md`, `AGENTS.md`, `tests/AGENTS.md`, `docs/project-overview.md` (whole milestone) |

`runtime/__init__.py` and `engine/__init__.py` change hands between waves (3→4, 3→5), never
within one.

## 12. Cutting-rule check

| WP | 1 one PR | 2 one job, ≤1 ADR | 3 exclusive files | 4 seams first | 5 size | 6 edges listed | 7 deterministic tests |
|---|---|---|---|---|---|---|---|
| 00 | ✓ | job ✓; **9 ADRs: flagged exception** | ✓ | n/a | docs | ✓ | repository tests |
| 01 | ✓ | ✓ | ✓ | n/a | ~60 | ✓ | ✓ |
| 02 | ✓ | ✓ | ✓ | n/a | ~40 | ✓ | ✓ (`postgres` marker for processes) |
| 03 | ✓ | ✓ | ✓ | provides `with_` | ~70 | ✓ | ✓ snapshots |
| 04 | ✓ | ✓ | ✓ | provides records | ~330 | ✓ | ✓ |
| 05 | ✓ | ✓ | ✓ | **is the seam** | ~350 | ✓ | ✓ |
| 06 | ✓ | ✓ (repositories over one schema) | ✓ | consumes records | ~500 | ✓ | ✓ |
| 07 | ✓ | ✓ | ✓ | consumes `with_`, vocabulary | 0 | ✓ | ✓ |
| 08 | ✓ | ✓ | ✓ | consumes `Telemetry`, `SpanRecord` | ~350 | ✓ | ✓ no socket |
| 09 | ✓ | ✓ | ✓ | provides `build_model` | ~220 | ✓ | ✓; one `live`, not run |
| 10 | ✓ | ✓ | ✓ | implements `WorkspaceProvider` | ~400 | ✓ | offline + `docker` marker |
| 11 | ✓ | ✓ | ✓ | implements `Operation` | ~300 | ✓ | ✓ fakes |
| 12 | ✓ | ✓ | ✓ | consumes seams only | ~450 | ✓ | ✓ Hypothesis |
| 13 | ✓ | ✓ | ✓ | implements `AgentRuntime` | ~450 | ✓ | `TestModel`/`FunctionModel` |
| 14 | ✓ | ✓ | ✓ | fakes for runtime, ops, workspace | ~350 | ✓ | ✓ |
| 15 | ✓ | ✓ | ✓ | fakes for all components | ~450 | ✓ | ✓ incl. subprocess kill |
| 16 | ✓ | ✓ (commands + their wiring) | ✓ | consumes `Engine` | ~350 | ✓ | `CliRunner`, scripted |
| 17 | ✓ | ✓ | ✓ | real components | tests | ✓ | scripted; `docker` marker |
| 18 | ✓ | ✓ | ✓ | n/a | docs | ✓ | repository tests |

Rules: 1 one sub-agent, branch and PR; 2 one job and at most one ADR; 3 exclusive file
ownership within a wave; 4 seams exist before behaviour; 5 under about 600 changed lines;
6 goal, paths, seams, tests and dependencies listed; 7 deterministic, offline tests.
Independent verification is WP-19; the ask-first list is section 7.

## 13. Risks: where the cut is most likely wrong

1. **The engine is cut in three (planning, stage execution, durable workflow) before DBOS has
   been exercised.** If explicit resume or `recv` across process exit behaves differently from
   the source reading, the pure state machine may not map onto workflow replay. Detection:
   WP-15's first test is that spike. Re-cut: pull the spike forward as a test-only WP in wave 1
   and, if it fails, switch decision 4 to one workflow per segment and merge WP-14 into WP-15,
   re-splitting by "straight-through path" and "waits and recovery".
2. **Runtime and sandbox are separate packages joined by a `WorkspaceHandle` re-attached by
   reference.** That relies on alpha Harness behaviour (attach by ref; its PID tmpfs working
   with `--read-only --user`) and puts Pydantic AI in two packages. Re-cut: fold the sandbox
   into `conveyor.runtime` as a module sequenced after WP-13 (one owner of `pydantic_ai`), or,
   if the Harness backend cannot be hardened, a thin Conveyor `docker`-CLI backend in WP-10.
3. **The seams (WP-05) are written before any implementation.** `StageInput` and `AgentRuntime`
   are consumed by six WPs; a wrong shape stalls wave 3. Mitigation: any seam change stops the
   WP and goes to the orchestrator, who changes it once and resumes the affected WPs. Re-cut if it happens twice: insert a
   walking-skeleton WP after WP-05 (fake-backed engine loop over the reference factory) and
   delay wave 3 until it passes. The WP-04/WP-06 split is the same kind of risk in miniature;
   merge them if the records churn.

Also noted: Docker tests can only be proven in CI's `docker` job (no daemon in this
environment), and on Windows the workspace-tool tests skip, so Windows coverage will sit a
little lower than Linux (still expected above 90%).

## 14. How the plan is run

- **Briefs.** Each sub-agent gets a self-contained brief: its WP entry, files to read first, the
  seams it consumes and provides, owned paths, the cutting rules above and `AGENTS.md`, and the report
  format (PR link, `make check` result, coverage, deviations, open questions).
- **Isolation.** Each sub-agent runs in its own git worktree on its own branch off
  `origin/milestone/factory-execution`, and opens a draft PR against that branch.
- **Waves.** All WPs of a wave launch together. Before a WP is reported done a separate review
  sub-agent checks its diff (correctness, `AGENTS.md` boundaries, layering, determinism,
  docstrings, owned paths). At each wave end the orchestrator stops, reports the PRs, what each verified,
  deviations and the next wave, updates the status table above, and waits for the owner to confirm
  the merge.
- **Commit window.** No commit, push or PR before 18:15 UK on weekdays
  (`TZ=Europe/London date`); earlier work stays uncommitted in its worktree.
- **Rules.** `AGENTS.md` in full; no force-push, `--no-verify`, hand-edited lockfiles or
  schemas; never weaken a check; anything beyond section 7 stops and asks.

## 15. Verification

Per WP: `make check` plus its named acceptance tests. Per wave: `make check` on the integration
branch after merges. Milestone: WP-19 runs the ten definition-of-done items and the four-step
walkthrough (publish four agents, `conveyor run start prd-to-pr --input inputs/sample-prd.yaml
--repo <sample>`, close the terminal, `conveyor run approve`, `conveyor run show`) with scripted
models; the `docker` CI job proves the no-network sandbox; CI green on all three OS runners.
