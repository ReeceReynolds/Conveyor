"""Engine creation: supported backends, SQLite connection settings and write transactions.

Every SQLite connection gets write-ahead logging, enforced foreign keys and a busy timeout.
SQLAlchemy, not the `sqlite3` module, decides when transactions begin, so reads see a
consistent snapshot and writers can take the write lock up front with `BEGIN IMMEDIATE`.
"""

from typing import Final

from sqlalchemy import Connection, Engine, create_engine, event, make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry

from conveyor.storage.errors import UnsupportedDatabaseError

SUPPORTED_BACKENDS: Final = frozenset({"sqlite", "postgresql"})
"""Database backends Conveyor runs on: SQLite locally, Postgres tested in CI."""

BUSY_TIMEOUT_MS: Final = 15_000
"""How long a SQLite connection waits for another writer's lock before failing."""

_IMMEDIATE: Final = "conveyor_begin_immediate"

_PRAGMAS: Final = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
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
    finally:
        cursor.close()


def _begin_sqlite_transaction(connection: Connection) -> None:
    immediate = connection.get_execution_options().get(_IMMEDIATE, False)
    connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")
