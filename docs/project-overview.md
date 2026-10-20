# Conveyor — Project Overview

## What Conveyor Is

Conveyor is an open-source foundation layer for harness engineering: building agent-driven software factories.

It does not ship agents. It ships the infrastructure an engineer uses to define a factory, build the specialised agents that work inside it, evaluate each agent against a human-defined quality bar, version every change, and see exactly how those changes affect what the factory produces.

## The Thesis

Software engineering is changing. Models are now strong enough to do most of the work of delivery, but without structure they drift: they make up process, skip steps and produce output nobody asked for. The leverage has moved from writing code to designing the system that guides agents to a reliable end state. The industry calls this discipline **harness engineering**: building the process, context, tools and checks around agents so they produce reliable work.

Conveyor's take on harness engineering:

**Humans set the sat nav. Agents drive the route.**

The sat nav is the harness. The human sets the destination (the factory outcome), plots the route (stages, each with a single responsibility) and defines what counts as being on course (the quality gates). Agents do the driving. When the route is wrong, the human re-plans it from evidence rather than grabbing the wheel.

The engineer's job becomes defining the process, giving each step a single responsibility, setting the quality bar for that step, and improving the whole system based on evidence. Conveyor is the tooling for that job: it makes the harness explicit, versioned and measurable.

## Why This Project Exists

Conveyor is built in public to explore and demonstrate this shift in practice, and to show what industry-standard engineering looks like when applied to agent infrastructure. The goal is not a broad platform for everyone. The goal is a credible, well-engineered foundation, a reference factory that runs end to end, and published evidence of agents measurably improving the factory's output over time.

## The Factory Model

Every factory in Conveyor is built from the same five levels, from the smallest unit up to the complete process. Each level is made of the one below it. This is how a factory is built, read, versioned and improved.

| Level | What it is | Examples |
|---|---|---|
| **Primitives** | The smallest units that cannot be broken down further. | An instruction, a model setting, a tool, a permission, a contract, an eval check, an eval case. |
| **Components** | Groups of primitives with one job. | An eval suite (cases, checks and a pass threshold), a toolkit (tools and their permissions), an input/output contract pair, a model profile (model and its parameters). |
| **Blocks** | The three parts every agent is made of. | **Brief** (instructions and contracts: what the agent does and what it must produce), **Capabilities** (model profile and toolkit: what it can use) and **Quality Gate** (eval suite and thresholds: what good looks like). |
| **Agents** | A complete, reusable worker: one Brief, one set of Capabilities and one Quality Gate, versioned as a single unit. | `requirements-analyst`, `task-planner`, `implementer`, `code-reviewer` |
| **Factory** | Agents placed into an ordered process alongside deterministic operations and human gates, with triggers, handoffs, rework loops and an outcome definition. | `prd-to-pr` |

A **run** is the factory processing one real input and producing real artifacts.

### Why this structure matters

- **Read top down.** Anyone can read a factory as a sequence of agents, open an agent to see its three blocks, and open a block to see the exact primitives inside it. Nothing is hidden in an unstructured prompt.
- **Improve bottom up.** Changes happen at the primitive level (a sentence in an instruction, a model setting, an eval threshold) and their effect rolls up through the agent to the factory outcome.
- **Measure at the right level.** Quality is judged by evals at the agent level and by outcome scoring at the factory level.
- **Version at the right level.** Each agent is versioned as one unit, and its diff is expressed in terms of the blocks and primitives that changed, e.g. *"implementer v4 → v5: Capabilities changed; model profile changed; model switched."*
- **Reuse cleanly.** Primitives and components (contracts, toolkits, eval checks) can be shared across agents. Agents can be reused across factories.

## Core Concepts

