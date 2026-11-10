"""The registry service: publish agent folders as versions, look versions up and compare them.

This module joins the three layers below it: contract resolution (`conveyor.contracts`),
snapshots and diffs (`conveyor.registry`) and storage (`conveyor.storage`). Its functions take
a project root or an open `Store` and return typed results; they print nothing and read no
clock, so the CLI and, later, the HTTP API share one implementation and tests stay
deterministic.

A version is referred to by a *ref*: `latest` (or `None`), a sequence number such as `v3`, or
at least four hex characters of its content ID.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from conveyor.model.checks import AGENT_FILE, AGENTS_DIR, inspect_agent_folder
from conveyor.model.errors import Issue
from conveyor.model.types import SLUG_PATTERN
from conveyor.registry.diff import AgentDiff, diff_snapshots, render, summarise
from conveyor.registry.snapshot import (
    AgentSnapshot,
    SnapshotError,
    build_snapshot,
    canonical_bytes,
    content_id,
    snapshot_from_bytes,
)
from conveyor.storage import (
    AgentVersionRecord,
    AmbiguousVersionError,
    InvalidPrefixError,
    RegistryNotFoundError,
    StorageError,
    Store,
    VersionNotFoundError,
)

LATEST: Final = "latest"
"""The ref naming an agent's newest version."""

WORKING_COPY_LABEL: Final = "working copy"
"""How diffs refer to the agent folder on disk."""

_SEQUENCE_REF = re.compile(r"v(?P<sequence>[0-9]{1,18})")
_PREFIX_REF = re.compile(r"[0-9a-fA-F]{4,64}")


class PublishError(Exception):
    """Raised when an agent folder is invalid, so it cannot be snapshotted or published.

    `str(error)` lists every issue, one `file:line:column: field: message` line each.

    Attributes:
        name: The agent's name.
        issues: Every problem found, in file order.
    """

    def __init__(self, name: str, issues: Iterable[Issue]) -> None:
        """Create the error.

        Args:
            name: The agent's name.
            issues: The problems found; at least one.
        """
        self.name = name
        self.issues: tuple[Issue, ...] = tuple(sorted(issues, key=Issue.sort_key))
        super().__init__("\n".join(issue.render() for issue in self.issues))


class RefProblem(StrEnum):
    """Why a ref did not name exactly one version."""

    MALFORMED = "malformed"
    """The ref is not `latest`, `vN` or a content ID prefix of 4 to 64 hex characters."""
    NOT_FOUND = "not found"
    """No version of the agent matches the ref."""
    AMBIGUOUS = "ambiguous"
    """The content ID prefix matches several different versions."""


class VersionRefError(Exception):
    """Raised when a ref does not name exactly one version of an agent.

    `str(error)` is a one-line message ready to show; for lookups the storage layer rejects,
    it is the storage error's own message.

    Attributes:
        name: The agent's name.
        ref: The ref as given; `None` for the latest version.
        problem: Why the lookup failed.
    """

    def __init__(self, message: str, *, name: str, ref: str | None, problem: RefProblem) -> None:
        """Create the error.

        Args:
            message: What went wrong, in one line.
            name: The agent's name.
            ref: The ref as given.
            problem: Why the lookup failed.
        """
        self.name = name
        self.ref = ref
        self.problem = problem
        super().__init__(message)


_STORAGE_PROBLEMS: dict[type[StorageError], RefProblem] = {
    InvalidPrefixError: RefProblem.MALFORMED,
    VersionNotFoundError: RefProblem.NOT_FOUND,
    AmbiguousVersionError: RefProblem.AMBIGUOUS,
}


