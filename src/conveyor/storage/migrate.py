"""Alembic migrations, configured in code and applied whenever a store is opened.

The migration scripts ship inside the package (`conveyor/storage/migrations/`), so an installed
Conveyor can upgrade any store it opens without an `alembic.ini` or a separate command.

Any number of threads and processes may open the same new or outdated store at once (ADR 0024).
Two locks make that safe:

- Within a process, a module-level lock serialises every Alembic command, because Alembic's
  `context` is one object per process: without it, one thread's `env.py` can run on another
  thread's connection. `check_current` runs no command and never touches that context (it
  reads the revision through its own `MigrationContext`), so it takes no lock.
- Between processes, the database serialises the upgrade. SQLite's `BEGIN IMMEDIATE` takes
  the write lock before Alembic starts. On Postgres, `upgrade` takes a transaction-level
  advisory lock (`MIGRATION_LOCK_KEY`) before Alembic runs, which the migration's commit or
  rollback releases; a process that waited on it then finds the database current and changes
  nothing. It sees the winner's migration because Postgres's default isolation level, READ
  COMMITTED, gives each statement a fresh snapshot, taken after the lock is granted.

SQLite's write lock is taken before the module lock, when the transaction begins; the Postgres
advisory lock is taken after it, while the module lock is held. A thread holding the module
lock therefore waits only on the advisory lock, and the advisory lock's holder (another
process, or a thread here that is committing) waits on nothing this thread holds, so the locks
cannot form a cycle.
"""

import threading
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from alembic.util import CommandError
from sqlalchemy import Connection, TextClause, bindparam, text

from conveyor.storage.errors import (
    IncompatibleSchemaError,
    MigrationError,
    MigrationRequiredError,
)

MIGRATIONS_DIR: Final = Path(__file__).with_name("migrations")
"""Where the Alembic environment and version scripts live."""

MIGRATION_LOCK_KEY: Final = 0x636F6E7665796F72
"""The Postgres advisory lock key that serialises migrations between processes.

A fixed signed 64-bit value (the ASCII bytes of "conveyor"), shared by every Conveyor process
that migrates the same database. It is taken with `pg_advisory_xact_lock`, so it is held only
by the migrating transaction and cannot outlive it.
"""

ALEMBIC_LOCK: Final = threading.Lock()
"""Held around every Alembic command, because Alembic's `context` is process-wide."""


def migration_lock_statement(dialect: str) -> TextClause | None:
    """Return the statement that serialises migrations between processes on a backend.

    Args:
        dialect: The SQLAlchemy dialect name, such as `"postgresql"` or `"sqlite"`.

    Returns:
        `pg_advisory_xact_lock(MIGRATION_LOCK_KEY)` on Postgres; `None` on SQLite, where the
        transaction's `BEGIN IMMEDIATE` already holds the write lock.
    """
    if dialect != "postgresql":
        return None
    return text("SELECT pg_advisory_xact_lock(:key)").bindparams(
        bindparam("key", MIGRATION_LOCK_KEY)
    )


def alembic_config(connection: Connection) -> Config:
    """Build the Alembic configuration for a connection, with no `alembic.ini`.

    `migrations/env.py` reads the connection from `config.attributes`, so Alembic runs inside
    the caller's transaction. Pass the result to `alembic.command` functions, for example to
    generate a new revision with `command.revision(config, message, autogenerate=True)`.

    Args:
        connection: A connection, usually inside a transaction.

    Returns:
        The configuration.
    """
    config = Config()
    # Config values are interpolated by configparser, so a literal `%` must be doubled.
    config.set_main_option("script_location", str(MIGRATIONS_DIR).replace("%", "%%"))
    config.attributes["connection"] = connection
    return config


def upgrade(connection: Connection) -> None:
    """Apply every migration the database has not yet had.

    Holds the module lock throughout and, on Postgres, takes the advisory lock in the
    connection's transaction before Alembic runs, so concurrent callers wait their turn. The
    advisory lock is released when the caller commits or rolls back.

    Args:
        connection: A connection inside a transaction; the caller commits.

    Raises:
        IncompatibleSchemaError: If the database is at a revision this Conveyor does not know,
            which means a newer Conveyor migrated it.
        MigrationError: If a migration fails for any other reason.
    """
    with ALEMBIC_LOCK:
        if (lock := migration_lock_statement(connection.dialect.name)) is not None:
            connection.execute(lock)
        try:
            command.upgrade(alembic_config(connection), "head")
        except CommandError as error:
            # Alembic reports a revision it has no script for as a ResolutionError: the
            # database was migrated by a newer Conveyor. Anything else is a failed migration.
            if isinstance(error.__cause__, ResolutionError):
                msg = (
                    f"the database schema is newer than this version of Conveyor supports: {error}"
                )
                raise IncompatibleSchemaError(msg) from error
            msg = f"migrating the registry database failed: {error}"
            raise MigrationError(msg) from error


def check_current(connection: Connection) -> None:
    """Check that the database has every migration, without applying any.

    Args:
        connection: A connection; nothing is written through it.

    Raises:
        IncompatibleSchemaError: If the database is at a revision this Conveyor does not know,
            which means a newer Conveyor migrated it.
        MigrationRequiredError: If the database lacks migrations this Conveyor has, because
            an older Conveyor wrote it.
    """
    current = MigrationContext.configure(connection).get_current_revision()
    scripts = ScriptDirectory.from_config(alembic_config(connection))
    if current == scripts.get_current_head():
        return
    if current is not None:
        try:
            scripts.get_revision(current)
        except CommandError as error:
            msg = (
                "the database schema is newer than this version of Conveyor supports: "
                f"unknown revision {current!r}"
            )
            raise IncompatibleSchemaError(msg) from error
    msg = (
        "the registry database was written by an older version of Conveyor and must be "
        "migrated; any command that writes to the registry, such as publishing, migrates it"
    )
    raise MigrationRequiredError(msg)