| Concept | Level | What it is |
|---|---|---|
| **Factory** | Factory | A human-defined process that turns an input into an intended outcome. |
| **Stage** | Factory | One position in the factory. Holds an agent, a deterministic operation (e.g. fetch a file, run tests) or a human gate. |
| **Trigger** | Factory | What starts a factory: an external event or a manual start. Inside the factory, a stage starts when its upstream artifact is ready. |
| **Agent** | Agent | A purpose-built worker for one stage, made of a Brief, Capabilities and a Quality Gate. |
| **Agent Version** | Agent | An immutable, content-addressed snapshot of an agent's full definition, with author, timestamp, change message and diff. |
| **Brief, Capabilities, Quality Gate** | Block | The three blocks of every agent. |
| **Eval Suite, Toolkit, Contract Pair, Model Profile** | Component | Groups of primitives with one job. |
| **Instruction, Model Setting, Tool, Permission, Contract, Eval Check, Eval Case** | Primitive | The units everything else is built from. |
| **Run** | Execution | One durable execution of a factory. Records the exact agent versions used, every artifact, trace, eval result and the factory outcome. Survives restarts and can wait at human gates. |
| **Artifact** | Execution | The typed output of a stage, passed to the next. Immutable, content-addressed and stored with the run. |
| **Change Set** | Execution | The agent version changes between one run and the run before it: which agents changed, who changed them, and the diffs. |
| **Factory Outcome** | Execution | The owner-defined measure of the factory's end output for a run. What the whole system is ultimately optimised for. |

## How It Works

**Who decides?**
Humans. A human designs the factory process, creates an agent for each step, scopes what that agent is focused on, defines the shape of its output, and writes its evals. Every change a human makes to an agent is versioned.

**How does work move through the factory?**
As a handoff, not a negotiation. A human has a process in mind, for example taking a PRD through to a PR. Each step has one agent: one turns the PRD into technical requirements, the next breaks requirements into actionable tasks, the next implements, the next reviews. One agent's output is the next agent's input. Agents never coordinate outside the process the human defined.

**What happens when a step isn't good enough?**
Two things can stop a handoff. An agent can fail its Quality Gate, or a downstream stage (such as code review) can send work back. Rework loops are explicit and bounded: the factory definition sets which stage can return work to which, how many iterations are allowed, and when the run escalates to a human.

**What happens if something crashes?**
Every run is a durable workflow. Each completed stage is checkpointed, so a crash or restart resumes the run at the last completed stage rather than starting again, and a human gate can wait for days without holding a process open.

**What can an agent touch?**
Only what its Capabilities declare. Each agent's toolkit lists its permitted tools, file paths, network access and secrets. Anything not declared is unavailable to it. Agents with file or shell access run in a sandbox with no network by default, and permissions are enforced by the runtime and the sandbox, never by the prompt.

**How is quality judged?**
By the people who own the work, never by Conveyor. The agent creator defines each agent's Quality Gate. The factory owner defines what a good factory outcome is. Conveyor provides the machinery to define, run, record and compare those judgements, and makes no assumptions about what they should be.

**What is being optimised?**
The output of the factory. Prompts, models, evals and logs all exist to serve one question: is the factory producing better results than it was before? Humans adjust individual agents based on the factory's output, and Conveyor shows whether each adjustment helped.

## Core Capabilities

### 1. Factory Definition and Execution

Factories are defined in declarative, human-readable configuration: stages, the agent, operation or human gate at each stage, entry triggers (external event or manual), handoffs, rework loops and outcome scorers.

Execution is deterministic in structure. The graph is fixed by the human; only the data flowing through it varies. Runs execute as durable workflows (DBOS), so they survive restarts and can pause at human gates.

### 2. Agent Registry and Version Control

Agents are authored as files and published into Conveyor's own registry.

- An agent lives in a folder that mirrors its blocks: `agent.yaml` (Capabilities and contracts), `prompt.md` (Brief) and `evals/` (Quality Gate).
- `conveyor agent publish <name> -m "message"` validates the agent and creates an immutable, content-addressed version, recording author, timestamp, message and a full diff against the previous version.
- The diff is structured by the factory model, showing which blocks, components and primitives changed: instructions, model, model parameters, tools, permissions, contracts or eval definitions.
- Factories reference agents by name. Each run pins the exact resolved versions, so every outcome traces back to precise configuration.