class VersionDiff(BaseModel):
    """The difference between two sides, each a stored version or the working copy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="The agent's name.")
    old_label: str = Field(description="How to refer to the old side, e.g. `v3`.")
    new_label: str = Field(description="How to refer to the new side, e.g. `working copy`.")
    diff: AgentDiff = Field(description="Everything that differs, old to new.")

    def summary(self) -> str:
        """Describe the diff in one line.

        Returns:
            For example `implementer v1 → v2: Capabilities changed; ...`.
        """
        return summarise(
            self.diff, name=self.name, old_label=self.old_label, new_label=self.new_label
        )

    def render(self) -> str:
        """Describe the diff in full, with line-by-line text diffs.

        Returns:
            Multi-line text ending in a newline.
        """
        return render(self.diff, name=self.name, old_label=self.old_label, new_label=self.new_label)


class PublishResult(BaseModel):
    """What publishing an agent did."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: AgentVersionRecord = Field(
        description="The version created or, when nothing changed, the unchanged latest one."
    )
    created: bool = Field(description="Whether a new version was recorded.")
    diff: VersionDiff | None = Field(
        description=(
            "The change from the previous version; `None` for a first version or when nothing "
            "was published."
        )
    )


class AgentListing(BaseModel):
    """One agent of a project: its folder, its latest version, or both."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="The agent's name.")
    latest: AgentVersionRecord | None = Field(
        description="The newest published version; `None` if the agent was never published."
    )
    has_folder: bool = Field(description=f"Whether `{AGENTS_DIR}/<name>/{AGENT_FILE}` exists.")


@dataclass(frozen=True)
class WorkingCopy:
    """The side of a diff that is the agent folder on disk, as it would be published.

    Attributes:
        project_root: The project the agent folder is in.
    """

    project_root: Path


type Side = AgentVersionRecord | WorkingCopy
"""One side of a diff: a stored version or the working copy."""


def check_agent_name(name: str) -> str:
    """Check that a name can be an agent's, and so names a folder in `agents/`.

    Args:
        name: The name to check.

    Returns:
        The name, unchanged.

    Raises:
        ValueError: If the name is not a slug (lowercase letters and digits in groups joined
            by single hyphens). Such a name could also reach outside `agents/`.
    """
    if re.fullmatch(SLUG_PATTERN, name) is None:
        message = (
            f"not an agent name: {name!r} (use lowercase letters and digits, joined by single "
            "hyphens)"
        )
        raise ValueError(message)
    return name


def _snapshot_issue(folder: Path, error: SnapshotError) -> Issue:
    file = error.file or folder
    # `SnapshotError` prefixes its message with the file; the issue carries the file itself.
    return Issue(file=file, message=str(error).removeprefix(f"{file}: "))


def snapshot_working_copy(project_root: Path, name: str) -> AgentSnapshot:
    """Validate an agent folder and snapshot it, exactly as `publish` would.

    Args:
        project_root: The project holding `agents/<name>/` and the contract modules.
        name: The agent's name.

    Returns:
        The snapshot of `<project_root>/agents/<name>/`.

    Raises:
        ValueError: If `name` is not an agent name.
        PublishError: If the folder is not a valid agent, its contracts do not resolve, or a
            file cannot be snapshotted.
    """
    folder = project_root / AGENTS_DIR / check_agent_name(name)
    # Links are refused everywhere in an agent (ADR 0013), including the folder itself and
    # its agent.yaml: a linked folder would be validated against another project's contracts.
    # A linked `agents/` does the same to every agent in it, and the snapshot would then hold
    # this project's schemas while validation had checked the other project's.
    for path in (project_root / AGENTS_DIR, folder, folder / AGENT_FILE):
        if path.is_symlink():
            issue = Issue(file=path, message="symbolic links are not followed")
            raise PublishError(name, [issue])
    # Validating reads agent.yaml and resolves the contracts; the snapshot reuses both, so
    # each contract module is imported once per publish (a test counts the imports).
    inspection = inspect_agent_folder(folder)
    if inspection.issues or inspection.agent is None:
        raise PublishError(name, inspection.issues)
    # The instructions and eval files are read again for the snapshot, and can change in
    # between: report the same failures as issues rather than letting them escape.
    try:
        return build_snapshot(folder, inspection.agent, inspection.schemas)
    except SnapshotError as error:
        raise PublishError(name, [_snapshot_issue(folder, error)]) from error


def _label(record: AgentVersionRecord) -> str:
    return f"v{record.sequence}"


def load_snapshot(store: Store, record: AgentVersionRecord) -> AgentSnapshot:
    """Read a stored version's snapshot and check that it is the content it claims to be.

    Args:
        store: The project's store.
        record: The version.

    Returns:
        The snapshot.

    Raises:
        StorageError: If the snapshot is missing or its bytes are corrupt.
        SnapshotError: If the stored bytes are not a snapshot, or not one with the version's
            content ID.
    """
    snapshot = snapshot_from_bytes(store.objects.get(record.snapshot_digest))
    actual = content_id(snapshot)
    if actual != record.content_id:
        message = (
            f"the stored snapshot of {record.agent} {_label(record)} has content ID {actual}, "
            f"not {record.content_id}"
        )
        raise SnapshotError(message)
    return snapshot


def resolve(store: Store, name: str, ref: str | None) -> AgentVersionRecord:
    """Find the version of an agent a ref names.

    Args:
        store: The project's store.
        name: The agent's name.
        ref: `None` or `latest` for the newest version, `vN` for sequence N, or 4 to 64 hex
            characters of a content ID (any case). When several versions share the content
            ID (the agent was reverted to it), the newest of them.

    Returns:
        The version.

    Raises:
        VersionRefError: If the ref is malformed or does not name exactly one version.
    """
    if ref is None or ref == LATEST:
        latest = store.registry.latest(name)
        if latest is None:
            message = f"agent {name!r} has no published versions"
            raise VersionRefError(message, name=name, ref=ref, problem=RefProblem.NOT_FOUND)
        return latest
    sequence = _SEQUENCE_REF.fullmatch(ref)
    if sequence is None and _PREFIX_REF.fullmatch(ref) is None:
        message = (
            f"not a version: {ref!r} (use {LATEST}, vN, or 4 to 64 hex characters of a content ID)"
        )
        raise VersionRefError(message, name=name, ref=ref, problem=RefProblem.MALFORMED)
    try:
        if sequence is not None:
            return store.registry.get(name, int(sequence["sequence"]))
        return store.registry.find(name, ref)
    except (InvalidPrefixError, VersionNotFoundError, AmbiguousVersionError) as error:
        raise VersionRefError(
            str(error), name=name, ref=ref, problem=_STORAGE_PROBLEMS[type(error)]
        ) from error


def previous_version(store: Store, record: AgentVersionRecord) -> AgentVersionRecord | None:
    """Find the version a version follows.

    Args:
        store: The project's store.
        record: The version.

    Returns:
        Its parent, or `None` for an agent's first version.
    """
    if record.parent_sequence is None:
        return None
    return store.registry.get(record.agent, record.parent_sequence)


def _side(store: Store, name: str, side: Side) -> tuple[AgentSnapshot, str]:
    if isinstance(side, WorkingCopy):
        return snapshot_working_copy(side.project_root, name), WORKING_COPY_LABEL
    return load_snapshot(store, side), _label(side)


def diff_versions(store: Store, name: str, old: Side, new: Side) -> VersionDiff:
    """Compare two sides of an agent, each a stored version or the working copy.

    Args:
        store: The project's store, which the stored versions are read from.
        name: The agent's name.
        old: The earlier side.
        new: The later side.

    Returns:
        The diff, with labels such as `v3` and `working copy`.

    Raises:
        PublishError: If a side is the working copy and the folder is not a valid agent.
        StorageError: If a stored snapshot is missing or corrupt.
        SnapshotError: If a stored snapshot is unreadable.
    """
    old_snapshot, old_label = _side(store, name, old)
    new_snapshot, new_label = _side(store, name, new)
    return VersionDiff(
        name=name,
        old_label=old_label,
        new_label=new_label,
        diff=diff_snapshots(old_snapshot, new_snapshot),
    )


def list_agents(project_root: Path) -> tuple[AgentListing, ...]:
    """List a project's agents: every agent folder and every agent with published versions.

    The store is opened read-only, so listing never creates or migrates `.conveyor/`; a
    project without one has nothing published.

    Args:
        project_root: The project holding `agents/` and `.conveyor/`.

    Returns:
        The agents, sorted by name. An agent folder is any folder in `agents/` holding an
        `agent.yaml`, valid or not.

    Raises:
        StorageError: If the store exists but cannot be read.
    """
    folders = {
        folder.name
        for folder in (project_root / AGENTS_DIR).glob("*")
        if (folder / AGENT_FILE).is_file()
    }
    latest: dict[str, AgentVersionRecord] = {}
    try:
        with Store.open(project_root, read_only=True) as store:
            for name in store.registry.agents():
                if (record := store.registry.latest(name)) is not None:
                    latest[name] = record
    except RegistryNotFoundError:
        # Nothing was ever published here; the agent folders are still listed.
        pass
    return tuple(
        AgentListing(name=name, latest=latest.get(name), has_folder=name in folders)
        for name in sorted(folders | latest.keys())
    )


def _require_text(value: str, what: str) -> None:
    if not value.strip():
        message = f"a publish {what} is required"
        raise ValueError(message)


def is_one_line(text: str) -> bool:
    """Whether text holds no line breaks, tabs or other control characters.

    Args:
        text: The text to check.

    Returns:
        `True` if every character is printable or a space.
    """
    return all(character == " " or character.isprintable() for character in text)


def _require_line(value: str, what: str) -> None:
    _require_text(value, what)
    if not is_one_line(value):
        # `history` prints one version per line, and a control character could rewrite the
        # terminal it is printed to.
        message = f"a publish {what} must be one line of text, got {value!r}"
        raise ValueError(message)


def publish(
    project_root: Path, name: str, *, author: str, message: str, now: datetime
) -> PublishResult:
    """Publish the agent in `<project_root>/agents/<name>/` as its next version.

    The folder is validated and snapshotted first; an invalid agent is refused and nothing is
    stored. The snapshot is then written to the object store and recorded as a new version, so
    a version never points to a missing snapshot. If the latest version has the same content,
    nothing is recorded and that version is returned. Content equal to an older version (a
    revert) is still a new version, with the next sequence.

    Publishing is safe to run from several processes at once. Whether the content is
    unchanged is decided in the same locked transaction that records the version (see
    `RegistryRepository.add_version_if_changed`), so publishers of the same content record it
    once, and the diff is always taken from the version the new one actually follows.

    Args:
        project_root: The project holding `agents/` and the contract modules; its state lives
            in `<project_root>/.conveyor/`.
        name: The agent's name.
        author: Who is publishing; one line of text.
        message: Why; must not be blank.
        now: When, as a timezone-aware datetime.

    Returns:
        The version and whether it was created, with the diff from the previous version.

    Raises:
        ValueError: If `name` is not an agent name, `author` or `message` is blank, `author`
            is not one line of printable text, or `now` is naive.
        PublishError: If the agent folder is invalid.
        StorageError: If the store cannot be opened, or the previous snapshot is corrupt.
    """
    _require_text(message, "message")
    _require_line(author, "author")
    if now.utcoffset() is None:
        error = f"the publish time must be timezone-aware, got {now.isoformat()}"
        raise ValueError(error)
    snapshot = snapshot_working_copy(project_root, name)
    snapshot_id = content_id(snapshot)

    with Store.open(project_root) as store:
        digest = store.objects.put(canonical_bytes(snapshot))
        # Check the latest snapshot before recording anything, so a corrupt store fails the
        # publish without leaving a version behind. This read only checks and caches: another
        # publisher may record a version before ours, so it never decides what ours follows.
        latest = store.registry.latest(name)
        checked = {} if latest is None else {latest.sequence: load_snapshot(store, latest)}
        record, created = store.registry.add_version_if_changed(
            agent=name,
            content_id=snapshot_id,
            author=author,
            message=message,
            snapshot_digest=digest,
            created_at=now,
        )
        if not created or record.parent_sequence is None:
            return PublishResult(record=record, created=created, diff=None)
        parent = store.registry.get(name, record.parent_sequence)
        parent_snapshot = checked.get(parent.sequence)
        if parent_snapshot is None:
            parent_snapshot = load_snapshot(store, parent)

    diff = VersionDiff(
        name=name,
        old_label=_label(parent),
        new_label=_label(record),
        diff=diff_snapshots(parent_snapshot, snapshot),
    )
    return PublishResult(record=record, created=True, diff=diff)
