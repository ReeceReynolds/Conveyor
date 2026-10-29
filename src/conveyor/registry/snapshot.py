"""Agent snapshots: everything that defines one agent version, and its content ID.

A snapshot holds the parsed `agent.yaml`, the text of its instructions, the JSON Schemas of
its input and output contracts, and every file of its eval suite. Its identity is the sha256
of its canonical JSON form (see `conveyor.registry.canonical` and ADR 0013), so the same
content always gets the same ID, on any machine and whatever order keys or files come in.

Building a snapshot reads files but imports nothing: contract schemas are resolved elsewhere
and passed in.
"""

import hashlib
import re
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import Field, JsonValue, ValidationError, field_validator, model_validator

from conveyor.model.agent import Agent
from conveyor.model.base import ConfigModel
from conveyor.registry.canonical import CanonicalFormError, canonical_json, load_canonical_json

type JsonSchema = dict[str, JsonValue]
"""A JSON Schema document, as plain JSON data."""

FORMAT = 1
"""Version of the snapshot's canonical form. Bump it whenever that form changes."""

SHORT_ID_LENGTH = 12
"""Characters kept by `short_id`; 48 bits, enough to tell an agent's versions apart."""

_CONTENT_ID = re.compile(r"[0-9a-f]{64}")
_SKIPPED_DIRS = frozenset({"__pycache__"})
_SKIPPED_SUFFIXES = frozenset({".pyc"})


class SnapshotError(Exception):
    """Raised when an agent folder cannot be snapshotted, or bytes are not a snapshot."""

    def __init__(self, message: str, file: Path | None = None) -> None:
        """Create the error.

        Args:
            message: What is wrong.
            file: The file or folder at fault, when there is one.
        """
        self.file = file
        super().__init__(f"{file}: {message}" if file is not None else message)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _check_relative_posix(path: str) -> str:
    parts = path.split("/")
    if "\\" in path or any(part in {"", ".", ".."} for part in parts):
        message = f"must be a relative POSIX path with no '.', '..' or empty parts, got {path!r}"
        raise ValueError(message)
    return path


class EvalFile(ConfigModel):
    """One file of an agent's eval suite."""

    path: str = Field(description="POSIX path relative to the eval suite, e.g. 'cases/x.yaml'.")
    digest: str = Field(description="sha256 of the UTF-8 encoded content, as lowercase hex.")
    content: str = Field(description="The file's text, with LF line endings.")

    @classmethod
    def of(cls, path: str, content: str) -> Self:
        """Create an eval file, computing its digest.

        Args:
            path: POSIX path relative to the eval suite.
            content: The file's text.

        Returns:
            The eval file.
        """
        return cls(path=path, digest=_sha256(content), content=content)

    @field_validator("path")
    @classmethod
    def _path_is_relative(cls, path: str) -> str:
        return _check_relative_posix(path)

    @model_validator(mode="after")
    def _digest_matches(self) -> Self:
        if self.digest != _sha256(self.content):
            message = "digest does not match content"
            raise ValueError(message)
        return self


class AgentSnapshot(ConfigModel):
    """Everything that defines one version of an agent, and nothing else.

    The folder the agent lives in is not part of it; the files the agent points to are, by
    content. See ADR 0013 for what is and is not part of an agent's identity.
    """

    format: Literal[1] = Field(
        default=FORMAT, description="Version of the canonical form this snapshot follows."
    )
    agent: Agent = Field(description="The parsed `agent.yaml`.")
    instructions: str = Field(description="Text of the instructions file, with LF line endings.")
    input_schema: JsonSchema = Field(description="JSON Schema of the input contract.")
    output_schema: JsonSchema = Field(description="JSON Schema of the output contract.")
    eval_files: tuple[EvalFile, ...] = Field(
        default=(), description="Every file of the eval suite, sorted by path."
    )

    @field_validator("eval_files")
    @classmethod
    def _sorted_and_unique(cls, files: tuple[EvalFile, ...]) -> tuple[EvalFile, ...]:
        ordered = tuple(sorted(files, key=lambda file: file.path))
        for previous, current in pairwise(ordered):
            if previous.path == current.path:
                message = f"duplicate eval file {current.path!r}"
                raise ValueError(message)
        return ordered

    @model_validator(mode="after")
    def _has_canonical_form(self) -> Self:
        # Pydantic accepts NaN and unbounded integers that JSON cannot carry exactly. Reject
        # them here so every snapshot has an ID and `canonical_bytes` never fails.
        try:
            canonical_json(self.model_dump(mode="json"))
        except CanonicalFormError as error:
            raise ValueError(str(error)) from error
        return self


def canonical_bytes(snapshot: AgentSnapshot) -> bytes:
    """Serialise a snapshot in canonical form (RFC 8785 JSON, UTF-8).

    Args:
        snapshot: The snapshot.

    Returns:
        Bytes that depend only on the snapshot's content.
    """
    return canonical_json(snapshot.model_dump(mode="json"))


def content_id(snapshot: AgentSnapshot) -> str:
    """Compute a snapshot's content ID.

    Args:
        snapshot: The snapshot.

    Returns:
        The sha256 of `canonical_bytes(snapshot)`, as 64 lowercase hex characters.
    """
    return hashlib.sha256(canonical_bytes(snapshot)).hexdigest()


def short_id(content_id: str) -> str:
    """Shorten a content ID for display.

    Args:
        content_id: A full content ID, as returned by `content_id`.

    Returns:
        Its first 12 characters.

    Raises:
        ValueError: If `content_id` is not 64 lowercase hex characters.
    """
    if _CONTENT_ID.fullmatch(content_id) is None:
        message = f"not a content ID (64 lowercase hex characters): {content_id!r}"
        raise ValueError(message)
    return content_id[:SHORT_ID_LENGTH]


