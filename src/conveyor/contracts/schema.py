"""Export contract models as JSON Schema, and resolve a set of references to their schemas.

The registry stores each agent version's input and output schemas and diffs them, so the same
model must always produce the same schema. Pydantic's output is already deterministic for a
given model; key order follows field order, which is kept because it is meaningful to people
reading the schema and to models generating structured output from it.
"""

import copy
import math
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, JsonValue, TypeAdapter

from conveyor.contracts.resolver import ContractResolutionError, describe, resolve_each

type JsonSchema = dict[str, JsonValue]
"""A JSON Schema document as plain JSON data."""

DIALECT = "https://json-schema.org/draft/2020-12/schema"
"""The JSON Schema dialect Pydantic generates; every contract schema declares it."""

MAX_EXACT_INTEGER = 2**53 - 1
"""Largest integer JSON carries exactly between implementations (RFC 8785, I-JSON)."""

_JSON_SCHEMA = TypeAdapter[JsonSchema](JsonSchema)


def contract_schema(model: type[BaseModel]) -> JsonSchema:
    """Generate a contract's JSON Schema 2020-12, describing the data the contract accepts.

    Args:
        model: The contract model. Nested models appear under `$defs`.

    Returns:
        A fresh copy of the schema, with `$schema` first. Equal on every call for the same
        model.

    Raises:
        ContractResolutionError: If Pydantic cannot express the model as JSON Schema, for
            example because a field holds a callable.
    """
    try:
        schema = model.model_json_schema(mode="validation")
    except Exception as error:
        ref = f"{model.__module__}.{model.__qualname__}"
        reason = f"no JSON Schema can be generated for it: {describe(error)}"
        raise ContractResolutionError(ref, reason) from error
    # Validating as JSON data both types the result and copies it, so callers can't mutate
    # what Pydantic caches on the model.
    result = _JSON_SCHEMA.validate_python({"$schema": DIALECT, **schema})
    # The registry hashes schemas in canonical JSON, which cannot hold these values; report
    # them here so `conveyor validate` catches what publishing would otherwise refuse.
    problem = inexact_value(result)
    if problem is not None:
        ref = f"{model.__module__}.{model.__qualname__}"
        reason = f"its JSON Schema has a value JSON cannot carry exactly: {problem}"
        raise ContractResolutionError(ref, reason)
    return result


def inexact_value(value: JsonValue) -> str | None:
    """Find the first value that has no exact, portable JSON form.

    JSON parsers commonly read numbers as IEEE doubles, so integers beyond +/-(2**53 - 1)
    lose precision, NaN and the infinities are not JSON at all, and a lone surrogate is not
    valid Unicode. RFC 8785, which the registry uses for content IDs, rejects all of them.

    Args:
        value: Plain JSON data.

    Returns:
        A one-line description naming the first offending value and its JSON Pointer, or
        `None` when every value is exact.
    """
    return next(_inexact_values(value, ""), None)


def _inexact_values(value: JsonValue, pointer: str) -> Iterator[str]:
    where = f" at {pointer}" if pointer else ""
    match value:
        case bool() | None:
            pass
        case int() if abs(value) > MAX_EXACT_INTEGER:
            yield f"integer {value} exceeds 2**53 - 1{where}"
        case float() if not math.isfinite(value):
            yield f"{value} is not a JSON number{where}"
        case str() if not _encodes(value):
            yield f"string has a lone surrogate{where}"
        case list():
            for index, item in enumerate(value):
                yield from _inexact_values(item, f"{pointer}/{index}")
        case dict():
            for key, item in value.items():
                yield from _inexact_values(key, pointer)
                escaped = key.replace("~", "~0").replace("/", "~1")
                yield from _inexact_values(item, f"{pointer}/{escaped}")
        case _:
            pass


def _encodes(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def resolve_contract_schemas(project_root: Path, refs: Iterable[str]) -> dict[str, JsonSchema]:
    """Resolve contract references and generate each one's JSON Schema.

    Args:
        project_root: The folder holding the contract modules.
        refs: Contract references. A reference given more than once is resolved once, and
            each contract module is imported once for all of them.

    Returns:
        Each distinct reference mapped to its schema, in first-seen order.

    Raises:
        ContractResolutionError: For the first reference that does not resolve or has no
            JSON Schema.
    """
    schemas: dict[str, JsonSchema] = {}
    for ref, result in _schemas_or_errors(project_root, refs).items():
        if isinstance(result, ContractResolutionError):
            raise result
        schemas[ref] = result
    return schemas


def _schemas_or_errors(
    project_root: Path, refs: Iterable[str]
) -> dict[str, JsonSchema | ContractResolutionError]:
    # The schema is generated while the project's modules are still importable.
    results = resolve_each(project_root, refs, contract_schema)
    return {ref: _as_written(ref, result) for ref, result in results.items()}


def _as_written(
    ref: str, result: JsonSchema | ContractResolutionError
) -> JsonSchema | ContractResolutionError:
    """Report a schema failure against the reference as written, not where the model lives."""
    if not isinstance(result, ContractResolutionError) or result.ref == ref:
        return result
    error = ContractResolutionError(ref, result.reason)
    error.__cause__ = result.__cause__
    return error


class ContractSchemas:
    """Contract schemas resolved during one run, such as one `conveyor validate`.

    Every agent of a project usually names models from the same few contract modules.
    Resolving through one of these imports each module once for all the references first
    asked for together, and answers a reference seen before without importing anything.

    Results are kept for as long as the object lives, so make a new one for each run: an
    edit to a contract module is not seen by an object that has already resolved it.
    """

    def __init__(self) -> None:
        """Create an empty set of resolved schemas."""
        self._resolved: dict[tuple[Path, str], JsonSchema | ContractResolutionError] = {}

    def resolve(
        self, project_root: Path, refs: Iterable[str]
    ) -> dict[str, JsonSchema | ContractResolutionError]:
        """Resolve contract references, reusing what this object has resolved before.

        Args:
            project_root: The folder holding the contract modules.
            refs: Contract references.

        Returns:
            Each distinct reference, in first-seen order, mapped to a fresh copy of its
            schema, or to the error that stopped it resolving.
        """
        root = project_root.resolve()
        order = list(dict.fromkeys(refs))
        missing = [ref for ref in order if (root, ref) not in self._resolved]
        for ref, result in _schemas_or_errors(root, missing).items():
            self._resolved[root, ref] = result
        results: dict[str, JsonSchema | ContractResolutionError] = {}
        for ref in order:
            result = self._resolved[root, ref]
            # Callers own what they get: a schema they change must not change the next one.
            is_error = isinstance(result, ContractResolutionError)
            results[ref] = result if is_error else copy.deepcopy(result)
        return results
