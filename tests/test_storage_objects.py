"""The content-addressed object store: layout, idempotency, atomicity and corruption checks."""

import errno
import hashlib
import os
import stat
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conveyor.storage import (
    CorruptObjectError,
    InvalidDigestError,
    ObjectNotFoundError,
    ObjectStore,
    StateUnavailableError,
)
from conveyor.storage import objects as objects_module
from conveyor.storage.objects import sync_directory

HELLO_DIGEST = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

SYNCS_DIRECTORIES = os.name == "posix"
"""Whether this platform can open a directory to fsync it (not Windows)."""


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


def test_put_repairs_a_corrupt_object(objects: ObjectStore) -> None:
    digest = objects.put(b"hello")
    path = objects.root / digest[:2] / digest[2:]
    path.write_bytes(b"tampered")

    assert objects.put(b"hello") == digest

    assert objects.get(digest) == b"hello"
    assert _files(objects.root) == [f"2c/{HELLO_DIGEST[2:]}"]


def _same_fan_out(digest: str) -> bytes:
    """Content, other than `hello`, whose digest shares the fan-out folder of `digest`."""
    return next(
        data
        for data in (f"other {n}".encode() for n in range(10_000))
        if hashlib.sha256(data).hexdigest()[:2] == digest[:2]
    )


def test_put_makes_the_object_and_its_name_durable(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, int]] = []
    real_fsync, real_replace = os.fsync, Path.replace

    def fsync(descriptor: int) -> None:
        info = os.fstat(descriptor)
        events.append(("sync dir" if stat.S_ISDIR(info.st_mode) else "sync file", info.st_ino))
        real_fsync(descriptor)

    def replace(self: Path, target: Path) -> Path:
        events.append(("replace", self.stat().st_ino))
        return real_replace(self, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)

    first = objects.put(b"hello")
    file = (objects.root / first[:2] / first[2:]).stat().st_ino
    fan_out = (objects.root / first[:2]).stat().st_ino
    root = objects.root.stat().st_ino
    # A new fan-out folder is itself a new name, in the root. Windows cannot sync folders.
    folders = [("sync dir", fan_out), ("sync dir", root)] if SYNCS_DIRECTORIES else []
    assert events == [("sync file", file), ("replace", file), *folders]

    events.clear()
    second = objects.put(_same_fan_out(first))
    other = (objects.root / second[:2] / second[2:]).stat().st_ino
    folders = [("sync dir", fan_out)] if SYNCS_DIRECTORIES else []
    assert events == [("sync file", other), ("replace", other), *folders]

    events.clear()
    objects.put(b"hello")
    assert events == []


def test_directories_are_not_synced_where_that_is_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []
    real_open = os.open

    def record_open(path: Path, flags: int) -> int:
        opened.append(path)
        return real_open(path, flags)

    monkeypatch.setattr(objects_module, "_SYNCS_DIRECTORIES", False)
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", record_open)
        sync_directory(tmp_path)
    assert opened == []


@pytest.mark.skipif(not SYNCS_DIRECTORIES, reason="Windows cannot open a directory to sync it")
@pytest.mark.parametrize(
    ("error", "raised"),
    [(errno.EINVAL, False), (errno.ENOTSUP, False), (errno.EIO, True)],
    ids=["EINVAL", "ENOTSUP", "EIO"],
)
def test_syncing_a_directory_tolerates_only_file_systems_that_cannot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: int, raised: bool
) -> None:
    def fail(_descriptor: int) -> None:
        raise OSError(error, os.strerror(error))

    monkeypatch.setattr(os, "fsync", fail)

    if raised:
        with pytest.raises(OSError, match=os.strerror(error)):
            sync_directory(tmp_path)
    else:
        sync_directory(tmp_path)


