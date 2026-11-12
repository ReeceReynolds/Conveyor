# 0017. A run pins the latest published version of every agent, and refuses unpublished edits

- Status: Accepted
- Date: 2026-11-11

## Context

The project overview says each run "pins the exact resolved versions, so every outcome traces
back to precise configuration". Change sets, eval baselines and the self-hosting plan all rely
on that. The registry ([ADR 0013](0013-agent-version-identity.md)) gives every published agent
an immutable snapshot and a content ID, and a factory file refers to agents by name only.

Two questions follow. Which version does a run use when the factory says `agent: implementer`?
And what happens when the agent folder on disk differs from what was last published, which is
the normal state while someone is editing an agent?

## Decision

**A run pins the latest published version of every agent the factory uses.** All pins are taken
at once, when the run starts and before any stage runs. They are stored with the run. Rework
passes and resumed runs reuse the pins and never look at the registry's latest version again.

**A run refuses to start if any agent is not ready.** An agent is not ready when it has no
published version, or when its working copy differs from its latest published version. The
error names every such agent and the fix, `conveyor agent publish <name> -m "<message>"`. All
agents are checked and reported together.

**Agents are built from the stored snapshot, never from the working copy.** The instructions,
model profile, tools, permissions and contract schemas a stage runs with are those of the
pinned `AgentSnapshot`.

**Contract classes are resolved from the project at each stage, and checked against the pin.**
A snapshot stores the JSON Schemas of its contracts, not their Python source
([ADR 0011](0011-contract-resolution.md)). Typed output needs the Pydantic class, so the stage
resolves it from the project and compares its schema with the snapshot's. If they are not
equal the stage fails.

**There is no override flag in M3.** A run cannot be started against a working copy or an older
version.

The factory file itself is stored by digest with the run ([ADR 0019](0019-operations.md)), so
the stage list and operation configuration are pinned as well.

## Alternatives considered

- **Warn and run the published version.** The run would silently ignore the edit the person
  just made, and they would judge their change from a run that did not contain it.
- **Publish automatically at run start.** This hides a versioning step. Versions would appear
  with no deliberate message, and the registry history would stop being a record of decisions.
- **Run the working copy unpinned.** The run would not trace back to any stored version, which
  removes the basis for change sets.
- **Pin each agent when its stage first runs.** A publish made while a run waits at a gate
  would give one run a mix of versions from before and after the change.
- **A flag to choose versions or skip the check.** Useful later, for example to re-run an old
  configuration. Nothing in M3 needs it, and leaving it out keeps one path to test.

## Consequences

- Every run can be traced to exact agent versions. Two runs with equal pins and an equal
  factory digest ran the same configuration.
- Editing an agent and running the factory takes two steps: publish, then run. The refusal
  message says so.
- A contract edited before the run starts changes the agent's working copy, so the run refuses
  to start. A contract edited while a run is in progress, for example while it waits at a gate,
  makes the next stage that uses it fail.
- Only changes to a contract's JSON Schema are detected, at start or at a stage. A change that
  touches only validator code, such as a `model_validator`, leaves the schema equal, so it is
  not detected and the run uses the changed behaviour.
- A run that waits at a human gate for days keeps its versions even if agents are published in
  the meantime.
- A later ADR can add an explicit way to choose versions without changing what a pin is.
