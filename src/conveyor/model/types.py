"""Constrained primitive types shared by the agent and factory models.

Each type validates with a message written for the person editing the YAML, and publishes
the same constraint (a `pattern`, `uniqueItems`) in the JSON Schema for editor feedback.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, LiteralString, TypeIs

from pydantic import AfterValidator, GetCoreSchemaHandler, GetJsonSchemaHandler, Strict
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema

from conveyor.model.base import Loc, RuleViolation, custom_error, raise_violations

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
DOTTED_REF_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
ENV_VAR_PATTERN = r"^[A-Z][A-Z0-9_]*$"
TOOL_NAME_PATTERN = r"^[a-z0-9_]+(?:[.-][a-z0-9_]+)*$"
# Starting with a letter or digit keeps YAML from reading a leading `?`, `-`, `&`, ... as syntax.
NO_SPACE_PATTERN = r"^[A-Za-z0-9]\S*$"
RATING_SCALE_PATTERN = r"^(\d+)-(\d+)$"
PARAMETER_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"


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
    # Also read the path as Windows would, where a backslash separates and `C:` names a drive.
    windows = PureWindowsPath(str(path))
    if path.is_absolute() or windows.drive or windows.root or ".." in windows.parts:
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

ParameterName = Annotated[
    str,
    _Pattern(
        PARAMETER_NAME_PATTERN,
        "parameter_name",
        "must be a parameter name like 'timeout_seconds'",
    ),
]
"""The name of an operation parameter: lowercase letters, digits and underscores."""

type ParameterValue = (
    str | int | float | bool | tuple[ParameterValue, ...] | Mapping[str, ParameterValue] | None
)
"""A JSON-representable YAML value: a scalar, or a sequence (held as a tuple) or mapping of them."""


def _is_sequence(value: object) -> TypeIs[list[object] | tuple[object, ...]]:
    return isinstance(value, list | tuple)


def _is_mapping(value: object) -> TypeIs[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _describe(value: object) -> str:
    """Quote a scalar as YAML spells it; name the type of anything bigger, which may be long."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float) and not math.isfinite(value):
        return ".nan" if math.isnan(value) else ("-.inf" if value < 0 else ".inf")
    if isinstance(value, str | int | float):
        return repr(value)
    return f"a {type(value).__name__}"


def _parameter_value(value: object, loc: Loc, violations: list[RuleViolation]) -> ParameterValue:
    if value is None or isinstance(value, str | int):  # bool is an int
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            message = f"must be a finite number, got {_describe(value)}"
            violations.append(RuleViolation(loc, "finite_number", message, value))
        return value
    if _is_sequence(value):
        return tuple(_parameter_value(item, (*loc, i), violations) for i, item in enumerate(value))
    if _is_mapping(value):
        result: dict[str, ParameterValue] = {}
        for key, item in value.items():
            if isinstance(key, str):
                result[key] = _parameter_value(item, (*loc, key), violations)
            else:
                message = f"mapping keys must be strings, got {_describe(key)}"
                violations.append(RuleViolation(loc, "parameter_key", message, key))
        return result
    message = (
        f"must be a string, number, boolean, null, list or mapping, got {type(value).__name__!r}"
    )
    violations.append(RuleViolation(loc, "parameter_value", message, value))
    return None


def _check_parameters(value: object) -> Mapping[str, ParameterValue]:
    if not _is_mapping(value):
        raise custom_error("parameters", f"must be a mapping of parameters, got {_describe(value)}")
    violations: list[RuleViolation] = []
    result: dict[str, ParameterValue] = {}
    for key, item in value.items():
        if isinstance(key, str) and re.fullmatch(PARAMETER_NAME_PATTERN, key):
            result[key] = _parameter_value(item, (key,), violations)
        else:
            # Only a string key goes in the location: an int would read as a list index.
            loc: Loc = (key,) if isinstance(key, str) else ()
            message = f"must be a parameter name like 'timeout_seconds', got {_describe(key)}"
            violations.append(RuleViolation(loc, "parameter_name", message, key))
    if violations:
        raise_violations("parameters", violations)
    return result


def _same_parameters(value: Mapping[str, ParameterValue]) -> Mapping[str, ParameterValue]:
    return value


class _Parameters:
    """Annotated marker: operation parameters, checked in one pass.

    A plain union would report one error per member it tried; this reports one clear message
    per problem, and publishes the union's JSON Schema unchanged.
    """

    def __get_pydantic_core_schema__(
        self, source: type[object], handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        schema = handler(source)
        return core_schema.no_info_plain_validator_function(
            _check_parameters,
            json_schema_input_schema=schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                _same_parameters, return_schema=schema
            ),
        )

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema["additionalProperties"] = False
        return json_schema


Parameters = Annotated[Mapping[ParameterName, ParameterValue], _Parameters()]
"""Named operation parameters, as given; lists become tuples. Each operation validates its own."""
