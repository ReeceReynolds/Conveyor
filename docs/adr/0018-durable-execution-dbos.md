# 0018. Durable execution: DBOS Transact, one step per stage attempt, waits by process exit

- Status: Accepted
- Date: 2026-11-11

## Context

The project overview requires every run to be a durable workflow: "each completed stage is
checkpointed, so a crash or restart resumes the run at the last completed stage rather than
starting again, and a human gate can wait for days without holding a process open". It names
DBOS Transact, which runs durable workflows inside the Python process with no extra server.

`dbos` 3.5.0 (MIT, `Requires-Python >=3.10`) was checked against the published wheel on
2026-11-11. These facts shape this decision:

- It supports a SQLite system database, so it can run locally with nothing else installed.
- Parking a waiting workflow without holding a thread (`DBOS.recv` or `DBOS.sleep` with
  `suspend=True`) is available only in Transact Enterprise. In the open-source edition a
  workflow that waits holds a thread in a live process.
- When DBOS launches, it recovers pending workflows filtered by executor ID and application
  version.
- `DBOS.resume_workflow` does not run the workflow in the calling process. It re-enqueues it,
  by default on DBOS's internal queue. Every launched process polls that queue whatever its
  executor ID, and dequeuing checks only the application version and the queue name.
- The default `application_version` is an MD5 hash of the workflow sources, the `dbos` version
  and the application name. Any change to any of them, including a `dbos` patch release, changes
  it.
- The timeout of `DBOS.recv` is durable: the wait is recorded as a sleep, 60 seconds by default.
  A replayed `recv` returns the recorded message, or `None`, at once.
- The Python interpreter waits for executor threads before it exits, so a process with a
  workflow still waiting in `recv` does not exit until DBOS is shut down.
- Pydantic AI has its own DBOS integration, which makes each model call a durable step. Its
  current form is the `DBOSDurability` capability; the older `DBOSAgent` wrapper is deprecated.

A human gate that holds a process open for days is not acceptable, so the open-source edition
cannot wait at a gate the way the overview describes. This is the highest technical risk in
Milestone 3.

## Decision

**Use `dbos` 3.5 (`dbos>=3.5`) in one package.** `conveyor.engine` is the only package that
imports `dbos` ([ADR 0023](0023-execution-package-layering.md)).

**The system database is its own file, `.conveyor/dbos.sqlite`.** DBOS owns that schema. It is
never part of Conveyor's Alembic chain ([ADR 0012](0012-storage.md)) and Conveyor never reads its
tables. Conveyor's own records of runs and attempts stay in `conveyor.db`.

**One run is one DBOS workflow, and one durable step is one stage attempt.** A step is an agent
run, an operation or a gate decision. A completed step is never executed again: on replay DBOS
returns its recorded result.

**Gates and escalation wait by the process exiting.** When the run reaches a human gate, or a
rework loop runs out of iterations, the run is marked `waiting` or `escalated` and the workflow
waits in `DBOS.recv` on the run's topic. The CLI process then shuts DBOS down and exits cleanly.
Because the `recv` timeout is durable and a replayed `recv` returns at once, the workflow loops
while `recv` returns `None`, and a decision is always sent before the workflow is resumed.

**Escalation parks like a gate.** On an `escalated` run, `approve` accepts the newest output of
the rework loop and the run continues at the stage after the one that escalated; the rejecting
stage does not run again ([ADR 0016](0016-run-model-and-handoff-routing.md)). The rejected
attempt keeps the status `rejected`, and the override is recorded as a decision on the run.
`reject` ends the run as `rejected`.

**Every resume is explicit, and only the process that asked for it can run it.** Each Conveyor
process launches DBOS with a unique executor ID and a pinned `application_version`, so nothing
is recovered at launch by a process that did not ask for it. Because `resume_workflow` goes
through a queue that any process may poll, Conveyor also:

- gives each run its own queue name;
- has `approve`, `reject` and `resume` call `DBOS.send(run_id, decision, topic)`, then
  `DBOS.resume_workflow(run_id, queue_name=<run queue>)`, then wait on the workflow handle in the
  foreground of that command's process;
- has each process listen only to its own run's queue (`DBOS.listen_queues`);
- takes the run lock in the workflow's first step, so a process that dequeues a run without
  holding its lock cannot drive it.

**The application version is a constant, `conveyor-run-1`, owned by `conveyor.engine`**, not
DBOS's default, which a Conveyor upgrade or even a `dbos` patch release would change, stranding
every run in flight. It is bumped only when the workflow's step order changes incompatibly.
Compatible changes to the workflow use `DBOS.patch()` and keep the version. Before acting,
`approve`, `reject` and `resume` read the application version recorded for the run. If it
differs from the current one, they refuse with a clear error that names the version needed,
rather than enqueue a run that no process will pick up.

