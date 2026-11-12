# 0019. Operations: built-in, typed and configured with `with:` on the stage

- Status: Accepted
- Date: 2026-11-11

## Context

A factory stage holds an agent, an operation or a human gate. Until now an operation stage is a
bare slug (`operation: run-tests`) and nothing runs it. The reference factory has two:
`fetch-prd`, which produces the `PRD` the requirements agent reads, and `run-tests`, which tests
the implementer's work so the reviewer can see the results.

To route handoffs by contract ([ADR 0016](0016-run-model-and-handoff-routing.md)), an operation
must declare its input and output contracts the way an agent does. Each also needs settings:
which contract the PRD must satisfy, which test command to run and for how long. The factory
file has nowhere to put them.

## Decision

**Built-in operations live in a registry in a new package, `conveyor.operations`, keyed by
slug.** Each operation declares its input contract (or none) and its output contract, in code
or from its parameters, and a strict parameters model that forbids unknown fields. `fetch-prd`,
for example, takes its output contract from `with:`. An unknown slug or invalid parameters are
preflight errors, so a run never starts with them.

**Operation stages gain one optional field, `with:`.** It is a mapping of the operation's
parameters, validated by that operation's parameters model. In the factory model the field is
`OperationStage.with_`, since `with` is a Python keyword. This changes the configuration format,
and `schemas/factory.schema.json` is regenerated. `agent.yaml` does not change.

**The two built-ins in M3:**

- `fetch-prd` takes `with: {output: contracts.PRD}`. It reads the run's input file
  (`conveyor run start ... --input FILE`), validates it against the named contract and outputs
  it as an artifact. It has no input artifact. A file that violates the contract is reported
  with the position of the problem.
- `run-tests` takes `with: {command: [...], timeout_seconds: N}`. It needs no input artifact.
  It runs the command in the run's workspace and outputs `TestResults`.

**`TestResults` is a Conveyor-owned contract**, defined in `conveyor.operations`: the command's
exit code, whether the tests passed, the tail of the output, and the commit that was tested. In
the reference factory the reviewer receives it as context next to the `CodeChanges` it reviews.

**Operations reach the workspace only through the `Workspace` seam** that the engine hands them,
never by opening paths or containers themselves. `run-tests` therefore runs inside the same
sandbox as the agents ([ADR 0021](0021-workspace-sandbox-and-tools.md)).

**Operation configuration is pinned with the run.** The factory file is stored by digest with
the run, so the `with:` parameters of every stage are recorded exactly as they were.

## Alternatives considered

- **Separate `operations/<name>.yaml` files**, like agent folders. This adds a second new file
  type with its own schema and loader, for two built-ins whose settings fit in a few lines on
  the stage.
- **A project `operations.py` that defines operations as code.** It is not declarative: a person
  reading the factory file could not see what a stage does, and the settings could not be
  validated or shown in a schema.
- **Hard-coded settings per operation.** The test command and the PRD contract differ from
  project to project, so they cannot be fixed in Conveyor.

## Consequences

- Operations can be routed, preflighted and recorded exactly like agents.
- Adding an operation means adding code to `conveyor.operations`. Project-defined operations are
  not supported in M3.
- Every factory schema consumer sees the new optional `with:` key. Existing factory files stay
  valid.
- The reference factory's operation stages gain `with:` blocks.
- Fetching from GitHub, pushing branches and opening pull requests are future operations. They
  are the place where network access and tokens belong, not agents.