def test_failed_write_leaves_nothing_behind(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk_full = OSError("disk full")

    def fail(_self: Path, _target: Path) -> Path:
        raise disk_full

    monkeypatch.setattr(Path, "replace", fail)

    with pytest.raises(StateUnavailableError) as caught:
        objects.put(b"hello")

    assert caught.value.reason == "disk full"
    assert caught.value.path == objects.root / HELLO_DIGEST[:2] / HELLO_DIGEST[2:]

    assert _files(objects.root) == []
    assert not objects.exists(HELLO_DIGEST)


def test_a_full_disk_is_reported_with_the_operating_systems_reason(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_descriptor: int) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(os, "fsync", fail)

    with pytest.raises(StateUnavailableError) as caught:
        objects.put(b"hello")

    assert caught.value.reason == os.strerror(errno.ENOSPC)
    assert _files(objects.root) == []


def test_an_unreadable_object_is_a_storage_error(objects: ObjectStore) -> None:
    path = objects.root / HELLO_DIGEST[:2] / HELLO_DIGEST[2:]
    path.mkdir(parents=True)

    with pytest.raises(StateUnavailableError) as caught:
        objects.get(HELLO_DIGEST)

    assert caught.value.path == path
    # Windows refuses to open a folder as a file rather than naming the problem.
    assert caught.value.reason == os.strerror(errno.EISDIR if os.name == "posix" else errno.EACCES)


def test_a_file_where_a_fan_out_folder_goes_is_a_storage_error(objects: ObjectStore) -> None:
    (objects.root / HELLO_DIGEST[:2]).write_text("in the way\n")

    with pytest.raises(StateUnavailableError, match="not a folder"):
        objects.put(b"hello")
    with pytest.raises(StateUnavailableError) as caught:
        objects.get(HELLO_DIGEST)

    assert caught.value.path == objects.root / HELLO_DIGEST[:2]
    assert caught.value.reason == "not a folder"


def _replace_refused(_self: Path, _target: Path) -> Path:
    """`Path.replace` as Windows does it when another process has the target open."""
    raise PermissionError(errno.EACCES, "Access is denied")


def test_a_refused_replace_of_an_intact_object_is_a_completed_write(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent writer of the same content stored it first and holds it open."""

    def other_writer_first(_self: Path, target: Path) -> Path:
        target.write_bytes(b"hello")
        return _replace_refused(_self, target)

    monkeypatch.setattr(Path, "replace", other_writer_first)

    assert objects.put(b"hello") == HELLO_DIGEST

    monkeypatch.undo()
    assert objects.get(HELLO_DIGEST) == b"hello"
    assert _files(objects.root) == [f"2c/{HELLO_DIGEST[2:]}"]


def test_a_refused_replace_of_anything_else_is_a_storage_error(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "replace", _replace_refused)

    with pytest.raises(StateUnavailableError, match="Access is denied"):
        objects.put(b"hello")

    assert _files(objects.root) == []


def _refuse_reads(monkeypatch: pytest.MonkeyPatch, times: int) -> list[Path]:
    """Make the next `times` reads fail as Windows fails them during another writer's replace."""
    original = Path.read_bytes
    reads: list[Path] = []

    def read_bytes(self: Path) -> bytes:
        reads.append(self)
        if len(reads) <= times:
            raise PermissionError(errno.EACCES, "Permission denied")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    return reads


def test_a_read_refused_during_a_concurrent_replace_is_retried(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows CI hit this: one publisher checked the object while another replaced it.
    objects.put(b"hello")
    monkeypatch.setattr(objects_module, "_READS_REFUSED_DURING_REPLACE", True)
    monkeypatch.setattr(objects_module, "_REPLACE_RETRY_SECONDS", 0)
    reads = _refuse_reads(monkeypatch, times=2)

    assert objects.put(b"hello") == HELLO_DIGEST

    assert len(reads) == 3
    assert _files(objects.root) == [f"2c/{HELLO_DIGEST[2:]}"]


def test_a_refused_replace_whose_check_is_refused_too_is_retried(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Our replace is refused, and so is the read that checks the other writer's copy."""
    original_replace = Path.replace

    def other_writer_first(self: Path, target: Path) -> Path:
        original_replace(self, target)
        raise PermissionError(errno.EACCES, "Access is denied")

    monkeypatch.setattr(objects_module, "_READS_REFUSED_DURING_REPLACE", True)
    monkeypatch.setattr(objects_module, "_REPLACE_RETRY_SECONDS", 0)
    monkeypatch.setattr(Path, "replace", other_writer_first)
    original_read = Path.read_bytes
    reads: list[Path] = []

    def read_bytes(self: Path) -> bytes:
        reads.append(self)
        # The first check, before writing, finds no object; the next read is refused once.
        if len(reads) == 1:
            raise PermissionError(errno.EACCES, "Permission denied")
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    assert objects.put(b"hello") == HELLO_DIGEST

    monkeypatch.undo()
    assert objects.get(HELLO_DIGEST) == b"hello"
    assert len(reads) == 2


def test_a_read_refused_for_longer_than_a_replace_takes_is_a_storage_error(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects.put(b"hello")
    monkeypatch.setattr(objects_module, "_READS_REFUSED_DURING_REPLACE", True)
    monkeypatch.setattr(objects_module, "_REPLACE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(objects_module, "_REPLACE_RETRY_SECONDS", 0.01)
    reads = _refuse_reads(monkeypatch, times=10_000)

    with pytest.raises(StateUnavailableError, match="Permission denied"):
        objects.put(b"hello")

    assert len(reads) > 1


def test_a_refused_read_is_not_retried_where_replacing_never_causes_one(
    objects: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects.put(b"hello")
    monkeypatch.setattr(objects_module, "_READS_REFUSED_DURING_REPLACE", False)
    reads = _refuse_reads(monkeypatch, times=1)

    with pytest.raises(StateUnavailableError, match="Permission denied"):
        objects.put(b"hello")

    assert len(reads) == 1