**`conveyor run resume` continues a run after a crash.** It replays the recorded steps, marks the
attempt that was in flight `interrupted`, resets the workspace to the commit that attempt
started from, and re-runs only that stage. Completed stages are not re-run and their models are
not called again.

**A per-run file lock stops two processes driving one run.** A process that cannot take the
lock refuses to act on the run.

**Status values.**

| Record | Values |
|---|---|
| Run | `pending`, `running`, `waiting`, `escalated`, `completed`, `rejected`, `failed` |
| Agent or operation attempt | `running`, `succeeded`, `rejected`, `failed`, `interrupted` |
| Gate attempt | `waiting`, `approved`, `rejected` |

A run is `waiting` at a human gate and `escalated` when a rework loop has run out; both park the
workflow. A run is `rejected` when a person rejects it at a gate or after escalation. An attempt
is `rejected` when its output has `decision: "reject"`
([ADR 0016](0016-run-model-and-handoff-routing.md)) and `interrupted` when the process ended
while it was running.

**The spike proves the design first.** Milestone 3's durable-workflow work package starts with a
test that the primary design works: start, park at the gate, tear DBOS down, relaunch, approve,
complete. It must also prove that:

- the parking process exits cleanly once DBOS is shut down;
- a `recv` that times out returns `None` and the workflow keeps waiting;
- a decision sent before the resume is the one the workflow receives;
- an unrelated live Conveyor process does not dequeue the resumed run.

**The fallback, if `recv` plus explicit resume misbehaves:** one DBOS workflow per segment of the
run between waits. A gate then ends a workflow, and the decision starts the next one from the
recorded state. The work package switches to it if the spike cannot be made to pass.

**Pydantic AI's DBOS integration is not used in M3.** The durable unit is the stage attempt,
which is what the milestone needs, and keeping model calls out of DBOS keeps `dbos` in one
package. Using `DBOSDurability` for finer-grained resume inside a stage is a follow-up.

## Alternatives considered

- **Share Conveyor's database with DBOS.** DBOS's tables would sit beside Conveyor's, so the two
  schemas would be coupled, and DBOS's frequent checkpoint writes would contend for SQLite's one
  write lock with Conveyor's own writes.
- **Pydantic AI's DBOS capability (`DBOSDurability`).** A crash in the middle of a long agent
  run would resume from the last model call instead of the start of the stage. It would put
  `dbos` in two packages, and DBOS's replay constraints would apply inside agent code.
- **Transact Enterprise's suspended waits.** They would let a gate wait without a process, but
  Conveyor is open source and local-first, and cannot depend on a commercial edition.
- **Keep the process open at a gate.** This is what the open-source edition does by default, and
  it is what the overview rules out.
- **DBOS's default executor ID, application version and internal queue.** Every process would
  share the executor ID, so any command could recover any pending run at launch; the default
  application version changes with the code and the `dbos` version, so runs started before an
  upgrade would not be recovered after it; and any live process could dequeue a resumed run.
- **One workflow per segment between waits.** Kept as the fallback above. It needs Conveyor to
  carry state between workflows itself, which is the work DBOS is adopted to do.

## Consequences

- A gate can wait for days with no process running. The cost is that nothing happens on its own
  after a crash: the person runs `conveyor run resume`.
- A crash in the middle of a stage repeats that stage, including its model calls. Its cost is
  paid twice. The workspace reset makes the repeat start from the same files.
- `.conveyor/dbos.sqlite` is new on-disk state, ignored by Git through `.conveyor/.gitignore`.
- `dbos` brings these transitive runtime dependencies:
  - `psycopg[binary]`, new at runtime (until now development-only, ADR 0012);
  - `sqlalchemy[asyncio]`, the async extra of a library storage already uses;
  - `pyyaml`, beside ruamel.yaml ([ADR 0009](0009-yaml-library.md)), which remains Conveyor's
    YAML library;
  - `click`, `croniter` and `python-dateutil`.

  Conveyor code outside `conveyor.storage` still does not import SQLAlchemy, and no Conveyor
  code imports the others.
- A run parked or crashed before the application version is bumped cannot be resumed by newer
  Conveyor code. It needs the Conveyor release that started it; `approve`, `reject` and `resume`
  say which version that is.
- Every change to the workflow code needs a decision: compatible, with `DBOS.patch()`, or
  incompatible, with a version bump. Getting it wrong replays old runs against steps in a
  different order.
- Postgres as a system database (the overview's "Postgres in production") is not configured in
  M3.
