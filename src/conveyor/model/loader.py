"""Load configuration YAML into models, reporting problems by file, line, column and field.

YAML is parsed with ruamel.yaml (see ADR 0009): YAML 1.2 semantics and a safe, pure-Python
composer whose node tree records where every key, value and item starts. This module walks
that tree into plain dicts, lists and scalars plus an index of positions, rejecting duplicate
keys, explicit tags and merge keys along the way. It is the only place that touches ruamel.
"""

import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails
from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError
from ruamel.yaml.reader import ReaderError

from conveyor.model.agent import Agent
from conveyor.model.base import ConfigModel, Loc, RuleViolation
from conveyor.model.errors import ConfigError, Issue
from conveyor.model.factory import UNION_TAGS, Factory, raw_stage_graph_violations

_MESSAGES = {
    "missing": "required field is missing",
    "extra_forbidden": "unknown field",
    "model_type": "must be a mapping of fields",
}

_CORE = "tag:yaml.org,2002:"
_MAP, _SEQ, _MERGE = f"{_CORE}map", f"{_CORE}seq", f"{_CORE}merge"
_SCALAR_TAGS = frozenset(f"{_CORE}{name}" for name in ("str", "int", "float", "bool", "null"))
# YAML 1.2 has no timestamp type, but ruamel resolves dates anyway; keep them as text.
_TIMESTAMP = f"{_CORE}timestamp"
MAX_VALUES = 100_000
"""Most values one document may expand to.

Aliases can nest, so a few lines can expand to billions of values. Real configuration is
nowhere near this; the cap keeps a hostile or mistaken file from hanging validation.
"""


# ruamel.yaml's node and error attributes are unannotated, so strict type checking sees them as
# Unknown. These protocols describe the parts this module reads; ruamel's objects satisfy them
# structurally, so no casts or ignores are needed.
class _Mark(Protocol):
    @property
    def line(self) -> int: ...
    @property
    def column(self) -> int: ...


class _Node(Protocol):
    @property
    def tag(self) -> str | None: ...
    @property
    def value(self) -> str | list[_Node] | list[tuple[_Node, _Node]]: ...
    @property
    def start_mark(self) -> _Mark: ...


class _Constructor(Protocol):
    def construct_object(self, node: _Node) -> object: ...


class _Yaml(Protocol):
    @property
    def constructor(self) -> _Constructor: ...
    def compose(self, stream: str) -> _Node | None: ...


class _YamlDumper(Protocol):
    def dump(self, data: object, stream: IO[str]) -> object: ...


class _LocatedError(Protocol):
    @property
    def context(self) -> str | None: ...
    @property
    def problem(self) -> str | None: ...
    @property
    def problem_mark(self) -> _Mark | None: ...


class _CharacterError(Protocol):
    @property
    def position(self) -> int: ...
    @property
    def character(self) -> int: ...


@dataclass(frozen=True)
class Position:
    """A 1-based line and column in a file."""

    line: int
    column: int

    @classmethod
    def of(cls, mark: _Mark) -> Position:
        """Convert one of ruamel's 0-based marks."""
        return cls(mark.line + 1, mark.column + 1)


_START = Position(1, 1)


@dataclass(frozen=True)
class Document:
    """A parsed YAML document: plain data plus where each part of it was written.

    Attributes:
        file: The file the document was read from.
        data: The document as plain dicts, lists and scalars.
        keys: Position of each mapping key, by location.
        values: Position of each value or sequence item, by location.
    """

    file: Path
    data: object
    keys: Mapping[Loc, Position]
    values: Mapping[Loc, Position]

    def __contains__(self, loc: Loc) -> bool:
        """Whether `loc` was written in the document."""
        return loc in self.values

    def position(self, loc: Loc, *, of_key: bool = False) -> Position:
        """Find where `loc` was written, or its nearest written ancestor.

        Args:
            loc: The location to find.
            of_key: Prefer the position of the key over that of its value.

        Returns:
            The best known position; the start of the file if nothing closer is known.
        """
        if of_key and loc in self.keys:
            return self.keys[loc]
        if loc in self.values:
            return self.values[loc]
        for end in range(len(loc) - 1, 0, -1):
            ancestor = loc[:end]
            if ancestor in self.keys:
                return self.keys[ancestor]
            if ancestor in self.values:
                return self.values[ancestor]
        return self.values.get((), _START)

    def issue(self, loc: Loc, message: str, *, of_key: bool = False) -> Issue:
        """Create an issue positioned at `loc`.

        Args:
            loc: Where the problem is.
            message: What is wrong.
            of_key: Point at the key rather than its value.

        Returns:
            The issue.
        """
        position = self.position(loc, of_key=of_key)
        return Issue(
            file=self.file, line=position.line, column=position.column, loc=loc, message=message
        )