Owning the registry, rather than relying on Git history alone, gives Conveyor stable version IDs to link runs, change sets, evals and outcomes to. Because definitions are plain files, they can still live in Git and be reviewed in pull requests.

### 3. Agent Evals

Evals form each agent's Quality Gate and are defined by its creator. Conveyor uses Pydantic Evals as the engine and provides the machinery every eval suite plugs into, not the judgement:

- **Pluggable checks:** creators write checks as code, model-graded assessments, schema assertions or trajectory checks over the agent's tool calls.
- **Quality gates:** creator-set pass thresholds that decide whether an agent's output moves on during a run.
- **Case capture:** any logged run, good or bad, can be promoted into an eval case for that agent.
- **Repeated runs:** cases can run N times, set by the creator, because agents are non-deterministic. Pass rates are reported with a confidence interval.
- **Baseline comparison:** publishing a new agent version runs its suite against the previous version and shows the difference before it is promoted.

### 4. Factory Logs

Every run produces a scannable timeline that follows the factory model: the run, then one row per stage showing agent and version, status, gate result, duration and cost. Each row expands into full detail: inputs, outputs, model calls, tool calls, eval results, retries, rework loops and errors.

Logs are structured OpenTelemetry traces using the GenAI semantic conventions (pinned to a specific version, since they are still in Development status), not text dumps, so they can be filtered, compared across runs, linked to versions and outcomes, and exported to any standard observability backend.

### 5. Factory Outcome and Change Impact

This is the improvement loop, and the part that ties everything else together.

The factory owner defines how outcomes are scored by registering outcome scorers: code, model-graded or human review. Conveyor records every score against the run and never prescribes what to measure.

Because every run pins its agent versions, Conveyor can answer the question that matters most:

**"I changed agent X. What did that do to the factory's output?"**

For any change set, Conveyor links together:

- each agent version change, with its author, message and diff
- each changed agent's eval results, before and after
- factory outcome scores, before and after
- cost and duration, before and after

Changing an agent's model is a version change like any other, so swapping models shows up in exactly the same view.

**Execute → Evaluate → Inspect → Change → Compare → Repeat**

### 6. Factory Overview

A local web interface where the factory owner sees runs, outputs and change sets in one place. Navigation follows the factory model, so the owner can drill from the factory, to an agent, to a block, down to the exact primitive that changed.

Conveyor does not decide whether a change "worked". It lays runs and change sets out side by side so the owner can judge, and the owner decides how many runs they need before trusting a trend.

- **Factory Overview:** runs over time with their outcome scores, and a marker wherever a change set landed.
- **Change Set Detail:** what changed, who changed it, the diffs, the eval movement and the outcome movement.
- **Run Detail:** the run's timeline and artifacts.
- **Agent Detail:** an agent's blocks, version history, eval history and the runs it took part in.

## Model Selection

Each agent chooses its own model as part of its Capabilities. Model ID, parameters and provider routing are part of the agent's versioned definition.

- Supported providers: OpenRouter (default), Anthropic and OpenAI, plus anything Pydantic AI supports.
- A model profile can pin which upstream providers OpenRouter may use and disable fallbacks, so eval and baseline runs are not skewed by silent provider changes.
- Credentials are configured per provider, never stored in agent definitions.
- Different agents in the same factory can use different providers and models.

## Technical Stack

