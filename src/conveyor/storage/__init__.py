"""Local-first persistence: a migrated SQL database and a content-addressed object store.

All state for a project lives in `<project>/.conveyor/`: `conveyor.db` (SQLite in WAL mode,
with foreign keys enforced) and `objects/` (immutable blobs named by their sha256 digest).
`Store.open` creates both and applies migrations; `Store.open(..., read_only=True)` creates
and migrates nothing, for commands that only read. The storage layer does not interpret what
it stores: an agent snapshot, for example, arrives as opaque bytes.
"""

from conveyor.storage.errors import (
    AmbiguousVersionError,
    CorruptObjectError,
    DatabaseUnavailableError,
    IncompatibleSchemaError,
    InvalidDigestError,
    InvalidPrefixError,
    MigrationError,
    MigrationRequiredError,
    ObjectNotFoundError,
    RegistryNotFoundError,
    StateUnavailableError,
    StorageError,
    UnsupportedDatabaseError,
    VersionNotFoundError,
)
from conveyor.storage.objects import ObjectStore
from conveyor.storage.registry import AgentVersionRecord, RegistryRepository
from conveyor.storage.store import STATE_DIR, Store

__all__ = [
    "STATE_DIR",
    "AgentVersionRecord",
    "AmbiguousVersionError",
    "CorruptObjectError",
    "DatabaseUnavailableError",
    "IncompatibleSchemaError",
    "InvalidDigestError",
    "InvalidPrefixError",
    "MigrationError",
    "MigrationRequiredError",
    "ObjectNotFoundError",
    "ObjectStore",
    "RegistryNotFoundError",
    "RegistryRepository",
    "StateUnavailableError",
    "StorageError",
    "Store",
    "UnsupportedDatabaseError",
    "VersionNotFoundError",
]
