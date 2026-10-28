"""Export contract models as JSON Schema, and resolve a set of references to their schemas.

The registry stores each agent version's input and output schemas and diffs them, so the same
model must always produce the same schema. Pydantic's output is already deterministic for a
given model; key order follows field order, which is kept because it is meaningful to people
reading the schema and to models generating structured output from it.
"""

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, JsonValue, TypeAdapter

from conveyor.contracts.resolver import ContractResolutionError, describe, resolve_contract

type JsonSchema = dict[str, JsonValue]
"""A JSON Schema document as plain JSON data."""

DIALECT = "https://json-schema.org/draft/2020-12/schema"
"""The JSON Schema dialect Pydantic generates; every contract schema declares it."""

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
    return _JSON_SCHEMA.validate_python({"$schema": DIALECT, **schema})


def resolve_contract_schemas(project_root: Path, refs: Iterable[str]) -> dict[str, JsonSchema]:
    """Resolve contract references and generate each one's JSON Schema.

    Args:
        project_root: The folder holding the contract modules.
        refs: Contract references. A reference given more than once is resolved once.

    Returns:
        Each distinct reference mapped to its schema, in first-seen order.

    Raises:
        ContractResolutionError: For the first reference that does not resolve or has no
            JSON Schema.
    """
    schemas: dict[str, JsonSchema] = {}
    for ref in refs:
        if ref not in schemas:
            schemas[ref] = _schema_for(project_root, ref)
    return schemas


def _schema_for(project_root: Path, ref: str) -> JsonSchema:
    model = resolve_contract(project_root, ref)
    # Report a schema failure against the reference as written, not where the model lives.
    try:
        return contract_schema(model)
    except ContractResolutionError as error:
        raise ContractResolutionError(ref, error.reason) from error.__cause__
