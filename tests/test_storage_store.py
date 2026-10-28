"""Opening stores, migrations (including drift from the ORM models) and database settings."""

import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import DateTime, Engine, bindparam, inspect, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import IntegrityError, OperationalError

from conveyor.storage import (
    STATE_DIR,
    IncompatibleSchemaError,
    Store,
    UnsupportedDatabaseError,
    database,
)
from conveyor.storage.database import BUSY_TIMEOUT_MS, connect
from conveyor.storage.migrate import MIGRATIONS_DIR, alembic_config
from conveyor.storage.schema import Base, UTCDateTime

DIGEST = "0" * 64


@pytest.fixture
def engine(store: Store, database_url: str) -> Iterator[Engine]:
    """A separate engine on the store's (already migrated) database."""
    del store
    created = connect(database_url)
    yield created
    created.dispose()


def _head() -> str | None:
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()


def _tables(engine: Engine) -> list[str]:
    return sorted(inspect(engine).get_table_names())


def test_open_creates_the_state_folder(tmp_path: Path) -> None:
    with Store.open(tmp_path):
        pass

    state = tmp_path / STATE_DIR
    assert sorted(path.name for path in state.iterdir()) == [".gitignore", "conveyor.db", "objects"]
    assert (
        state / ".gitignore"
    ).read_text() == "# Created by Conveyor: local state, never committed.\n*\n"


def test_reopening_keeps_data_and_the_users_ignore_file(tmp_path: Path) -> None:
    with Store.open(tmp_path) as first:
        digest = first.objects.put(b"snapshot")
        first.registry.add_version(
            agent="implementer",
            content_id=DIGEST,
            author="ada",
            message="m",
            snapshot_digest=digest,
            created_at=datetime(2026, 10, 28, tzinfo=UTC),
        )
    ignore = tmp_path / STATE_DIR / ".gitignore"
    ignore.write_text("edited\n")

    with Store.open(tmp_path) as second:
        latest = second.registry.latest("implementer")
        assert latest is not None
        assert second.objects.get(latest.snapshot_digest) == b"snapshot"
    assert ignore.read_text() == "edited\n"


def test_migrations_create_the_registry_tables(engine: Engine) -> None:
    assert _tables(engine) == ["agent_versions", "agents", "alembic_version"]
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == _head() == "0001"


def test_models_and_migrations_do_not_drift(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_migrations_downgrade_and_upgrade_again(
    engine: Engine, database_url: str, tmp_path: Path
) -> None:
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
    assert _tables(engine) == ["alembic_version"]

    with Store.open_url(database_url, tmp_path / "objects"):
        pass
    assert _tables(engine) == ["agent_versions", "agents", "alembic_version"]


def test_a_newer_schema_is_refused(tmp_path: Path) -> None:
    with Store.open(tmp_path):
        pass
    database = connect(f"sqlite:///{tmp_path / STATE_DIR / 'conveyor.db'}")
    with database.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    database.dispose()

    with pytest.raises(IncompatibleSchemaError, match="newer than this version of Conveyor"):
        Store.open(tmp_path)


def test_unsupported_databases_are_refused(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedDatabaseError) as caught:
        Store.open_url("mysql://user@localhost/conveyor", tmp_path)

    assert caught.value.backend == "mysql"
    assert str(caught.value) == "unsupported database 'mysql'; use sqlite or postgresql"


def test_sqlite_connections_are_configured(tmp_path: Path) -> None:
    engine = connect(f"sqlite:///{tmp_path / 'settings.db'}")
    with engine.connect() as connection:
        settings = {
            pragma: connection.exec_driver_sql(f"PRAGMA {pragma}").scalar()
            for pragma in ("journal_mode", "foreign_keys", "busy_timeout", "synchronous")
        }
    engine.dispose()

    assert settings == {
        "journal_mode": "wal",
        "foreign_keys": 1,
        "busy_timeout": BUSY_TIMEOUT_MS,
        "synchronous": 1,
    }


def _lock_new_database(path: Path) -> sqlite3.Connection:
    """Open a new database the way a concurrent store does: holding the write lock."""
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("CREATE TABLE placeholder (x)")
    return holder


def test_switching_a_new_database_to_wal_waits_for_other_connections(tmp_path: Path) -> None:
    # SQLite fails this switch at once while another connection holds a lock, ignoring the
    # busy timeout; stores opening one new project together hit exactly that.
    path = tmp_path / "new.db"
    holder = _lock_new_database(path)
    release = threading.Timer(0.1, holder.execute, ("COMMIT",))
    release.start()
    engine = connect(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
    finally:
        engine.dispose()
        release.join()
        holder.close()

    assert mode == "wal"


def test_switching_to_wal_gives_up_after_the_busy_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "BUSY_TIMEOUT_MS", 50)
    path = tmp_path / "held.db"
    holder = _lock_new_database(path)
    engine = connect(f"sqlite:///{path}")
    try:
        with pytest.raises(OperationalError, match="database is locked"), engine.connect():
            pass
    finally:
        engine.dispose()
        holder.close()


def _insert_version(engine: Engine, *, agent_id: int, sequence: int, parent: int | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agent_versions (agent_id, sequence, content_id, parent_sequence,"
                " author, message, created_at, snapshot_digest)"
                " VALUES (:agent_id, :sequence, :digest, :parent, 'a', 'm', :when, :digest)"
            ).bindparams(bindparam("when", type_=DateTime())),
            {
                "agent_id": agent_id,
                "sequence": sequence,
                "parent": parent,
                "digest": DIGEST,
                # The column stores naive UTC; raw SQL bypasses the UTCDateTime type.
                "when": datetime(2026, 10, 28),
            },
        )


def test_the_database_enforces_version_integrity(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO agents (id, name) VALUES (1, 'implementer')"))
    _insert_version(engine, agent_id=1, sequence=1, parent=None)

    with pytest.raises(IntegrityError, match=r"(?i)foreign key"):
        _insert_version(engine, agent_id=2, sequence=1, parent=None)
    with pytest.raises(IntegrityError, match=r"(?i)unique"):
        _insert_version(engine, agent_id=1, sequence=1, parent=None)
    with pytest.raises(IntegrityError, match=r"(?i)check"):
        _insert_version(engine, agent_id=1, sequence=2, parent=None)
    with pytest.raises(IntegrityError, match=r"(?i)check"):
        _insert_version(engine, agent_id=1, sequence=0, parent=None)
    _insert_version(engine, agent_id=1, sequence=2, parent=1)


def test_migrations_ship_inside_the_package() -> None:
    assert sorted(path.name for path in (MIGRATIONS_DIR / "versions").glob("*.py")) == [
        "0001_registry_tables.py"
    ]
    assert (MIGRATIONS_DIR / "env.py").is_file()
    assert (MIGRATIONS_DIR / "script.py.mako").is_file()


def test_utc_datetime_round_trips_and_refuses_naive_values() -> None:
    column = UTCDateTime()
    dialect = sqlite.dialect()
    local = datetime(2026, 10, 28, 14, 30, tzinfo=timezone(timedelta(hours=2)))

    stored = column.process_bind_param(local, dialect)
    assert stored == datetime(2026, 10, 28, 12, 30)
    assert column.process_result_value(stored, dialect) == local
    assert column.process_bind_param(None, dialect) is None
    assert column.process_result_value(None, dialect) is None
    with pytest.raises(ValueError, match="naive"):
        column.process_bind_param(datetime(2026, 10, 28), dialect)
