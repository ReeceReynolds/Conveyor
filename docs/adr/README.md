# Architecture Decision Records

Each significant decision is recorded as an ADR (see [0001](0001-record-architecture-decisions.md)).
To add one, copy [`0000-template.md`](0000-template.md) to the next number and add it below.

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-python-and-uv-workspace.md) | Python 3.14 with a uv workspace and committed lockfile | Accepted |
| [0003](0003-quality-tooling.md) | Quality tooling: Ruff, Pyright strict, pre-commit and GitHub Actions | Accepted |
| [0004](0004-testing-strategy.md) | Testing strategy | Accepted |
| [0005](0005-release-process.md) | Releases: SemVer, Conventional Commits, release-please and Trusted Publishing | Accepted |
| [0006](0006-ui-toolchain.md) | UI toolchain: pnpm, Vite, React, TypeScript, Biome and Vitest | Accepted |
| [0007](0007-license-and-distribution-name.md) | Apache-2.0 licence and the `conveyor-harness` distribution name | Accepted |
| [0008](0008-contracts-and-configuration.md) | Contracts and configuration: Pydantic v2 models and JSON Schema 2020-12 | Accepted |
| [0009](0009-yaml-library.md) | YAML parsing with ruamel.yaml | Accepted |
| [0010](0010-cli.md) | CLI: Typer | Accepted |
| [0011](0011-contract-resolution.md) | Contract resolution: dotted references, resolved in isolation at validate and publish time | Accepted |
| [0012](0012-storage.md) | Storage: SQLite via SQLAlchemy 2.0 and Alembic, plus a content-addressed object store | Accepted |
| [0013](0013-agent-version-identity.md) | Agent version identity: canonical snapshots hashed with RFC 8785 | Accepted |
| [0014](0014-agent-ready-repository.md) | Agent-ready repository: enforce, don't instruct | Accepted |
| [0015](0015-read-only-store.md) | Read-only store access for commands that only read | Accepted |
| [0016](0016-run-model-and-handoff-routing.md) | Run model and handoff routing: inputs selected by contract, one envelope for rework | Accepted |
| [0017](0017-run-version-pinning.md) | A run pins the latest published version of every agent, and refuses unpublished edits | Accepted |
| [0018](0018-durable-execution-dbos.md) | Durable execution: DBOS Transact, one step per stage attempt, waits by process exit | Accepted |
| [0019](0019-operations.md) | Operations: built-in, typed and configured with `with:` on the stage | Accepted |
| [0020](0020-agent-runtime-pydantic-ai.md) | Agent runtime: Pydantic AI v2 and parts of Pydantic AI Harness, behind `AgentRuntime` | Accepted |
| [0021](0021-workspace-sandbox-and-tools.md) | Workspace sandbox and tools: hardened Docker through the Harness, declared tools only | Accepted |
| [0022](0022-observability-and-cost.md) | Observability and cost: Pydantic AI instrumentation, a local span store, optional OTLP | Accepted |
| [0023](0023-execution-package-layering.md) | Execution package layering: six new packages, each heavy dependency in one place | Accepted |
| [0024](0024-guarded-migrations.md) | Guarded migrations: a Postgres advisory lock and a process lock around Alembic | Accepted |

Still to be recorded as each is adopted: tools (MCP), evals (Pydantic Evals), API (FastAPI) and
security.
