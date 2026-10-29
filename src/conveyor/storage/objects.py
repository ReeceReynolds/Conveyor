"""A content-addressed, write-once object store on the local filesystem.

Each object is stored under the sha256 digest of its bytes, fanned out by the first two hex
characters (`objects/ab/cdef...`) so no directory grows unboundedly. Writes go to a temporary
file in the destination directory, are fsynced and moved into place with `os.replace`, and the
directory is fsynced too, so readers never see a partial object and a stored object survives a
crash. The content is verified against its digest on every read, and an existing object is
verified before a write of the same content is skipped.
"""

import errno
import hashlib
import os
import re
import tempfile
from pathlib import Path

from conveyor.storage.errors import CorruptObjectError, InvalidDigestError, ObjectNotFoundError

DIGEST_PATTERN = r"[0-9a-f]{64}"
"""A sha256 digest as stored: 64 lowercase hexadecimal characters."""

_FAN_OUT = 2

_SYNCS_DIRECTORIES = os.name == "posix"
"""Whether directories can be opened and fsynced here (not on Windows)."""

_SYNC_UNSUPPORTED = frozenset({errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP})
"""What `fsync` on a directory fails with on file systems that do not support it."""


def digest_of(data: bytes) -> str:
    """Compute the digest an object is stored under.

    Args:
        data: The object's content.

    Returns:
        The sha256 digest as 64 lowercase hexadecimal characters.
    """
    return hashlib.sha256(data).hexdigest()


def check_digest(digest: str) -> str:
    """Reject anything that is not a well-formed digest.

    Digests become file names, so this also keeps lookups inside the store.

    Args:
        digest: The digest to check.

    Returns:
        The digest, unchanged.

    Raises:
        InvalidDigestError: If it is not 64 lowercase hexadecimal characters.
    """
    if re.fullmatch(DIGEST_PATTERN, digest) is None:
        raise InvalidDigestError(digest)
    return digest


def sync_directory(directory: Path) -> None:
    """Flush a directory's entries to disk, so a file just named in it survives a crash.

    `fsync` on a file makes its content durable but not its name; POSIX needs the directory
    synced as well. Windows cannot open a directory to sync it, so there, and on file systems
    that refuse to sync directories, this does nothing.

    Args:
        directory: The directory to sync.

    Raises:
        OSError: If the directory cannot be opened, or syncing it fails for another reason.
    """
    if not _SYNCS_DIRECTORIES:
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in _SYNC_UNSUPPORTED:
            raise
    finally:
        os.close(descriptor)


class ObjectStore:
    """Immutable blobs addressed by the sha256 digest of their content."""

    def __init__(self, root: Path) -> None:
        """Open (and create, if needed) a store rooted at a directory.

        Args:
            root: The directory holding the fan-out subdirectories.
        """
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        check_digest(digest)
        return self.root / digest[:_FAN_OUT] / digest[_FAN_OUT:]

    def put(self, data: bytes) -> str:
        """Store bytes, unless an object with the same content is already stored intact.

        An existing object is re-hashed first. If its bytes no longer match its digest (the
        disk or someone corrupted it), it is rewritten, so storing content repairs it.

        Args:
            data: The object's content.

        Returns:
            The object's digest, 64 lowercase hexadecimal characters.
        """
        digest = digest_of(data)
        path = self._path(digest)
        if path.is_file() and digest_of(path.read_bytes()) == digest:
            return digest
        new_directory = not path.parent.exists()
        path.parent.mkdir(exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            # Atomic on POSIX and Windows; a concurrent writer of the same digest wrote the same
            # bytes, so whichever replace lands last is equally correct.
            Path(temporary).replace(path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        # The object's bytes are durable; make its name (and a new fan-out folder's) durable too.
        sync_directory(path.parent)
        if new_directory:
            sync_directory(self.root)
        return digest

    def get(self, digest: str) -> bytes:
        """Read an object and verify that its content still matches its digest.

        Args:
            digest: The object's digest.

        Returns:
            The object's content.

        Raises:
            InvalidDigestError: If `digest` is malformed.
            ObjectNotFoundError: If no such object is stored.
            CorruptObjectError: If the stored bytes no longer hash to `digest`.
        """
        path = self._path(digest)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ObjectNotFoundError(digest) from None
        actual = digest_of(data)
        if actual != digest:
            raise CorruptObjectError(digest, actual)
        return data

    def exists(self, digest: str) -> bool:
        """Check whether an object is stored, without reading or verifying it.

        Args:
            digest: The object's digest.

        Returns:
            Whether an object with that digest is stored.

        Raises:
            InvalidDigestError: If `digest` is malformed.
        """
        return self._path(digest).is_file()
