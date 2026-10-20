"""Constrained primitive types shared by the agent and factory models.

Each type validates with a message written for the person editing the YAML, and publishes
the same constraint (a `pattern`, `uniqueItems`) in the JSON Schema for editor feedback.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, LiteralString

from pydantic import AfterValidator, GetCoreSchemaHandler, GetJsonSchemaHandler, Strict
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema

from conveyor.model.base import RuleViolation, custom_error, raise_violations

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
DOTTED_REF_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
ENV_VAR_PATTERN = r"^[A-Z][A-Z0-9_]*$"
TOOL_NAME_PATTERN = r"^[a-z0-9_]+(?:[.-][a-z0-9_]+)*$"
# Starting with a letter or digit keeps YAML from reading a leading `?`, `-`, `&`, ... as syntax.
NO_SPACE_PATTERN = r"^[A-Za-z0-9]\S*$"
RATING_SCALE_PATTERN = r"^(\d+)-(\d+)$"


@dataclass(frozen=True)
class _Pattern:
    """Annotated marker: the string must fully match `regex`, else `message` is reported."""

    regex: str
    error_type: LiteralString
    message: str

    def __get_pydantic_core_schema__(
        self, source: type[str], handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(self._check, handler(source))

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema["pattern"] = self.regex
        return json_schema

    def _check(self, value: str) -> str:
        if re.fullmatch(self.regex, value) is None:
            raise custom_error(self.error_type, f"{self.message}, got {value!r}")
        return value


class _UniqueItems:
    """Annotated marker: a tuple whose items must all be distinct."""

    def __get_pydantic_core_schema__(
        self, source: type[tuple[object, ...]], handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(_check_unique, handler(source))

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema["uniqueItems"] = True
        return json_schema


class _NonEmpty:
    """Annotated marker: a tuple with at least one item.

    Unlike `Field(min_length=1)`, this is checked only once every item is valid, so a list
    whose items all fail is not also reported as empty.
    """

    def __get_pydantic_core_schema__(
        self, source: type[tuple[object, ...]], handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(_check_non_empty, handler(source))

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema["minItems"] = 1
        return json_schema


def _check_non_empty[T](items: tuple[T, ...]) -> tuple[T, ...]:
    if not items:
        raise custom_error("empty", "must list at least one item")
    return items


def _check_unique[T](items: tuple[T, ...]) -> tuple[T, ...]:
    violations: list[RuleViolation] = []
    for index, item in enumerate(items):
        first = items.index(item)
        if first != index:
            shown = f"{item!r} " if isinstance(item, str) else ""
            message = f"duplicate entry {shown}(same as item {first})"
            violations.append(RuleViolation((index,), "duplicate", message, item))
    if violations:
        raise_violations("unique items", violations)
    return items


def _check_relative_path(path: PurePosixPath) -> PurePosixPath:
    if path.is_absolute() or ".." in path.parts:
        raise custom_error(
            "relative_path",
            f"must be a relative path inside the folder, got {str(path)!r}",
        )
    return path


_RATING_SCALE_MESSAGE = "must be a rating scale like '1-5', lowest first"


def _check_rating_scale(value: str) -> str:
    match = re.fullmatch(RATING_SCALE_PATTERN, value)
    if match is None or int(match[1]) >= int(match[2]):
        raise custom_error("rating_scale", f"{_RATING_SCALE_MESSAGE}, got {value!r}")
    return value


UNIQUE = _UniqueItems()
"""Annotate a `tuple[...]` field with this to reject duplicate items."""

NON_EMPTY = _NonEmpty()
"""Annotate a `tuple[...]` field with this to require at least one item."""

Slug = Annotated[
    str,
    _Pattern(
        SLUG_PATTERN,
        "slug",
        "must be a lowercase slug like 'task-planner'",
    ),
]
"""A lowercase, hyphen-separated name used for agents, factories, stages and operations."""

DottedRef = Annotated[
    str,
    _Pattern(
        DOTTED_REF_PATTERN,
        "dotted_ref",
        "must be a dotted reference like 'contracts.TaskList'",
    ),
]
"""A reference to a Python object, such as a contract or scorer. Not resolved here."""

SecretName = Annotated[
    str,
    _Pattern(
        ENV_VAR_PATTERN,
        "secret_name",
        "must be an environment variable name like 'GITHUB_TOKEN'",
    ),
]
"""The name (never the value) of a secret an agent may read from its environment."""

ToolName = Annotated[
    str,
    _Pattern(
        TOOL_NAME_PATTERN, "tool_name", "must be a tool name like 'github.create_pull_request'"
    ),
]
"""The name of a tool an agent may call."""

Token = Annotated[
    str,
    _Pattern(NO_SPACE_PATTERN, "token", "must start with a letter or digit and contain no spaces"),
]
"""A name without whitespace that starts with a letter or digit, such as a model id."""

RelativePath = Annotated[PurePosixPath, AfterValidator(_check_relative_path)]
"""A POSIX-style path relative to, and contained in, the folder of the file declaring it."""

RatingScale = Annotated[
    str,
    # The pattern publishes the shape to JSON Schema; the validator also checks the bounds.
    _Pattern(RATING_SCALE_PATTERN, "rating_scale", _RATING_SCALE_MESSAGE),
    AfterValidator(_check_rating_scale),
]
"""An inclusive integer rating scale written as 'low-high', such as '1-5'."""

StrictBool = Annotated[bool, Strict()]
"""A boolean that must be written as `true` or `false`, never coerced from strings."""

StrictInt = Annotated[int, Strict()]
"""An integer that is never coerced from strings or floats."""

StrictFloat = Annotated[float, Strict()]
"""A number that is never coerced from strings."""
