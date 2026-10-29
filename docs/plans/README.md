# Execution plans

A plan is an agent-sized breakdown of one milestone: the goal, what is in and out of scope, the
work packages (each small enough for one agent or one PR, with the branch it lands on) and a
definition of done that can be checked. Plans live in the repository so agents and humans read
the same, current version, and so changes to the plan are reviewed like code.

## Conventions

- One file per milestone, named `milestone-N-<slug>.md`, e.g.
  [`milestone-2-agent-registry.md`](milestone-2-agent-registry.md).
- The first lines give a status, `Planned | In progress | Done`, and the integration branch.
- Update the plan in the same PR as the work: when a work package lands, record its state and
  PR; when scope changes, change the plan first.
- Completed plans stay as history; mark them `Done` rather than deleting them.
- Decisions with lasting consequences go in an ADR ([`docs/adr/`](../adr/README.md)); the plan
  links to it.

## Plans

| Milestone | Status |
|---|---|
| [2 — Agent registry and versioning](milestone-2-agent-registry.md) | In progress |
