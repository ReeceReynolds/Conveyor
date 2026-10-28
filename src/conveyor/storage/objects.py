"""A content-addressed, write-once object store on the local filesystem.

Each object is stored under the sha256 digest of its bytes, fanned out by the first two hex
characters (`objects/ab/cdef...`) so no directory grows unboundedly. Writes go to a temporary
file in the destination directory and are moved into place with `os.replace`, so readers never
see a partial object, and the content is verified against its digest on every read.
"""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from conveyor.storage.errors import CorruptObjectError, InvalidDigestError, ObjectNotFoundError

DIGEST_PATTERN = r"[0-9a-f]{64}"
"""A sha256 digest as stored: 64 lowercase hexadecimal characters."""

_FAN_OUT = 2


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
        """Store bytes, unless an object with the same content is already stored.

        Args:
            data: The object's content.

        Returns:
            The object's digest, 64 lowercase hexadecimal characters.
        """
        digest = digest_of(data)
        path = self._path(digest)
        if path.is_file():
            return digest
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
