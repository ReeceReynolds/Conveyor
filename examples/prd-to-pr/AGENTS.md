# examples/prd-to-pr

The reference PRD → PR factory. It exists to prove Conveyor works end to end and doubles as a
test fixture (`tests/conftest.py` exposes it as `example`). It is not product code: it is a
uv workspace member that is never published.

## Layout

```
factories/prd-to-pr.yaml      the factory: stages, trigger, rework loop, outcome scorers
agents/<name>/agent.yaml      Brief, Capabilities and Quality Gate; `name` matches the folder
agents/<name>/prompt.md       the instructions file named by `brief.instructions`
agents/<name>/evals/          the eval suite named by `quality_gate.suite`
```

Each YAML file starts with a `yaml-language-server: $schema=` comment pointing at `schemas/`,
so editors validate it.

## Rules

- It must always validate: `uv run conveyor validate examples/prd-to-pr`. Tests fail if it
  does not.
- Keep placeholder prompts honest: a prompt that is not written yet says so ("Placeholder
  instructions...") rather than pretending to be a real prompt. Replace placeholders only with
  prompts that are actually used and evaluated.
- Contracts, scorers and evals referenced here are filled in as the capabilities they need
  land; do not add stand-ins that suggest a capability exists before it does.
- Update [`README.md`](README.md) when the stages or agents change.
