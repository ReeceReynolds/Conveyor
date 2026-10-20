# 0001. Record architecture decisions

- Status: Accepted
- Date: 2026-10-20

## Context

Conveyor follows the principle "adopt before building": it uses established tools for
everything except its core purpose. Each adoption is a decision that contributors, human or
agent, need to understand before changing it. The project overview states that the rationale
for each stack choice lives in `docs/adr/`.

## Decision

Record every new dependency and every significant architectural decision as a numbered
Markdown ADR in `docs/adr/`, using [`0000-template.md`](0000-template.md) (a lightweight MADR
format). ADRs are immutable once accepted; a changed decision gets a new ADR that supersedes
the old one. Stack choices from the overview get their ADR when the code that adopts them
lands, not before.

## Alternatives considered

- **Decisions in the overview only** — loses the alternatives and trade-offs, and the overview
  has no history.
- **Wiki or external docs** — not versioned with the code and invisible to coding agents.

## Consequences

Reviewers can ask "where is the ADR?" for any new dependency. Agents have the reasoning
in-repo. Writing an ADR adds a small cost to each decision.