class _Converter:
    """Walks ruamel's composed node tree into plain data, recording positions as it goes."""

    def __init__(self, file: Path, constructor: _Constructor) -> None:
        self.file = file
        self.constructor = constructor
        self.keys: dict[Loc, Position] = {}
        self.values: dict[Loc, Position] = {}
        self.issues: list[Issue] = []
        self._ancestors: list[int] = []
        self._count = 0

    def _problem(self, mark: _Mark, loc: Loc, message: str) -> None:
        position = Position.of(mark)
        self.issues.append(
            Issue(
                file=self.file,
                line=position.line,
                column=position.column,
                loc=loc,
                message=message,
            )
        )

    def convert(self, node: _Node, loc: Loc) -> object:
        """Convert `node`, found at `loc`, into plain data."""
        self.values[loc] = Position.of(node.start_mark)
        self._count += 1
        if self._count > MAX_VALUES:
            message = f"document expands to more than {MAX_VALUES:,} values; check its aliases"
            self._problem(node.start_mark, loc, message)
            raise ConfigError(self.issues)
        if id(node) in self._ancestors:
            self._problem(node.start_mark, loc, "recursive YAML aliases are not supported")
            return None
        self._ancestors.append(id(node))
        try:
            return self._convert(node, loc)
        finally:
            self._ancestors.pop()

    def _convert(self, node: _Node, loc: Loc) -> object:
        value = node.value
        if isinstance(value, str):
            if node.tag in _SCALAR_TAGS:
                return self.constructor.construct_object(node)
            if node.tag == _TIMESTAMP:
                return value
        elif node.tag == _SEQ:
            return [self.convert(item, (*loc, i)) for i, item in enumerate(_nodes(value))]
        elif node.tag == _MAP:
            return self._mapping(_pairs(value), loc)
        self._problem(node.start_mark, loc, f"unsupported YAML tag {node.tag!r}")
        return None

    def _mapping(self, pairs: list[tuple[_Node, _Node]], loc: Loc) -> dict[object, object]:
        result: dict[object, object] = {}
        for key_node, value_node in pairs:
            if key_node.tag == _MERGE:
                self._problem(key_node.start_mark, loc, "merge keys ('<<') are not supported")
                continue
            reported = len(self.issues)
            key = self._convert(key_node, loc) if isinstance(key_node.value, str) else None
            if not isinstance(key, str | int):
                if len(self.issues) == reported:
                    self._problem(key_node.start_mark, loc, "mapping keys must be plain scalars")
                continue
            child = (*loc, key)
            if key in result:
                first = self.keys[child]
                message = f"duplicate key {key!r} (first defined on line {first.line})"
                self._problem(key_node.start_mark, child, message)
                continue
            self.keys[child] = Position.of(key_node.start_mark)
            result[key] = self.convert(value_node, child)
        return result


def _nodes(value: list[_Node] | list[tuple[_Node, _Node]]) -> list[_Node]:
    return [item for item in value if not isinstance(item, tuple)]


def _pairs(value: list[_Node] | list[tuple[_Node, _Node]]) -> list[tuple[_Node, _Node]]:
    return [item for item in value if isinstance(item, tuple)]


# Returning ruamel's objects through these functions gives call sites the protocol types above;
# a plain annotated assignment would be narrowed back to ruamel's own, unannotated, types.
def _safe_yaml() -> _Yaml:
    return YAML(typ="safe", pure=True)


def _safe_yaml_dumper() -> _YamlDumper:
    return YAML(typ="safe", pure=True)


def _located(error: MarkedYAMLError) -> _LocatedError:
    return error


def _unprintable(error: ReaderError) -> _CharacterError:
    return error


def _position_at(text: str, index: int) -> Position:
    line_start = text.rfind("\n", 0, index) + 1
    return Position(text.count("\n", 0, index) + 1, index - line_start + 1)


