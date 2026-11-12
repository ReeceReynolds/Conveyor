# 0016. Run model and handoff routing: inputs selected by contract, one envelope for rework

- Status: Accepted
- Date: 2026-11-11

## Context

Milestone 3 makes `conveyor run` execute a factory. Before any stage can run, three things must
be fixed: what a run records, which artifact each stage receives, and what a stage receives when
work is sent back to it.

"One agent's output is the next agent's input" (the project overview) does not hold for the
reference factory as written. Its stages are `fetch-prd`, `requirements`, `tasks`, `implement`,
`validate`, `review`, `approve`. The stage before `review` is the operation `validate`, which
produces test results, but the `code-reviewer` agent's `brief.input` is `contracts.CodeChanges`,
which `implement` produced two stages earlier. The reviewer also needs the test results. A rule
based on position cannot express that.

Rework has the same problem. When `review` rejects, `implement` runs again. Its contract input
is still a `TaskList`, but it also needs the verdict and its own previous work, and
`brief.input` names exactly one contract ([ADR 0008](0008-contracts-and-configuration.md)).

The pre-M3 sweep also asked, in its "Notes for M3", for a decision on per-file objects or a
collector before run artifacts share the object store with agent snapshots.

## Decision

**A run is one execution of a factory on one input.** It records the factory file by digest,
the pinned agent versions ([ADR 0017](0017-run-version-pinning.md)), every execution of every
stage, every artifact and its spans ([ADR 0022](0022-observability-and-cost.md)). The status
values of runs and attempts are listed in [ADR 0018](0018-durable-execution-dbos.md).

**Every execution of a stage is a `stage_attempts` row** with two counters. `attempt` numbers
the executions of that stage within the run, so a re-run after a crash or a rework pass is a new
row, never an overwrite. `iteration` records which pass of a rework loop the execution belongs
to. Rows are keyed by run, stage and attempt, so writing the same attempt twice is a no-op.

**An artifact is the typed output of one stage attempt.** It is validated against its contract,
serialised as RFC 8785 canonical JSON (the scheme and the `rfc8785` package of
[ADR 0013](0013-agent-version-identity.md)) and written to the existing content-addressed object
store ([ADR 0012](0012-storage.md)). The run refers to it by sha256 digest and contract.
Artifacts are immutable. Identical content is stored once.

**No collector and no per-file objects in M3.** The sweep's concern was artifacts "far larger
than snapshots". M3's artifacts are not: each is one small JSON document (a PRD, a task list, a
summary of changes with commit SHAs, test results with an output tail, a verdict). The code an
agent writes lives in Git, in the run's workspace and its exported bundle
([ADR 0021](0021-workspace-sandbox-and-tools.md)), not in the object store. Objects are still
never deleted, as ADR 0012 records.

**A stage's input is selected by contract, not by position.** The input of a stage is the most
recent artifact in the run whose contract equals the stage's declared input contract. Agents
declare their contracts in `agent.yaml` (`brief.input`, `brief.output`). Operations declare
theirs in code or from their parameters ([ADR 0019](0019-operations.md)).

**Contract identity is the reference as written.** Two contracts are equal for routing when their
dotted references are equal, as written in `brief.input` or `brief.output`, or in an operation's
`with: output`. A Conveyor-owned contract, such as `TestResults`, is identified by its fully
qualified built-in name.

**Context artifacts.** Artifacts produced after the input artifact and before the stage runs are
passed with it as read-only context. In the reference factory `review` receives the latest
`CodeChanges` as its input and the `TestResults` from `validate` as context.

**Preflight proves the routing before any model call.** For every stage, an earlier stage must
produce its input contract. A factory that fails this check does not start.

**`StageInput` is the envelope every stage receives.** It is owned by Conveyor and holds the
primary input, the context artifacts and, on rework, a `rework` block. `brief.input` still
validates only the primary input, so the contracts format and `agent.yaml` do not change.

**Rework uses the same envelope.** When a stage rejects, the `return_to` stage runs again and
receives:

- its original input, unchanged and with the same digest;
- a `rework` block: the iteration, the rejecting stage and the verdict artifact;
- context: its own previous output and anything produced after it, such as later test results.

Rework context carries only the latest iteration's artifacts, never those of earlier passes.

The run then continues forward from the `return_to` stage, so in the reference factory
`validate` and `review` run again on the new `CodeChanges`.

**A stage rejects when its output has `decision: "reject"`.** Any agent stage with `on_reject`
must have an output contract with a required `decision` field, with no default, whose allowed
values are exactly `approve` and `reject` (a `Literal` or a `StrEnum`). Preflight checks this
against the output schema stored in the pinned agent version. The reference factory's
`ReviewVerdict` already conforms.

**`on_reject` is for agent stages only in M3.** On an operation or gate stage it is a preflight
error. The factory model still accepts it, so the configuration format does not change.

**`max_iterations` counts returns of work.** With `max_iterations: 3` the first three rejections
each send the work back, and the fourth rejection escalates the run to a person (ADR 0018). The
rework loop reuses the run's pinned agent versions.

**Approving an escalation accepts the loop's latest output.** The newest output of the rework
loop (in the reference factory, the newest `CodeChanges`) is accepted, and the run continues at
the stage after the one that escalated (the `approve` gate in `prd-to-pr`). The rejecting stage
does not run again. Its rejected attempt keeps the status `rejected`; the person's override is
recorded separately, as a decision on the run, which the run schema must hold.

## Alternatives considered

- **Explicit `inputs:` per stage in the factory file.** Every stage would list the stages or
  contracts it reads. This adds configuration surface for what the contracts already say, and
  the two can disagree.
- **Position only: a stage receives the previous stage's output.** This is the overview's
  wording, and it cannot give `review` the code changes when `validate` sits between them.
- **A dedicated rework contract per agent.** The implementer would declare a second input
  contract that includes the verdict. This changes every agent's contract pair and the
  `agent.yaml` format, and each factory would need a contract for each loop.
- **Per-file objects or a collector for artifacts now.** Neither is needed while artifacts are
  small JSON documents. A collector also has to prove an object is unreferenced by every run and
  every agent version, which is work with no benefit yet.

## Consequences

- A factory author reorders or inserts stages without rewiring inputs, as long as each input
  contract is still produced earlier. The preflight check reports it when it is not.
- Two stages that produce the same contract are legal. The later one wins for any stage after
  it. A factory that needs to tell them apart needs distinct contracts.
- Everything a stage saw can be rebuilt from stored digests, which the eval case capture of a
  later milestone depends on.
- Rejection detection relies on a field name. An agent stage with `on_reject` whose output
  contract has no conforming `decision` field is refused at preflight, not discovered at run
  time.
- Routing compares references, not schemas: two references to the same class written
  differently are different contracts, and one reference whose class changed is still the same
  contract.
- Agents receive an envelope, not the bare contract instance. How the envelope is rendered for
  the model belongs to the runtime ([ADR 0020](0020-agent-runtime-pydantic-ai.md)).
- The object store grows with every run and nothing collects it. If a later milestone stores
  large artifacts, the sweep's question has to be answered again in a new ADR.
