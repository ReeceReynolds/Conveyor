"""Errors raised by the storage layer. Each is specific enough to act on without parsing text."""

from collections.abc import Iterable


class StorageError(Exception):
    """Base class for every storage error."""


class UnsupportedDatabaseError(StorageError):
    """Raised when a database URL names a backend Conveyor does not support."""

    def __init__(self, backend: str) -> None:
        """Create the error.

        Args:
            backend: The backend named by the URL, such as `mysql`.
        """
        self.backend = backend
        super().__init__(f"unsupported database {backend!r}; use sqlite or postgresql")


class IncompatibleSchemaError(StorageError):
    """Raised when a database was migrated by a newer Conveyor than the one opening it."""


class InvalidDigestError(StorageError, ValueError):
    """Raised when an object digest is not 64 lowercase hexadecimal characters."""

    def __init__(self, digest: str) -> None:
        """Create the error.

        Args:
            digest: The malformed digest.
        """
        self.digest = digest
        super().__init__(f"not a sha256 digest (64 lowercase hex characters): {digest!r}")


class ObjectNotFoundError(StorageError):
    """Raised when no object with the requested digest is stored."""

    def __init__(self, digest: str) -> None:
        """Create the error.

        Args:
            digest: The digest that was looked up.
        """
        self.digest = digest
        super().__init__(f"no stored object with digest {digest}")


class CorruptObjectError(StorageError):
    """Raised when a stored object's content no longer matches its digest."""

    def __init__(self, digest: str, actual: str) -> None:
        """Create the error.

        Args:
            digest: The digest the object is stored under.
            actual: The digest of the bytes actually read.
        """
        self.digest = digest
        self.actual = actual
        super().__init__(f"object {digest} is corrupt: its content hashes to {actual}")


class InvalidPrefixError(StorageError, ValueError):
    """Raised when a version id prefix is too short or not hexadecimal."""

    def __init__(self, prefix: str) -> None:
        """Create the error.

        Args:
            prefix: The rejected prefix.
        """
        self.prefix = prefix
        super().__init__(f"a version id prefix needs 4 to 64 hex characters, got {prefix!r}")


class VersionNotFoundError(StorageError):
    """Raised when an agent has no version matching a sequence number or id prefix."""

    def __init__(self, agent: str, reference: str) -> None:
        """Create the error.

        Args:
            agent: The agent name.
            reference: What was looked up, such as `v3` or an id prefix.
        """
        self.agent = agent
        self.reference = reference
        super().__init__(f"agent {agent!r} has no version {reference}")


class AmbiguousVersionError(StorageError):
    """Raised when an id prefix matches more than one distinct version id of an agent."""

    def __init__(self, agent: str, prefix: str, matches: Iterable[str]) -> None:
        """Create the error.

        Args:
            agent: The agent name.
            prefix: The prefix that was looked up.
            matches: The distinct version ids the prefix matches.
        """
        self.agent = agent
        self.prefix = prefix
        self.matches: tuple[str, ...] = tuple(sorted(matches))
        listed = ", ".join(self.matches)
        super().__init__(f"prefix {prefix!r} matches several versions of {agent!r}: {listed}")