def snapshot_from_bytes(data: bytes) -> AgentSnapshot:
    """Read back a snapshot written by `canonical_bytes`.

    Args:
        data: Canonical snapshot bytes.

    Returns:
        The snapshot; `canonical_bytes` of it equals `data`.

    Raises:
        SnapshotError: If `data` is not a valid snapshot in canonical form.
    """
    try:
        snapshot = AgentSnapshot.model_validate(load_canonical_json(data))
    except (CanonicalFormError, ValidationError) as error:
        message = f"not a canonical agent snapshot: {error}"
        raise SnapshotError(message) from error
    if canonical_bytes(snapshot) != data:
        # The JSON was canonical but validation changed it, e.g. by filling in a default.
        message = "not a canonical agent snapshot: content changes when read back"
        raise SnapshotError(message)
    return snapshot


def _read_text(file: Path) -> str:
    """Read a text file the same way on every platform.

    The file must be a regular file, not a symbolic link: a link would bring content from
    outside the agent folder into its identity, and Git on Windows checks links out as small
    text files, so the same commit would hash differently. The bytes must be UTF-8; a leading
    byte order mark is dropped and CRLF line endings become LF.
    """
    if file.is_symlink():
        message = "symbolic links are not followed"
        raise SnapshotError(message, file)
    if not file.is_file():
        message = "not a regular file" if file.exists() else "file not found"
        raise SnapshotError(message, file)
    data = file.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        message = f"not UTF-8 text (invalid byte at offset {error.start})"
        raise SnapshotError(message, file) from error
    return text.replace("\r\n", "\n")


def _skipped(name: str, *, is_dir: bool) -> bool:
    if name.startswith("."):
        return True
    if is_dir:
        return name in _SKIPPED_DIRS
    return PurePosixPath(name).suffix in _SKIPPED_SUFFIXES


def read_eval_suite(suite: Path) -> tuple[EvalFile, ...]:
    """Read every file of an eval suite.

    A suite is a folder, read recursively, or a single file. Names starting with a dot
    (`.gitkeep`, `.DS_Store`, `.pytest_cache/`), `__pycache__/` folders and `*.pyc` files are
    skipped: they are tooling noise, not part of the Quality Gate. Everything else must be a
    regular UTF-8 text file (see `build_snapshot`).

    Args:
        suite: The suite folder or file.

    Returns:
        The suite's files, sorted by path. Paths are relative to the suite; a single-file
        suite holds one file named after itself.

    Raises:
        SnapshotError: If the suite is missing, or holds a link or a file that is not text.
    """
    if suite.is_symlink() or not suite.exists():
        message = "eval suite is a symbolic link" if suite.is_symlink() else "eval suite not found"
        raise SnapshotError(message, suite)
    if not suite.is_dir():
        return (EvalFile.of(suite.name, _read_text(suite)),)

    files: list[EvalFile] = []
    for folder, dirs, names in suite.walk():
        # Prune in place so skipped folders are never entered.
        dirs[:] = [name for name in dirs if not _skipped(name, is_dir=True)]
        for name in names:
            if not _skipped(name, is_dir=False):
                file = folder / name
                files.append(EvalFile.of(file.relative_to(suite).as_posix(), _read_text(file)))
    return tuple(sorted(files, key=lambda file: file.path))


def _inside(folder: Path, path: PurePosixPath) -> Path:
    """Join a path from `agent.yaml` to the agent folder, refusing links to folders on the way.

    Without this, `prompts/main.md` with `prompts` a link would read a file from anywhere. The
    last part is checked by whoever reads it, so it gets a more specific message.
    """
    target = folder
    for part in path.parts[:-1]:
        target /= part
        if target.is_symlink():
            message = "symbolic links are not followed"
            raise SnapshotError(message, target)
    return folder / path


def _schema(contract_schemas: Mapping[str, JsonSchema], ref: str, field: str) -> JsonSchema:
    try:
        return contract_schemas[ref]
    except KeyError:
        message = f"no JSON Schema given for {field} contract {ref!r}"
        raise SnapshotError(message) from None


def build_snapshot(
    folder: Path, agent: Agent, contract_schemas: Mapping[str, JsonSchema]
) -> AgentSnapshot:
    """Snapshot an agent from its folder.

    Reads the instructions file and every file of the eval suite. Text must be UTF-8; line
    endings are normalised from CRLF to LF and a byte order mark is dropped, so an agent
    checked out on Windows hashes the same as on Linux or macOS. Symbolic links are refused,
    including links to folders on the way to a file.

    Args:
        folder: The agent's folder; the paths in `agent` are relative to it.
        agent: The agent's parsed `agent.yaml`.
        contract_schemas: JSON Schemas of contracts, keyed by reference (e.g.
            `contracts.TaskList`); must include the agent's input and output.

    Returns:
        The snapshot.

    Raises:
        SnapshotError: If a file is missing, not regular, not UTF-8 text or reached through a
            symbolic link, a contract schema is missing, or the content cannot be represented
            exactly in JSON.
    """
    input_schema = _schema(contract_schemas, agent.brief.input, "input")
    output_schema = _schema(contract_schemas, agent.brief.output, "output")
    instructions = _read_text(_inside(folder, agent.brief.instructions))
    eval_files = read_eval_suite(_inside(folder, agent.quality_gate.suite))
    try:
        return AgentSnapshot(
            agent=agent,
            instructions=instructions,
            input_schema=input_schema,
            output_schema=output_schema,
            eval_files=eval_files,
        )
    except ValidationError as error:
        message = f"cannot snapshot agent {agent.name!r}: {error}"
        raise SnapshotError(message, folder) from error
