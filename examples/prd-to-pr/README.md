# PRD → PR reference factory

The reference factory that proves Conveyor works end to end: it takes a PRD through
requirements, task breakdown, implementation, validation, code review and human approval.
See [`docs/project-overview.md`](../../docs/project-overview.md#reference-factory-prd--pr).

```
factories/prd-to-pr.yaml        the factory: seven stages, a bounded review loop, outcome scorers
contracts.py                    the typed handoffs between stages (Pydantic models)
agents/requirements-analyst/    PRD → TechnicalRequirements
agents/task-planner/            TechnicalRequirements → TaskList
agents/implementer/             TaskList → CodeChanges
agents/code-reviewer/           CodeChanges → ReviewVerdict (can return work to implement)
```

Each agent's `brief.input` and `brief.output` name a model in [`contracts.py`](contracts.py), so
one agent's output is exactly the next one's input. The contracts are frozen and reject unknown
fields, and they check the rules a downstream stage relies on: ids are unique, tasks are listed
after the tasks they depend on, and a review that rejects the work carries at least one blocker
or major finding while an approval carries none. Their field descriptions end up in each agent
version's JSON Schema.

Each agent folder also holds a placeholder `prompt.md` and an empty `evals/` suite; scorers,
prompts and evals are filled in as Conveyor's execution and eval capabilities land. The factory
already passes validation, contracts included, and doubles as a test fixture:

```bash
uv run conveyor validate examples/prd-to-pr
```

It is a uv workspace member that is not published.
