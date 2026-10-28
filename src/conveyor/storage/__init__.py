"""Local-first persistence: a migrated SQL database and a content-addressed object store.

All state for a project lives in `<project>/.conveyor/`: `conveyor.db` (SQLite in WAL mode,
with foreign keys enforced) and `objects/` (immutable blobs named by their sha256 digest).
`Store.open` creates both and applies migrations. The storage layer does not interpret what
it stores: an agent snapshot, for example, arrives as opaque bytes.
"""

from conveyor.storage.errors import (
    AmbiguousVersionError,
    CorruptObjectError,
    IncompatibleSchemaError,
    InvalidDigestError,
    InvalidPrefixError,
    ObjectNotFoundError,
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
    "IncompatibleSchemaError",
    "InvalidDigestError",
    "InvalidPrefixError",
    "ObjectNotFoundError",
    "ObjectStore",
    "RegistryRepository",
    "StorageError",
    "Store",
    "UnsupportedDatabaseError",
    "VersionNotFoundError",
]
