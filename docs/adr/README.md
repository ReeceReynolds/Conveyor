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

Still to be recorded as each is adopted: agent execution (Pydantic AI and Harness), durable
execution (DBOS), tools (MCP), evals (Pydantic Evals), observability (OpenTelemetry GenAI
conventions), cost tracking, API (FastAPI), workspace isolation and security.
