import os
import shutil
import socket
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.docker_client import get_docker_host

from conveyor.storage import Store
from conveyor.storage.database import connect
from conveyor.storage.schema import Base

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parents[1] / "examples" / "prd-to-pr"

POSTGRES_IMAGE = "postgres:17-alpine"
# Point the Postgres tests at an existing, disposable database instead of a container.
POSTGRES_URL_ENV = "CONVEYOR_TEST_POSTGRES_URL"
# Set in CI's Postgres job, so a missing Docker fails the job instead of skipping its tests.
REQUIRE_POSTGRES_ENV = "CONVEYOR_REQUIRE_POSTGRES"
DEFAULT_DOCKER_HOST = "unix:///var/run/docker.sock"


@pytest.fixture
def in_fixtures(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the test from the fixtures folder, so reported paths are short and stable."""
    monkeypatch.chdir(FIXTURES)
    return Path()


@pytest.fixture
def example() -> Path:
    """The prd-to-pr reference factory, which doubles as a valid fixture."""
    return EXAMPLE


@pytest.fixture
def example_project(tmp_path: Path) -> Path:
    """A private copy of the reference factory, without any local registry state."""
    project = tmp_path / "prd-to-pr"
    ignore = shutil.ignore_patterns(".conveyor", "__pycache__")
    shutil.copytree(EXAMPLE, project, ignore=ignore)
    return project


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A Postgres database for the session: a testcontainer, or skipped without Docker."""
    if url := os.environ.get(POSTGRES_URL_ENV):
        yield url
        return
    if (unavailable := _docker_unavailable()) is not None:
        if os.environ.get(REQUIRE_POSTGRES_ENV):
            pytest.fail(f"Postgres tests are required but {unavailable}")
        pytest.skip(unavailable)
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as postgres:
        yield postgres.get_connection_url()


def _docker_unavailable() -> str | None:
    """Why the Docker daemon cannot be reached, or `None` if it (probably) can.

    Probes the socket directly: docker-py leaks its socket when the daemon is missing, which
    the warnings-as-errors test configuration would report as a failure.
    """
    host = get_docker_host() or DEFAULT_DOCKER_HOST
    url = urlsplit(host)
    try:
        if url.scheme == "unix":
            with socket.socket(socket.AF_UNIX) as probe:
                probe.connect(url.path)
        elif url.scheme == "tcp" and url.hostname is not None:
            with socket.create_connection((url.hostname, url.port or 2375), timeout=5):
                pass
    except OSError as error:
        return f"Docker is unavailable at {host}: {error}"
    return None


def _empty_postgres(url: str) -> None:
    engine = connect(url)
    try:
        with engine.begin() as connection:
            Base.metadata.drop_all(connection)
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


# Postgres runs in a container reached over TCP, so its tests opt back in to sockets.
_POSTGRES = pytest.param("postgresql", marks=[pytest.mark.postgres, pytest.mark.enable_socket])


@pytest.fixture(params=["sqlite", _POSTGRES])
def database_url(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[str]:
    """The URL of an empty database, on SQLite and (when available) on Postgres."""
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'test.db'}"
        return
    url: str = request.getfixturevalue("postgres_url")
    _empty_postgres(url)
    yield url
    _empty_postgres(url)


@pytest.fixture
def store(database_url: str, tmp_path: Path) -> Iterator[Store]:
    """A freshly migrated store on each supported database."""
    with Store.open_url(database_url, tmp_path / "objects") as opened:
        yield opened
