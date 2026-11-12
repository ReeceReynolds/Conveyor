"""Guarded migrations: concurrent first opens from threads and processes (ADR 0024).

The thread and process tests release every opener together from a barrier onto an empty
database, so their migrations overlap. The process tests spawn fresh interpreters, so nothing
is shared but the database, as with several terminals or CI jobs.
"""

import multiprocessing
import threading
import time
from multiprocessing.context import SpawnProcess
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, TextClause, event, text
from sqlalchemy.engine.interfaces import DBAPICursor, ExecutionContext

from conveyor.storage import ObjectStore, Store, migrate
from conveyor.storage.database import connect
from conveyor.storage.migrate import (
    MIGRATION_LOCK_KEY,
    MIGRATIONS_DIR,
    migration_lock_statement,
)
from conveyor.storage.schema import Base

OPENERS = 8
ROUNDS = 3
# A deadlock must fail fast, well inside the suite's 60-second test timeout.
THREAD_TIMEOUT_SECONDS = 20
# Generous: every process must first start an interpreter and import Conveyor.
PROCESS_TIMEOUT_SECONDS = 60


def _head() -> str | None:
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()


def _revision(url: str) -> str | None:
    engine = connect(url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _empty(url: str) -> None:
    engine = connect(url)
    try:
        with engine.begin() as connection:
            Base.metadata.drop_all(connection)
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


@pytest.mark.timeout(THREAD_TIMEOUT_SECONDS * 2)
def test_concurrent_first_open_from_threads(database_url: str, tmp_path: Path) -> None:
    barrier = threading.Barrier(OPENERS)
    errors: list[str] = []

    def open_store() -> None:
        try:
            barrier.wait(THREAD_TIMEOUT_SECONDS)
            with Store.open_url(database_url, tmp_path / "objects"):
                pass
        # A thread's exception would otherwise only be printed; the test fails on any error.
        except Exception as error:  # noqa: BLE001 -- report every failure back to the test
            errors.append(f"{type(error).__name__}: {error}")

    # Daemon threads, so a deadlocked opener cannot keep the test process alive.
    threads = [threading.Thread(target=open_store, daemon=True) for _ in range(OPENERS)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + THREAD_TIMEOUT_SECONDS
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))

    assert [thread for thread in threads if thread.is_alive()] == []
    assert errors == []
    assert _revision(database_url) == _head()


def _open_together(url: str, objects: Path, barrier: Barrier, outcomes: Queue[str | None]) -> None:
    """Wait for every opener, then open the store; report `None`, or the error, on the queue."""
    try:
        barrier.wait(PROCESS_TIMEOUT_SECONDS)
        with Store.open_url(url, objects):
            pass
        outcomes.put(None)
    # A traceback in a child process would be lost; the parent fails on any error string.
    except Exception as error:  # noqa: BLE001 -- report every failure back to the parent
        outcomes.put(f"{type(error).__name__}: {error}")


@pytest.mark.postgres
@pytest.mark.enable_socket
@pytest.mark.timeout(PROCESS_TIMEOUT_SECONDS * ROUNDS)
def test_concurrent_first_open_from_processes(postgres_url: str, tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    started: list[SpawnProcess] = []
    try:
        for round_ in range(ROUNDS):
            _empty(postgres_url)
            barrier = context.Barrier(OPENERS)
            outcomes: Queue[str | None] = context.Queue()
            objects = tmp_path / f"objects-{round_}"
            # Daemon processes, so a hung opener cannot outlive the test process.
            processes = [
                context.Process(
                    target=_open_together,
                    args=(postgres_url, objects, barrier, outcomes),
                    daemon=True,
                )
                for _ in range(OPENERS)
            ]
            for process in processes:
                process.start()
                started.append(process)
            results = [outcomes.get(timeout=PROCESS_TIMEOUT_SECONDS) for _ in processes]
            for process in processes:
                process.join(PROCESS_TIMEOUT_SECONDS)

            assert [result for result in results if result is not None] == []
            assert [process.exitcode for process in processes] == [0] * OPENERS
            assert _revision(postgres_url) == _head()
    finally:
        # Stop any opener still running (after a failure or timeout) before emptying the
        # database, so none of them holds a lock or recreates a table behind the cleanup.
        for process in started:
            if process.is_alive():
                process.terminate()
            process.join()
        _empty(postgres_url)


def _record_statements(url: str, objects: Path) -> list[str]:
    """Open a store on `url` and return every SQL statement it executed, in order."""
    engine = connect(url)
    statements: list[str] = []

    def record(
        _connection: Connection,
        _cursor: DBAPICursor,
        statement: str,
        _parameters: object,
        _context: ExecutionContext | None,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    with Store(engine, ObjectStore(objects)):
        pass
    return statements


def _first(statements: list[str], fragment: str) -> int:
    return next(index for index, statement in enumerate(statements) if fragment in statement)


def test_the_advisory_lock_is_taken_only_on_postgres_before_alembic(
    database_url: str, tmp_path: Path
) -> None:
    statements = _record_statements(database_url, tmp_path / "objects")

    locks = [index for index, statement in enumerate(statements) if "pg_advisory" in statement]
    if database_url.startswith("postgresql"):
        assert len(locks) == 1
        assert locks[0] < _first(statements, "alembic_version")
    else:
        assert locks == []


def test_upgrade_issues_the_lock_statement_before_alembic_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # SQLite cannot run the Postgres statement, so stand in a marker SQLite can run.
    def marker(dialect: str) -> TextClause:
        return text(f"SELECT 'migration lock for {dialect}'")

    monkeypatch.setattr(migrate, "migration_lock_statement", marker)

    statements = _record_statements(f"sqlite:///{tmp_path / 'test.db'}", tmp_path / "objects")

    locks = [index for index, statement in enumerate(statements) if "migration lock" in statement]
    assert statements[locks[0]] == "SELECT 'migration lock for sqlite'"
    assert len(locks) == 1
    assert locks[0] < _first(statements, "alembic_version")


def test_alembic_runs_only_while_the_module_lock_is_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # SQLite threads pass with or without the module lock, so check it is held directly.
    upgrade = migrate.command.upgrade
    held: list[bool] = []

    def checked_upgrade(config: Config, revision: str) -> None:
        held.append(migrate.ALEMBIC_LOCK.locked())
        upgrade(config, revision)

    monkeypatch.setattr(migrate.command, "upgrade", checked_upgrade)

    with Store.open_url(f"sqlite:///{tmp_path / 'test.db'}", tmp_path / "objects"):
        pass

    assert held == [True]
    assert not migrate.ALEMBIC_LOCK.locked()


def test_the_lock_statement_is_an_advisory_transaction_lock_on_postgres_only() -> None:
    statement = migration_lock_statement("postgresql")

    assert statement is not None
    assert str(statement) == "SELECT pg_advisory_xact_lock(:key)"
    assert statement.compile().params == {"key": MIGRATION_LOCK_KEY}
    assert migration_lock_statement("sqlite") is None


def test_the_lock_key_fits_postgres_bigint() -> None:
    assert -(2**63) <= MIGRATION_LOCK_KEY < 2**63
