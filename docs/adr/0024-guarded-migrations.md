# 0024. Guarded migrations: a Postgres advisory lock and a process lock around Alembic

- Status: Accepted
- Date: 2026-11-11

## Context

`Store.open` runs Alembic's `upgrade head` inside one transaction ([ADR 0012](0012-storage.md)).
On SQLite, `BEGIN IMMEDIATE` is taken before Alembic starts, so concurrent opens queue on the
write lock. On Postgres nothing serialises the upgrade. ADR 0012 records this in its
Consequences: "Running migrations concurrently on Postgres is not yet guarded by an advisory
lock".

The pre-M3 sweep reproduced it as finding F-05. Eight processes opening an empty Postgres
database at once: 8 of 48 opens failed with a duplicate key on `pg_type_typname_nsp_index`.
Eight threads in one process never finished: one session sat idle in transaction after creating
`alembic_version` while the others waited on it. Alembic's `context` is one object per process,
so one thread's `env.py` ran on another thread's connection.

Milestone 3 opens one store from more than one thread and process: DBOS, the CLI and later the
API server. The gap has to close first.

## Decision

**Take `pg_advisory_xact_lock` on the migrating connection before `command.upgrade`.** The lock
is held by the migration's transaction and released when it commits or rolls back, so a second
process waits, then finds the database current and does nothing.

**Hold a module-level lock around Alembic.** A `threading.Lock` in `conveyor.storage` serialises
every Alembic call in the process, because Alembic's `context` is process-wide.

No migration script changes, and SQLite behaves as before.

**This closes the gap recorded in ADR 0012's Consequences.** ADR 0012 is not edited.

**Tests.** `test_concurrent_first_open_from_threads` runs on SQLite and Postgres, and
`test_concurrent_first_open_from_processes` runs under the `postgres` marker.

## Alternatives considered

- **Open the store once per process and share it**, as the sweep's notes suggest as a stopgap.
  This avoids the thread case only, depends on every caller doing it, and leaves the process
  case open.
- **A session-level `pg_advisory_lock`.** It must be released explicitly, and an error between
  taking and releasing it could leave it held for the life of the connection. The transaction
  lock cannot outlive the migration.
- **Edit ADR 0012 to say the gap is closed.** Accepted ADRs are not rewritten; this ADR records
  the change instead.

## Consequences

- Any number of threads and processes can open a new or outdated store at the same time, on
  either backend.
- Opening a store in a process that is already migrating waits for it. After the first open the
  migration is a no-op check, so the wait is short.
- The module lock only covers one process. Processes are covered by the database's own locks:
  SQLite's write lock and the Postgres advisory lock.