Conveyor follows industry-standard packages and tooling throughout. It builds what is genuinely new (orchestration, the agent registry, quality gates, change impact) and adopts established tools for everything else. The rationale for each choice lives in `docs/adr/`.

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.14 (3.15 added to CI once dependencies support it) | The default language for AI engineering |
| Packaging and environments | uv workspace, `pyproject.toml`, committed `uv.lock` | Current standard for fast, reproducible Python projects |
| Agent execution | Pydantic AI v2, behind a small `AgentRuntime` interface | Model-agnostic, typed structured output, first-party MCP, OpenTelemetry and durable execution; its capability primitive matches the Capabilities block |
| Coding agents | Pydantic AI Harness (Coder, Guardrails, Spend Limits) | First-party file, shell, guardrail and budget capabilities instead of hand-built tools |
| Durable execution | DBOS Transact (SQLite locally, Postgres in production) | In-process durable workflows: runs survive restarts and wait at human gates with no extra server |
| Tools | Model Context Protocol (MCP), 2026-07-28 revision | The industry standard for exposing tools to agents |
| Contracts | Pydantic v2 models, exported to JSON Schema 2020-12 | Pydantic is the source of truth and plugs straight into typed outputs; JSON Schema is stored with each agent version for diffing and language-neutral use |
| Configuration | YAML parsed into strict Pydantic models; published JSON Schemas | Human-readable, validated, with editor autocomplete |
| Evals | Pydantic Evals as the engine | Code-first, typed datasets, LLM judges and trajectory checks over traces; Conveyor adds gates, repeats, baselines and case capture |
| Observability | OpenTelemetry, GenAI semantic conventions (pinned); local span store plus OTLP export | Vendor-neutral traces any backend can read (Phoenix, Langfuse, Logfire, Jaeger) |
| Cost tracking | Provider-reported cost, `genai-prices` as fallback | Real spend per call, per stage and per run |
| Storage | SQLite (WAL) via SQLAlchemy 2.0, Alembic migrations; content-addressed artifact store | Local-first, with Postgres tested in CI |
| CLI | Typer | Typed, well-documented CLI framework |
| API | FastAPI, OpenAPI, Server-Sent Events | Serves the local web interface and streams live run progress |
| Web interface | React, TypeScript, Vite, TanStack Router and Query, shadcn/ui; typed client generated from OpenAPI | Standard stack for a typed, component-based frontend; bundled into the Python package |
| Workspace isolation | Hardened Docker containers (no network by default, non-root, read-only root); gVisor optional | Standard isolation for code-executing agents |
| Security | OWASP Top 10 for Agentic Applications as the threat model | Shared industry taxonomy for agent risks |
| Testing | pytest, Pydantic AI `TestModel`, recorded cassettes, inline-snapshot, Hypothesis, testcontainers; nightly live evals with a spend cap | Fast, deterministic CI with real-model checks kept separate |
| Quality | Ruff, Pyright (strict), pre-commit, GitHub Actions | Linting, strict typing, tests and CI on every change |
| Releases | Semantic versioning, Conventional Commits, release-please, PyPI Trusted Publishing | Predictable, readable release history with no long-lived publishing tokens |

### Engineering Principles

- Clear separation between orchestration, agent execution, evals, artifacts, the registry, observability and the interface.
- Human-readable, Git-friendly configuration.
- Typed contracts between every stage.
- Immutable runs, artifacts and agent versions.
- Durable by default: every run can stop and resume without losing completed work.
- Containment over instruction: permissions are enforced by the runtime and sandbox, never by the prompt.
- Explicit permissions and secret handling per agent.
- Local-first: runs on one machine with no hosted dependencies.
- Adopt before building: use the established tool unless Conveyor's core purpose requires something new.
- Extensible without premature abstraction: one implementation of each thing until a second is genuinely needed.

## Reference Factory: PRD → PR

Lives in `/examples`. It exists to prove the infrastructure works end to end, not to be the product.

| # | Stage | Type | Output |
|---|---|---|---|
| 1 | Fetch PRD | Operation | PRD document |
| 2 | Requirements | Agent | Technical requirements |
| 3 | Task breakdown | Agent | Ordered, actionable tasks |
| 4 | Implementation | Agent | Code changes on a branch |
| 5 | Validation | Operation | Test and lint results |
| 6 | Code review | Agent | Review verdict; can return work to stage 4 |
| 7 | Approval | Human gate | Approve or reject the PR |

