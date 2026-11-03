# 0015. Read-only store access for commands that only read

- Status: Accepted
- Date: 2026-11-03

## Context

ADR [0012](0012-storage.md) has `Store.open` create `.conveyor/` and run `upgrade head` under
`BEGIN IMMEDIATE`, so a store is always current. That made every command a writer. Commands
that only read (`conveyor agent history`, `show`, `diff`) created a `.conveyor/` folder in
projects that had never published anything, took the write lock and failed in read-only
checkouts, such as a CI cache or a mounted volume (issue #19).

A SQLite database in write-ahead-log mode needs its `-wal` and `-shm` files beside it even to
be read. A connection opened with SQLite's `mode=ro` creates them but cannot remove them when it
closes. In a folder that cannot be written, it cannot create them at all, so the open fails
unless the database is opened as `immutable`.

## Decision

`Store.open(project_root, read_only=True)` opens an existing store without writing anything.
Commands that only read use it, and only `publish` opens the store for writing.

- Nothing is created. A missing `.conveyor/conveyor.db` raises `RegistryNotFoundError`, which
  the CLI reports as "nothing has been published yet". `ObjectStore(..., create=False)` does
  not create its folder.
- Nothing is migrated. `check_current` compares the database's revision with the package's
  head. An unknown (newer) revision raises `IncompatibleSchemaError`, as before, and an older
  one raises `MigrationRequiredError`. The next write migrates it.
- Writes are refused by SQLite, not by convention:
  - When the state folder can be written, the database opens normally with
    `PRAGMA query_only=ON`, and the last connection to close removes the `-wal` and `-shm`
    files.
  - When the folder cannot be written, the database opens with `mode=ro`, and also as
    `immutable` if no `-shm` file exists. With no `-shm` file, no process is writing, and none
    can create one in that folder.

## Alternatives considered

- **Always `mode=ro`.** This leaves `-wal` and `-shm` files behind after every read.
- **Always `immutable=1`.** This is unsafe beside a running publish: SQLite would skip locking
  and could read a half-written transaction.
- **Migrate on read when the folder is writable.** A read command would still take the write
  lock and change the database, which is what the issue reports.

## Consequences

Read commands work on read-only checkouts and leave a project exactly as they found it. After
a Conveyor upgrade that adds a migration, read commands fail with `MigrationRequiredError`
until something writes. Today, that something is `conveyor agent publish`. A future
`conveyor migrate` command could do it explicitly. Postgres stores (`Store.open_url`) are
unaffected: they are always opened for writing.
