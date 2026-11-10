"""Checks that need the filesystem: agent folders and the agents a factory references.

An agent lives in a folder named after it that mirrors its blocks: `agent.yaml`, the
instructions file named by its Brief, and the eval suite named by its Quality Gate. A factory
finds its agents in `agents/<name>/` under its project root, which is the parent of the
`factories/` folder holding the factory file, or the file's own folder otherwise.

An agent in a project (in `<root>/agents/<name>/`) also has its Brief's contract references
resolved against the project root, which imports the project's contract modules. An agent
folder outside a project has no root to resolve them from, so its references are checked as
names only.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

from conveyor.contracts import ContractResolutionError, ContractSchemas, JsonSchema
from conveyor.model.agent import Agent
from conveyor.model.errors import ConfigError, Issue
from conveyor.model.factory import agent_references, raw_agent_references
from conveyor.model.loader import (
    Document,
    read_document,
    validate_document,
    validate_factory_document,
)
from conveyor.model.types import DOTTED_REF_PATTERN

AGENT_FILE = "agent.yaml"
AGENTS_DIR = "agents"
FACTORIES_DIR = "factories"

type AgentFolderCheck = Callable[[Path], list[Issue]]
"""Checks one agent folder and returns its issues."""


@dataclass(frozen=True)
class AgentInspection:
    """What checking an agent folder found: its problems and, when valid, what it holds.

    Callers that go on to use the agent (publishing snapshots it) take the parsed agent and
    its contract schemas from here, so `agent.yaml` is read and each contract module imported
    once.

    Attributes:
        issues: Every problem found; empty if the agent is valid.
        agent: The validated `agent.yaml`; `None` if it could not be read or validated.
        schemas: The JSON Schema of each contract reference that resolved, keyed by
            reference; empty for a folder outside a project, whose references are not
            resolved.
    """

    issues: tuple[Issue, ...]
    agent: Agent | None = None
    schemas: Mapping[str, JsonSchema] = field(default_factory=dict[str, JsonSchema])


def check_agent_folder(folder: Path, contracts: ContractSchemas | None = None) -> list[Issue]:
    """Validate an agent folder: its `agent.yaml` and the files it points to.

    Args:
        folder: The agent's folder.
        contracts: Contract schemas already resolved in this run. Callers checking many
            agents pass the same one each time, so each contract module is imported once.

    Returns:
        Every problem found; empty if the agent is valid.
    """
    return list(inspect_agent_folder(folder, contracts).issues)


def inspect_agent_folder(folder: Path, contracts: ContractSchemas | None = None) -> AgentInspection:
    """Validate an agent folder and keep what validating it read.

    Args:
        folder: The agent's folder.
        contracts: Contract schemas already resolved in this run; see `check_agent_folder`.

    Returns:
        Every problem found, the parsed agent and the schemas of its resolved contracts.
    """
    contracts = contracts or ContractSchemas()
    file = folder / AGENT_FILE
    if not file.is_file():
        return AgentInspection(
            (Issue(file=folder, message=f"not an agent folder: no {AGENT_FILE}"),)
        )
    try:
        document = read_document(file)
    except ConfigError as error:
        return AgentInspection(error.issues)
    try:
        agent = validate_document(document, Agent)
    except ConfigError as error:
        # Still resolve whichever contract references are well-formed, so every problem is
        # reported in one pass.
        contract_issues, schemas = _resolve_contracts(
            folder, document, _raw_contracts(document.data), contracts
        )
        return AgentInspection((*error.issues, *contract_issues), schemas=schemas)

    issues: list[Issue] = []
    folder_name = folder.resolve().name
    if agent.name != folder_name:
        message = f"must match the folder name {folder_name!r}"
        issues.append(document.issue(("name",), message))
    if not (folder / agent.brief.instructions).is_file():
        message = f"file {str(agent.brief.instructions)!r} not found"
        issues.append(document.issue(("brief", "instructions"), message))
    if not (folder / agent.quality_gate.suite).exists():
        message = f"eval suite {str(agent.quality_gate.suite)!r} not found"
        issues.append(document.issue(("quality_gate", "suite"), message))
    refs = {"input": agent.brief.input, "output": agent.brief.output}
    contract_issues, schemas = _resolve_contracts(folder, document, refs, contracts)
    issues.extend(contract_issues)
    return AgentInspection(tuple(issues), agent, schemas)


def _resolve_contracts(
    folder: Path, document: Document, refs: Mapping[str, str], contracts: ContractSchemas
) -> tuple[list[Issue], dict[str, JsonSchema]]:
    """Resolve contract references, keyed by Brief field, when the agent is in a project.

    The references are resolved together, so a contract module they share is imported once;
    a failure is reported against every field that names the failing reference.
    """
    root = agent_project_root(folder)
    if root is None:
        return [], {}
    issues: list[Issue] = []
    schemas: dict[str, JsonSchema] = {}
    resolved = contracts.resolve(root, refs.values())
    for brief_field, ref in refs.items():
        result = resolved[ref]
        if isinstance(result, ContractResolutionError):
            issues.append(document.issue(("brief", brief_field), str(result)))
        else:
            schemas[ref] = result
    return issues, schemas


class _LooseBrief(BaseModel):
    input: object = None
    output: object = None


class _LooseAgent(BaseModel):
    brief: _LooseBrief


def _raw_contracts(data: object) -> dict[str, str]:
    """The well-formed contract references in an unvalidated agent, by Brief field name."""
    try:
        brief = _LooseAgent.model_validate(data).brief
    except ValidationError:
        return {}
    refs = {"input": brief.input, "output": brief.output}
    return {
        field: ref
        for field, ref in refs.items()
        if isinstance(ref, str) and re.fullmatch(DOTTED_REF_PATTERN, ref)
    }


def agent_project_root(folder: Path) -> Path | None:
    """Find the project an agent folder belongs to, if any.

    Args:
        folder: The agent's folder.

    Returns:
        The project root as an absolute path: the folder's grandparent when its parent is
        named `agents`. `None` for a standalone agent folder.
    """
    parent = folder.resolve().parent
    return parent.parent if parent.name == AGENTS_DIR else None


def project_root(factory_file: Path) -> Path:
    """Find the folder a factory resolves its agents from.

    Args:
        factory_file: Path to the factory file.

    Returns:
        The parent of `factories/` if the file is in one, else the file's folder.
    """
    folder = factory_file.parent
    return folder.parent if folder.resolve().name == FACTORIES_DIR else folder


def check_factory_file(
    file: Path, check_agent: AgentFolderCheck = check_agent_folder
) -> list[Issue]:
    """Validate a factory file and every agent it references.

    Args:
        file: Path to the factory file.
        check_agent: Validates a referenced agent folder. Callers checking many files pass a
            function that skips folders already checked.

    Returns:
        Every problem found; empty if the factory and its agents are valid.
    """
    try:
        document = read_document(file)
    except ConfigError as error:
        return list(error.issues)

    issues: list[Issue] = []
    try:
        references = agent_references(validate_factory_document(document).stages)
    except ConfigError as error:
        # Still check the agents that can be read, so every problem is reported in one pass.
        issues.extend(error.issues)
        references = raw_agent_references(document.data)

    agents_dir = project_root(file) / AGENTS_DIR
    for index, name in references:
        folder = agents_dir / name
        if folder.is_dir():
            issues.extend(check_agent(folder))
        else:
            message = f"agent not found: no folder {folder}"
            issues.append(document.issue(("stages", index, "agent"), message))
    return issues