**Example outcome scoring (chosen by this factory's owner):** tests pass, the PR is approved, and a reviewer quality score.

## Illustrative Configuration

```yaml
# factories/prd-to-pr.yaml  (Factory)
name: prd-to-pr
trigger:
  manual: true
  events: [github.issue.labelled:ready-for-build]
stages:
  - id: requirements
    agent: requirements-analyst
  - id: tasks
    agent: task-planner
  - id: implement
    agent: implementer
  - id: validate
    operation: run-tests
  - id: review
    agent: code-reviewer
    on_reject: { return_to: implement, max_iterations: 3, then: escalate }
  - id: approve
    human_gate: true
outcome:
  scorers:
    - scorers.tests_pass
    - scorers.pr_approved
    - { human_review: { scale: 1-5, optional: true } }
```

```yaml
# agents/task-planner/agent.yaml  (Agent)
name: task-planner

brief:                       # Block
  instructions: prompt.md
  input: contracts.TechnicalRequirements
  output: contracts.TaskList

capabilities:                # Block
  model:
    provider: openrouter
    id: anthropic/claude-sonnet
    temperature: 0.2
    routing: { only: [anthropic], allow_fallbacks: false }
  tools: []
  permissions: { network: false, secrets: [] }

quality_gate:                # Block
  suite: evals/
  min_pass_rate: 0.9
  repeats: 3
```

```python
# contracts.py  (Primitives)
from pydantic import BaseModel


class Task(BaseModel):
    id: str
    title: str
    acceptance_criteria: list[str]
    depends_on: list[str] = []


class TaskList(BaseModel):
    tasks: list[Task]
```

## Repository Layout

```
conveyor/
├── src/conveyor/        # Python package: orchestration, registry, evals, outcomes, API, CLI
├── ui/                  # React + TypeScript web interface (built into the Python package)
├── examples/prd-to-pr/  # Reference factory, agents, contracts and scorers
├── docs/                # Concepts, guides, threat model and architecture decision records (docs/adr/)
├── tests/
└── AGENTS.md            # Guidance for coding agents working on Conveyor itself
```

## Scope

**In the MVP**

- The factory model: primitives, components, blocks, agents and factories as first-class, versioned structures
- Factory definition and local, durable execution, including bounded rework loops and human gates
- Agent registry with publish, history and structured diffs
- Per-agent eval machinery: pluggable checks, gates, case capture, repeated runs and baseline comparison
- OpenTelemetry-based run logs with a scannable timeline and per-call cost
- Owner-defined outcome scorers and change set impact
- Sandboxed execution for agents with file or shell access
- The local web interface: Factory Overview, Run Detail, Change Set Detail and Agent Detail
- OpenRouter as the default provider, with Anthropic and OpenAI available
- The PRD → PR reference factory

**Not in the MVP**

- Visual factory editors
- Distributed or parallel execution
- Hosted service, multi-user accounts or access control
- Branching factory graphs beyond bounded rework loops
- A library of pre-built agents, evals or outcome scorers
- An LLM gateway, vector database or agent-to-agent protocol

## Definition of Success

An engineer can define a factory, build specialised agents, connect them into a controlled pipeline, set a quality bar for each one, run the factory, scan what happened, change an agent, and see what that change did to the factory's output.

For this project specifically, success is a public, reproducible example built to recognisable industry standards: the reference factory running end to end, and at least one change set with a traceable before and after across its diffs, its evals and the factory outcome.

Success is measured by the quality and reliability of what the factory produces, not by the number of agents or the volume of code generated.

## Product Philosophy

**Humans engineer the factory. Agents execute the work. Conveyor provides the structure, evidence and feedback loop that make the factory better.**
