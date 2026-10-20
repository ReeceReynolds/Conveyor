# 0007. Apache-2.0 licence and the `conveyor-harness` distribution name

- Status: Accepted
- Date: 2026-10-20

## Context

Conveyor is open-source infrastructure that others may build on commercially. The name
`conveyor` is already registered on PyPI.

## Decision

- License under **Apache-2.0**, which is permissive and includes an explicit patent grant.
- Publish to PyPI as **`conveyor-harness`**. The import package and the CLI stay `conveyor`.

## Alternatives considered

- **MIT** — equally permissive but has no patent grant.
- **`conveyor-ai`** — more generic; "harness" ties the name to harness engineering.

## Consequences

Users run `pip install conveyor-harness` and `import conveyor`. Docs must use the distribution
name when talking about installation.