def parse_yaml(text: str, file: Path) -> Document:
    """Parse one YAML document, keeping the position of every key and value.

    Args:
        text: The YAML source.
        file: Where the source came from, for error reporting.

    Returns:
        The parsed document.

    Raises:
        ConfigError: If the YAML is malformed, empty, has duplicate keys, uses explicit
            tags, merge keys or recursive aliases, or expands to more than `MAX_VALUES`
            values.
    """
    yaml = _safe_yaml()
    try:
        root = yaml.compose(text)
    except MarkedYAMLError as raw_error:
        error = _located(raw_error)
        position = Position.of(error.problem_mark) if error.problem_mark else _START
        problem = error.problem or "invalid YAML"
        if error.context and problem.startswith("but "):
            # e.g. "expected a single document in the stream" + "but found another document"
            problem = f"{error.context} {problem}"
        issue = Issue(file=file, line=position.line, column=position.column, message=problem)
        raise ConfigError([issue]) from None
    except ReaderError as raw_error:
        # Raised before parsing starts, for characters YAML forbids, such as most controls.
        error = _unprintable(raw_error)
        position = _position_at(text, error.position)
        message = f"character U+{error.character:04X} is not allowed in YAML"
        issue = Issue(file=file, line=position.line, column=position.column, message=message)
        raise ConfigError([issue]) from None
    if root is None:
        raise ConfigError([Issue(file=file, line=1, column=1, message="file is empty")])
    converter = _Converter(file, yaml.constructor)
    data = converter.convert(root, ())
    if converter.issues:
        raise ConfigError(converter.issues)
    return Document(file=file, data=data, keys=converter.keys, values=converter.values)


def read_document(file: Path) -> Document:
    """Read and parse a YAML file.

    Args:
        file: The file to read.

    Returns:
        The parsed document.

    Raises:
        ConfigError: If the file cannot be read or parsed.
    """
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ConfigError([Issue(file=file, message="file is not valid UTF-8")]) from None
    except OSError as error:
        raise ConfigError(
            [Issue(file=file, message=f"cannot read file: {error.strerror}")]
        ) from None
    return parse_yaml(text, file)


def _strip_union_tags(document: Document, loc: Loc) -> Loc:
    # Pydantic inserts the tag of a discriminated union member into error locations. Drop
    # those, but only where the document has no such key, so a real field is never lost.
    kept: list[str | int] = []
    for part in loc:
        if part in UNION_TAGS and (*kept, part) not in document:
            continue
        kept.append(part)
    return tuple(kept)


def _issue_from_error(document: Document, error: ErrorDetails) -> Issue:
    loc = _strip_union_tags(document, error["loc"])
    # Pydantic's own messages are capitalised; ours are not. Match them up.
    message = _MESSAGES.get(error["type"]) or error["msg"][:1].lower() + error["msg"][1:]
    if error["type"] == "missing":
        # Point at the mapping that lacks the field.
        position = document.position(loc[:-1], of_key=True) if len(loc) > 1 else _START
        return Issue(
            file=document.file,
            line=position.line,
            column=position.column,
            loc=loc,
            message=message,
        )
    return document.issue(loc, message, of_key=error["type"] == "extra_forbidden")


def validate_document[M: ConfigModel](
    document: Document,
    model: type[M],
    fallback: Callable[[object], Sequence[RuleViolation]] | None = None,
) -> M:
    """Validate a parsed document against a configuration model.

    Args:
        document: The parsed document.
        model: The model to validate against.
        fallback: Extra checks run on the raw data when validation fails, for rules pydantic
            skips while other parts of the document are invalid.

    Returns:
        The validated model.

    Raises:
        ConfigError: Listing every validation problem, each with its position.
    """
    try:
        return model.model_validate(document.data)
    except ValidationError as error:
        issues = [_issue_from_error(document, details) for details in error.errors()]
        reported = {(issue.loc, issue.message) for issue in issues}
        issues.extend(
            document.issue(violation.loc, violation.message)
            for violation in (fallback(document.data) if fallback else ())
            if (violation.loc, violation.message) not in reported
        )
        raise ConfigError(issues) from None


def validate_factory_document(document: Document) -> Factory:
    """Validate a parsed factory document, reporting stage-graph problems in every case.

    Args:
        document: The parsed document.

    Returns:
        The validated factory.

    Raises:
        ConfigError: Listing every validation problem, each with its position.
    """
    return validate_document(document, Factory, raw_stage_graph_violations)


def load_agent_file(file: Path) -> Agent:
    """Load and validate an `agent.yaml` file.

    Args:
        file: Path to the file.

    Returns:
        The agent.

    Raises:
        ConfigError: If the file cannot be read, parsed or validated.
    """
    return validate_document(read_document(file), Agent)


def load_factory_file(file: Path) -> Factory:
    """Load and validate a factory file.

    Args:
        file: Path to the file.

    Returns:
        The factory.

    Raises:
        ConfigError: If the file cannot be read, parsed or validated.
    """
    return validate_factory_document(read_document(file))


def dump_yaml(model: BaseModel) -> str:
    """Serialise a model as YAML that loads back into an equal model.

    Fields left at their defaults are omitted, matching how the files are written by hand.
    Keys are written in alphabetical order.

    Args:
        model: The model to serialise.

    Returns:
        The YAML text.
    """
    stream = io.StringIO()
    _safe_yaml_dumper().dump(model.model_dump(mode="json", exclude_defaults=True), stream)
    return stream.getvalue()
