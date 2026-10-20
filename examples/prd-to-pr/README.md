# PRD → PR reference factory

The reference factory that proves Conveyor works end to end: it takes a PRD through
requirements, task breakdown, implementation, validation, code review and human approval.
See [`docs/project-overview.md`](../../docs/project-overview.md#reference-factory-prd--pr).

```
factories/prd-to-pr.yaml        the factory: seven stages, a bounded review loop, outcome scorers
agents/requirements-analyst/    PRD → technical requirements
agents/task-planner/            requirements → ordered tasks
agents/implementer/             tasks → code changes
agents/code-reviewer/           code changes → review verdict (can return work to implement)
```

Each agent folder holds `agent.yaml`, a placeholder `prompt.md` and an empty `evals/` suite.
Contracts, scorers, prompts and evals are filled in as Conveyor's execution and eval
capabilities land. The factory already passes validation and doubles as a test fixture:

```bash
uv run conveyor validate examples/prd-to-pr
```

It is a uv workspace member that is not published.
