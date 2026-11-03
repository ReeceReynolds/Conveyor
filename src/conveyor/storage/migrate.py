"""Alembic migrations, configured in code and applied whenever a store is opened.

The migration scripts ship inside the package (`conveyor/storage/migrations/`), so an installed
Conveyor can upgrade any store it opens without an `alembic.ini` or a separate command.
"""

from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from alembic.script.revision import ResolutionError
from alembic.util import CommandError
from sqlalchemy import Connection

from conveyor.storage.errors import IncompatibleSchemaError, MigrationError

MIGRATIONS_DIR: Final = Path(__file__).with_name("migrations")
"""Where the Alembic environment and version scripts live."""


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

    Args:
        connection: A connection inside a transaction; the caller commits.

    Raises:
        IncompatibleSchemaError: If the database is at a revision this Conveyor does not know,
            which means a newer Conveyor migrated it.
        MigrationError: If a migration fails for any other reason.
    """
    try:
        command.upgrade(alembic_config(connection), "head")
    except CommandError as error:
        # Alembic reports a revision it has no script for as a ResolutionError: the database
        # was migrated by a newer Conveyor. Anything else is a failed migration.
        if isinstance(error.__cause__, ResolutionError):
            msg = f"the database schema is newer than this version of Conveyor supports: {error}"
            raise IncompatibleSchemaError(msg) from error
        msg = f"migrating the registry database failed: {error}"
        raise MigrationError(msg) from error
