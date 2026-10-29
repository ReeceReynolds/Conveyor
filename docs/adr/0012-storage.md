# 0012. Storage: SQLite via SQLAlchemy 2.0 and Alembic, plus a content-addressed object store

- Status: Accepted
- Date: 2026-10-28

## Context

The agent registry (Milestone 2) is the first feature that persists anything, and runs,
artifacts, eval results and traces will follow. Storage must be local-first (one machine, no
server to install), keep agent versions immutable, survive several Conveyor processes using the
same project at once, evolve its schema without losing data, and move to Postgres for shared
deployments later without a rewrite. Large immutable payloads (agent snapshots now, artifacts
later) should not bloat the database, and must be verifiable.

## Decision

**Where state lives.** Everything for a project is in `<project>/.conveyor/`:
`conveyor.db` and `objects/`. Opening a store writes a `.conveyor/.gitignore` containing `*`,
so state never reaches Git even in projects whose own `.gitignore` does not mention it.

**Relational data: SQLite (WAL) through SQLAlchemy 2.0's typed ORM.**
- Tables are declarative models with `Mapped[...]` annotations, which type-check under Pyright
  strict with no ignores. A metadata naming convention gives every constraint a deterministic
  name, so migrations can address it on any backend.
- Every SQLite connection sets `journal_mode=WAL` (readers never block the writer),
  `synchronous=NORMAL` (safe with WAL), `foreign_keys=ON` (SQLite's default is off) and a 15 s
  `busy_timeout`, from a `connect` event listener.
- SQLAlchemy, not the `sqlite3` module, emits `BEGIN`, so reads get a real snapshot and DDL is
  transactional. Write transactions use `BEGIN IMMEDIATE`, taking the write lock up front so
  concurrent publishers queue on the busy timeout instead of failing. On Postgres the same code
  path locks the agent's row with `SELECT ... FOR UPDATE`. A unique `(agent_id, sequence)`
  constraint, a self-referencing parent foreign key and check constraints back this up in the
  schema itself.
- Every decision a version depends on is made under that lock, never from an earlier read.
  The next sequence and the parent are computed in the recording transaction, and so is the
  no-op check for publishing unchanged content: `add_version_if_changed` compares the latest
  version's content ID inside the transaction and returns that version, with `created=False`,
  when it matches. Several processes publishing the same content therefore record it once, and
  the registry service builds each publish's diff from the recorded `parent_sequence`. A test
  runs six publishing processes against one project to hold this.
- Timestamps are stored as naive UTC (a portable `TypeDecorator`) and returned timezone-aware;
  naive input is rejected rather than guessed at.
- Callers never see ORM rows: repositories return frozen Pydantic records (ADR 0008).

**Migrations: Alembic, shipped in the package and applied on open.** The scripts live in
`conveyor/storage/migrations/` (included in the wheel) and are configured in code, with no
`alembic.ini`. `Store.open` runs `upgrade head` inside one transaction, so a store is always
current and a failed migration changes nothing. A database already at a revision this Conveyor
does not know (a newer Conveyor migrated it) is refused with `IncompatibleSchemaError`. A test
migrates a fresh database and asserts Alembic's `compare_metadata` finds no difference from the
models, so models and migrations cannot drift. New revisions are generated with
`alembic.command.revision(alembic_config(connection), message, autogenerate=True)` against a
migrated scratch database, then reviewed by hand.

**Objects: a content-addressed, write-once store on the filesystem.** Blobs are named by the
sha256 of their bytes, fanned out as `objects/ab/cdef...`. Writes go to a temporary file in the
target directory, are fsynced, and are moved into place with `os.replace`, so a reader sees a
whole object or none; writing existing content is a no-op. Every read re-hashes the bytes and
raises `CorruptObjectError` on mismatch. Digests are validated before they become paths. The
registry refuses to record a version whose snapshot is not already stored.

**Postgres** is supported through the same models and migrations. The repository, migration
and drift tests are parametrised over both backends; the Postgres cases are marked `postgres`
and use **testcontainers** (`postgres:17-alpine`) with **psycopg 3**. They are excluded from the
default run (`make test` stays Docker-free and the suite never starts a container twice in CI)
and run in a dedicated Linux job with `uv run pytest -m postgres`, which fails rather than skips
if Docker is missing. Run them locally the same way; without Docker they skip, or point
`CONVEYOR_TEST_POSTGRES_URL` at a disposable database. Coverage is measured on the default run,
so the few Postgres-only lines show as uncovered there.

## Alternatives considered

- **Raw `sqlite3`** — no dependency, but hand-written SQL per backend, no typed rows, no
  migration tooling and no path to Postgres.
- **SQLModel** — merges Pydantic and ORM models, but couples the public record types to the
  table layout, lags SQLAlchemy releases, and its typing is weaker under Pyright strict than
  SQLAlchemy 2.0's own `Mapped[...]`.
- **SQLAlchemy Core only (no ORM)** — viable, but the declarative models are what Alembic
  autogenerate and the drift test compare against, and they type-check row access.
- **Hand-rolled migrations (`PRAGMA user_version` plus SQL files)** — no autogenerate, no
  downgrade, no batch mode for SQLite's limited `ALTER TABLE`, and no shared tooling with
  Postgres.
- **Blobs in the database** — simpler backups, but bloats the WAL and every row read, and
  loses cheap deduplication and external verification.
- **psycopg2** — in maintenance mode; psycopg 3 is its successor and SQLAlchemy 2's
  recommended Postgres driver.

## Consequences

SQLAlchemy and Alembic (with Mako) become runtime dependencies; testcontainers and psycopg are
development-only. Every schema change needs a reviewed migration, enforced by the drift test.
Objects are never deleted, so a garbage collector for unreferenced blobs is future work. Running
migrations concurrently on Postgres is not yet guarded by an advisory lock, which matters only
once Postgres is used in production (out of scope for Milestone 2).
