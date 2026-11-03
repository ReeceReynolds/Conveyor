"""Engine creation: supported backends, SQLite connection settings and write transactions.

Every SQLite connection gets write-ahead logging, enforced foreign keys and a busy timeout.
Read-only engines (`connect_read_only`) open an existing database file without write access
and leave its journal mode alone.
SQLAlchemy, not the `sqlite3` module, decides when transactions begin, so reads see a
consistent snapshot and writers can take the write lock up front with `BEGIN IMMEDIATE`.
"""

import os
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from sqlalchemy import URL, Connection, Engine, create_engine, event, make_url
from sqlalchemy.engine.interfaces import DBAPIConnection, DBAPICursor
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import ConnectionPoolEntry

from conveyor.storage.errors import DatabaseUnavailableError, UnsupportedDatabaseError

SUPPORTED_BACKENDS: Final = frozenset({"sqlite", "postgresql"})
"""Database backends Conveyor runs on: SQLite locally, Postgres tested in CI."""

BUSY_TIMEOUT_MS: Final = 15_000
"""How long a SQLite connection waits for another writer's lock before failing."""

_IMMEDIATE: Final = "conveyor_begin_immediate"

_WAL_RETRY_SECONDS: Final = 0.01
"""Pause between attempts to switch a new database to write-ahead logging."""

_PRAGMAS: Final = (
    f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
)


def connect(url: str) -> Engine:
    """Create an engine for a supported database URL.

    Args:
        url: A SQLAlchemy URL, such as `sqlite:///path/to/conveyor.db` or
            `postgresql+psycopg://user:password@host/db`.

    Returns:
        The engine. SQLite engines are configured as described in the module docstring.

    Raises:
        UnsupportedDatabaseError: If the URL names any other backend.
    """
    backend = make_url(url).get_backend_name()
    if backend not in SUPPORTED_BACKENDS:
        raise UnsupportedDatabaseError(backend)
    engine = create_engine(url)
    if backend == "sqlite":
        event.listen(engine, "connect", _configure_sqlite_connection)
        event.listen(engine, "begin", _begin_sqlite_transaction)
    return engine


def connect_read_only(database: Path) -> Engine:
    """Create an engine that reads an existing SQLite database and cannot write to it.

    Reading a database in write-ahead-log mode needs its `-wal` and `-shm` files, which SQLite
    creates beside it. Where that folder can be written, the database is opened as usual with
    `PRAGMA query_only`, which refuses every write; the last connection to close removes the
    two files again, as a connection opened read-only cannot. Where it cannot be written (a
    read-only checkout), the database is opened with SQLite's `mode=ro`, and as `immutable`
    if its `-shm` file is missing too, since nothing can be writing to it there.

    Args:
        database: The database file; it must exist.

    Returns:
        The engine, with the busy timeout and foreign keys of `connect` but no journal mode
        change.
    """
    if _writable(database.parent):
        url = URL.create("sqlite", database=str(database))
    else:
        query = {"mode": "ro", "uri": "true"}
        if not database.with_name(f"{database.name}-shm").exists():
            query["immutable"] = "1"
        url = URL.create("sqlite", database=database.resolve().as_uri(), query=query)
    engine = create_engine(url)
    event.listen(engine, "connect", _configure_read_only_sqlite_connection)
    event.listen(engine, "begin", _begin_sqlite_transaction)
    return engine


def _writable(folder: Path) -> bool:
    return os.access(folder, os.W_OK)


@contextmanager
def database_errors() -> Generator[None]:
    """Report errors from the database driver as `DatabaseUnavailableError`.

    A file that is not a database, a lock held past the busy timeout or an unreachable server
    otherwise surface as SQLAlchemy's own exceptions, with a multi-line message and a link.

    Yields:
        Nothing; wrap the database work in a `with` block.

    Raises:
        DatabaseUnavailableError: If the block raises a driver error.
    """
    try:
        yield
    except DBAPIError as error:
        detail = str(error.orig).strip().splitlines()
        raise DatabaseUnavailableError(
            detail[0] if detail else type(error.orig).__name__
        ) from error


def writer(engine: Engine) -> Engine:
    """Derive an engine whose transactions take the write lock as they begin.

    On SQLite this emits `BEGIN IMMEDIATE`, so concurrent writers queue on the busy timeout
    instead of failing when a read transaction tries to upgrade. Other backends ignore it and
    rely on row locks instead.

    Args:
        engine: An engine from `connect`.

    Returns:
        An engine sharing the same connection pool.
    """
    return engine.execution_options(**{_IMMEDIATE: True})


def _configure_sqlite_connection(
    dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry
) -> None:
    # Stop `sqlite3` from issuing its own BEGIN (it skips SELECTs and DDL); see
    # `_begin_sqlite_transaction`. PRAGMAs then run outside any transaction, as they must.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        for pragma in _PRAGMAS:
            cursor.execute(pragma)
        _enable_wal(cursor)
    finally:
        cursor.close()


def _configure_read_only_sqlite_connection(
    dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry
) -> None:
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        for pragma in (*_PRAGMAS, "PRAGMA query_only=ON"):
            cursor.execute(pragma)
    finally:
        cursor.close()


def _enable_wal(cursor: DBAPICursor) -> None:
    """Switch the database to write-ahead logging, waiting out other connections' locks.

    WAL mode is stored in the database file, so this only changes anything on a new database.
    There, SQLite fails the switch at once with "database is locked" whenever another
    connection holds a lock, without consulting the busy timeout. That happens whenever
    several stores open the same new project at once, so the switch is retried for as long as
    the busy timeout would have waited.
    """
    deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
    while True:
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as error:
            if "locked" not in str(error) or time.monotonic() >= deadline:
                raise
            time.sleep(_WAL_RETRY_SECONDS)
        else:
            return


def _begin_sqlite_transaction(connection: Connection) -> None:
    immediate = connection.get_execution_options().get(_IMMEDIATE, False)
    connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")
