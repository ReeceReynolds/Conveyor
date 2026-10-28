"""Opening a project's store: the database, the object store and the repositories over them."""

from pathlib import Path
from types import TracebackType
from typing import Final, Self

from sqlalchemy import URL, Engine

from conveyor.storage.database import connect, writer
from conveyor.storage.migrate import upgrade
from conveyor.storage.objects import ObjectStore
from conveyor.storage.registry import RegistryRepository

STATE_DIR: Final = ".conveyor"
"""The folder, inside a project root, that holds all of Conveyor's local state."""

DATABASE_FILE: Final = "conveyor.db"
OBJECTS_DIR: Final = "objects"

# Written into the state folder so it stays out of Git in any project, without asking users
# to edit their own .gitignore.
_SELF_IGNORE = "# Created by Conveyor: local state, never committed.\n*\n"


class Store:
    """A project's persistent state: a migrated database plus a content-addressed object store.

    Open one with `Store.open` (or `Store.open_url`) and close it when done, preferably with
    `with`. Opening creates whatever is missing and applies any pending migrations.

    Attributes:
        objects: The content-addressed object store.
        registry: Agents and their versions.
    """

    def __init__(self, engine: Engine, objects: ObjectStore) -> None:
        """Wrap an engine and an object store, migrating the database first.

        Prefer `Store.open` or `Store.open_url`, which also create the engine.

        Args:
            engine: An engine from `conveyor.storage.database.connect`.
            objects: The object store to pair with the database.

        Raises:
            IncompatibleSchemaError: If a newer Conveyor migrated the database.
        """
        self._engine = engine
        try:
            with writer(engine).begin() as connection:
                upgrade(connection)
        except BaseException:
            engine.dispose()
            raise
        self.objects: ObjectStore = objects
        self.registry: RegistryRepository = RegistryRepository(engine, objects)

    @classmethod
    def open(cls, project_root: Path) -> Self:
        """Open the store in `<project_root>/.conveyor/`, creating it if needed.

        Args:
            project_root: The project folder (the one holding `agents/`).

        Returns:
            The open store, on SQLite in write-ahead-log mode.

        Raises:
            IncompatibleSchemaError: If a newer Conveyor migrated the database.
        """
        state = project_root / STATE_DIR
        state.mkdir(parents=True, exist_ok=True)
        ignore = state / ".gitignore"
        if not ignore.exists():
            ignore.write_text(_SELF_IGNORE, encoding="utf-8")
        url = URL.create("sqlite", database=str(state / DATABASE_FILE))
        return cls.open_url(url.render_as_string(hide_password=False), state / OBJECTS_DIR)

    @classmethod
    def open_url(cls, url: str, objects_dir: Path) -> Self:
        """Open a store on any supported database, such as Postgres in tests.

        Args:
            url: A SQLAlchemy database URL (`sqlite:///...` or `postgresql+psycopg://...`).
            objects_dir: Where to keep the object store; created if needed.

        Returns:
            The open store.

        Raises:
            UnsupportedDatabaseError: If the URL names another backend.
            IncompatibleSchemaError: If a newer Conveyor migrated the database.
        """
        return cls(connect(url), ObjectStore(objects_dir))

    def close(self) -> None:
        """Release every database connection. The store must not be used afterwards."""
        self._engine.dispose()

    def __enter__(self) -> Self:
        """Use the store as a context manager that closes it on exit.

        Returns:
            The store itself.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the store.

        Args:
            exc_type: The exception type, if the block raised.
            exc_value: The exception, if the block raised.
            traceback: The traceback, if the block raised.
        """
        self.close()
