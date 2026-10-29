"""The agent registry: immutable, content-addressed agent versions and their diffs.

An `AgentSnapshot` holds everything that defines one version of an agent. Its `content_id` is
the sha256 of its canonical form, so equal content always gets an equal ID. `diff_snapshots`
compares two snapshots by block, component and primitive, and `summarise` and `render` describe
the result for people. Those modules touch neither storage nor user code.

`conveyor.registry.service` joins them to contract resolution and storage: `publish` turns an
agent folder into its next version, `resolve` finds the version a ref such as `v3` names, and
`diff_versions` compares stored versions with each other or with the working copy.
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
from conveyor.registry.service import (
    LATEST,
    WORKING_COPY_LABEL,
    PublishError,
    PublishResult,
    RefProblem,
    Side,
    VersionDiff,
    VersionRefError,
    WorkingCopy,
    check_agent_name,
    diff_versions,
    load_snapshot,
    previous_version,
    publish,
    resolve,
    snapshot_working_copy,
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
    "LATEST",
    "WORKING_COPY_LABEL",
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
    "PublishError",
    "PublishResult",
    "RefProblem",
    "Side",
    "SnapshotError",
    "TextDiff",
    "VersionDiff",
    "VersionRefError",
    "WorkingCopy",
    "build_snapshot",
    "canonical_bytes",
    "check_agent_name",
    "content_id",
    "diff_snapshots",
    "diff_versions",
    "load_snapshot",
    "previous_version",
    "publish",
    "render",
    "resolve",
    "short_id",
    "snapshot_from_bytes",
    "snapshot_working_copy",
    "summarise",
]
