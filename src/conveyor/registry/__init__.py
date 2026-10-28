"""The agent registry: immutable, content-addressed agent versions and their diffs.

An `AgentSnapshot` holds everything that defines one version of an agent. Its `content_id` is
the sha256 of its canonical form, so equal content always gets an equal ID. `diff_snapshots`
compares two snapshots by block, component and primitive, and `summarise` and `render` describe
the result for people. Nothing here touches storage or imports user code.
"""

from conveyor.registry.diff import (
    AgentDiff,
    Block,
    BlockDiff,
    Change,
    Component,
    ComponentDiff,
    Primitive,
    PrimitiveChange,
    TextDiff,
    diff_snapshots,
    render,
    summarise,
)
from conveyor.registry.snapshot import (
    AgentSnapshot,
    EvalFile,
    JsonSchema,
    SnapshotError,
    build_snapshot,
    canonical_bytes,
    content_id,
    short_id,
    snapshot_from_bytes,
)

__all__ = [
    "AgentDiff",
    "AgentSnapshot",
    "Block",
    "BlockDiff",
    "Change",
    "Component",
    "ComponentDiff",
    "EvalFile",
    "JsonSchema",
    "Primitive",
    "PrimitiveChange",
    "SnapshotError",
    "TextDiff",
    "build_snapshot",
    "canonical_bytes",
    "content_id",
    "diff_snapshots",
    "render",
    "short_id",
    "snapshot_from_bytes",
    "summarise",
]
