"""Contracts: the Pydantic models agents receive and produce, and their JSON Schemas.

An agent's Brief names its input and output contracts with dotted references such as
`contracts.TaskList`, resolved against the project root (the folder holding `agents/` and
`factories/`). Resolving imports the project's contract modules in isolation, so projects never
see each other's modules; see ADR 0011.
"""

from conveyor.contracts.resolver import ContractResolutionError, resolve_contract, resolve_each
from conveyor.contracts.schema import (
    ContractSchemas,
    JsonSchema,
    contract_schema,
    resolve_contract_schemas,
)

__all__ = [
    "ContractResolutionError",
    "ContractSchemas",
    "JsonSchema",
    "contract_schema",
    "resolve_contract",
    "resolve_contract_schemas",
    "resolve_each",
]
