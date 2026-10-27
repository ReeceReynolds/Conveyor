# Milestone 2 — Agent registry and versioning

**Goal:** `conveyor agent publish <name> -m "message"` turns an agent folder into an immutable,
content-addressed version, and `conveyor agent diff` explains any change in factory-model
terms, e.g. *"implementer v4 → v5: Capabilities changed; model profile changed; model switched"*.

## Where things stand

| Milestone | What landed | PRs |
|---|---|---|
| M0 — Bootstrap | uv workspace, Ruff, Pyright strict, pytest + Hypothesis + inline-snapshot, CI, release-please, UI scaffold, ADRs 0001–0007 | #1, #2 |
| M1 — Factory model | Strict Pydantic models for agents and factories, YAML loading with file:line:column errors, JSON Schemas, `conveyor validate`, PRD → PR example (placeholder prompts, no contracts), ADRs 0008–0010 | #3, #4 |

Nothing executes yet, and nothing is versioned. Contract references (`contracts.TaskList`) are
validated as dotted names only; no `contracts.py` exists in the example.

## Why the registry comes next

Every later capability keys off agent version IDs: runs pin them, change sets are diffs between
them, eval baselines compare them, and the UI navigates by them. The registry has no model-call
or network dependency, so it can be built and tested deterministically now, and its storage
layer and contract resolution are prerequisites for execution (M3) anyway.

## Scope

**In:** contract resolution and example contracts; local storage (SQLite WAL, SQLAlchemy 2.0,
Alembic, content-addressed object store); canonical agent snapshots with content-hash version
IDs; structured diffs by block, component and primitive; `conveyor agent publish | history |
show | diff`; ADRs for each adopted tool or decision.

**Out (later milestones):** running agents (M3), eval baselines on publish (M4), runs and change
sets (M3/M5), the web UI (M6), Postgres in production deployments.

## Work packages

Wave 1 runs in parallel; wave 2 builds on all three.

### WP-A — Contract resolution (wave 1)
- New package `conveyor.contracts`: `resolve_contract(project_root, ref) -> type[BaseModel]` and
  `contract_schema(model) -> JsonSchema` (JSON Schema 2020-12, deterministic output).
- `ContractResolutionError` carries a message suitable for an `Issue`.
- Refs resolve against the project root (the folder holding `agents/` and `factories/`):
  `contracts.TaskList` → `<root>/contracts.py` or `<root>/contracts/__init__.py`, attribute
  `TaskList`, which must be a Pydantic `BaseModel` subclass. Importing must not leak project
  modules into `sys.modules` between projects.
- `conveyor validate` reports unresolvable `brief.input` / `brief.output` as normal issues on
  the right line, when the agent is validated within a project.
- `examples/prd-to-pr/contracts.py`: `PRD`, `TechnicalRequirements`, `TaskList` / `Task`,
  `CodeChanges`, `ReviewVerdict`; agent YAMLs point at them.
- ADR 0011 (amends ADR 0008's "resolving belongs to execution").

### WP-B — Storage foundation (wave 1)
- New package `conveyor.storage`: state lives in `<project>/.conveyor/` (gitignored):
  `conveyor.db` (SQLite, WAL, foreign keys on) and `objects/` (content-addressed, sha256,
  write-once, atomic writes, fan-out directories).
- SQLAlchemy 2.0 typed ORM, Alembic migrations shipped in the package and applied
  programmatically on open; a test fails if models and migrations drift.
- Registry tables: `agents` and `agent_versions` (version id = content hash, agent name,
  sequence number, parent version, author, message, created_at, snapshot object digest), plus a
  typed repository: add version, latest, by sequence, by id or unique id prefix, history.
- Postgres compatibility tested with testcontainers in a Linux-only CI job; skipped locally
  without Docker.
- ADR 0012 (storage).

### WP-C — Agent snapshots and structured diffs (wave 1)
- New package `conveyor.registry` (snapshot and diff modules only): `AgentSnapshot`, a frozen
  model holding everything that defines an agent version: the `Agent` config, instructions
  text, resolved input/output contract JSON Schemas, and the eval suite's files (path → digest
  and content).
- Canonical serialisation and `version_id(snapshot)` (sha256). Same content → same id,
  regardless of key order or file-system order.
- `diff_snapshots(old, new) -> AgentDiff`: a tree of Block → Component → Primitive changes
  (Brief: instructions, contract pair; Capabilities: model profile, toolkit, permissions;
  Quality Gate: eval suite files, thresholds), with old/new values and a unified text diff for
  instructions.
- `summarise(diff)` gives the one-line form; `render(diff)` the full human-readable form.
- Hypothesis properties: id stability, diff of identical snapshots is empty, diff detects every
  single-field change, rendering never crashes.
- ADR 0013 (version identity and canonical form).

### WP-D — Registry service and CLI (wave 2)
- `conveyor.registry.service`: `publish`, `history`, `show`, `diff`, joining A (schemas), B
  (storage) and C (snapshots). Publishing validates the agent first, refuses invalid agents,
  and is a no-op when content is unchanged.
- CLI group `conveyor agent`: `publish <name> -m MSG [--project PATH] [--author TEXT]`,
  `history <name>`, `show <name>[@vN|@<id-prefix>]`, `diff <name> [FROM] [TO]` (defaults to
  the last two versions).
- README, AGENTS.md and the example README updated; an end-to-end test publishes the example,
  edits a model setting and checks the diff summary.

## Definition of done

`make check` passes; 90%+ branch coverage holds; every new dependency has an ADR; publishing
`examples/prd-to-pr`'s `implementer`, switching its model and publishing again prints a diff
whose summary reads *"implementer v1 → v2: Capabilities changed; model profile changed; model
switched (… → …)"*.

## Delivery

Work packages land as PRs into `milestone/agent-registry`; the milestone then lands on `main` as
one reviewed PR so release-please records a single `feat` entry.
