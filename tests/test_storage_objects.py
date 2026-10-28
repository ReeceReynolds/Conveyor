"""The content-addressed object store: layout, idempotency, atomicity and corruption checks."""

import hashlib
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conveyor.storage import (
    CorruptObjectError,
    InvalidDigestError,
    ObjectNotFoundError,
    ObjectStore,
)

HELLO_DIGEST = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


@pytest.fixture
def objects(tmp_path: Path) -> ObjectStore:
    return ObjectStore(tmp_path / "objects")


@pytest.fixture(scope="module")
def shared_objects(tmp_path_factory: pytest.TempPathFactory) -> ObjectStore:
    """One store for every Hypothesis example (function-scoped fixtures are not reset)."""
    return ObjectStore(tmp_path_factory.mktemp("objects"))


def _files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def test_put_stores_under_the_sha256_digest_with_fan_out(objects: ObjectStore) -> None:
    digest = objects.put(b"hello")

    assert digest == HELLO_DIGEST
    assert _files(objects.root) == [f"2c/{HELLO_DIGEST[2:]}"]
    assert objects.get(digest) == b"hello"
    assert objects.exists(digest)


def test_put_is_idempotent_and_leaves_no_temporary_files(objects: ObjectStore) -> None:
    first = objects.put(b"same")
    path = objects.root / first[:2] / first[2:]
    written = path.stat().st_mtime_ns

    assert objects.put(b"same") == first
    assert path.stat().st_mtime_ns == written
    assert _files(objects.root) == [f"{first[:2]}/{first[2:]}"]


def test_empty_object_round_trips(objects: ObjectStore) -> None:
    digest = objects.put(b"")

    assert digest == hashlib.sha256(b"").hexdigest()
    assert objects.get(digest) == b""


@given(data=st.binary(max_size=4096))
def test_any_bytes_round_trip_under_their_digest(shared_objects: ObjectStore, data: bytes) -> None:
    digest = shared_objects.put(data)

    assert digest == hashlib.sha256(data).hexdigest()
    assert shared_objects.get(digest) == data
    assert shared_objects.put(data) == digest


def test_reopening_a_store_sees_existing_objects(tmp_path: Path) -> None:
    digest = ObjectStore(tmp_path).put(b"kept")

    assert ObjectStore(tmp_path).get(digest) == b"kept"


def test_missing_object_is_reported(objects: ObjectStore) -> None:
    assert not objects.exists(HELLO_DIGEST)
    with pytest.raises(ObjectNotFoundError) as caught:
        objects.get(HELLO_DIGEST)

    assert caught.value.digest == HELLO_DIGEST
    assert str(caught.value) == f"no stored object with digest {HELLO_DIGEST}"


def test_corruption_is_detected_on_read(objects: ObjectStore) -> None:
    digest = objects.put(b"hello")
    (objects.root / digest[:2] / digest[2:]).write_bytes(b"tampered")

    with pytest.raises(CorruptObjectError) as caught:
        objects.get(digest)

    assert caught.value.digest == digest
    assert caught.value.actual == hashlib.sha256(b"tampered").hexdigest()


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "abc",
        HELLO_DIGEST.upper(),
        HELLO_DIGEST + "0",
        "../" + HELLO_DIGEST[3:],
        "g" * 64,
    ],
)
def test_malformed_digests_are_rejected(objects: ObjectStore, digest: str) -> None:
    with pytest.raises(InvalidDigestError) as caught:
        objects.get(digest)
    assert caught.value.digest == digest
    with pytest.raises(InvalidDigestError):
        objects.exists(digest)


def test_failed_write_leaves_nothing_behind(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk_full = OSError("disk full")

    def fail(_self: Path, _target: Path) -> Path:
        raise disk_full

    monkeypatch.setattr(Path, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        objects.put(b"hello")

    assert _files(objects.root) == []
    assert not objects.exists(HELLO_DIGEST)
