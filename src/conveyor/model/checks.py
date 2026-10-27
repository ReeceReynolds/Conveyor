"""Checks that need the filesystem: agent folders and the agents a factory references.

An agent lives in a folder named after it that mirrors its blocks: `agent.yaml`, the
instructions file named by its Brief, and the eval suite named by its Quality Gate. A factory
finds its agents in `agents/<name>/` under its project root, which is the parent of the
`factories/` folder holding the factory file, or the file's own folder otherwise.
"""

from collections.abc import Callable
from pathlib import Path

from conveyor.model.agent import Agent
from conveyor.model.errors import ConfigError, Issue
from conveyor.model.factory import agent_references, raw_agent_references
from conveyor.model.loader import read_document, validate_document, validate_factory_document

AGENT_FILE = "agent.yaml"
AGENTS_DIR = "agents"
FACTORIES_DIR = "factories"

type AgentFolderCheck = Callable[[Path], list[Issue]]
"""Checks one agent folder and returns its issues."""


def check_agent_folder(folder: Path) -> list[Issue]:
    """Validate an agent folder: its `agent.yaml` and the files it points to.

    Args:
        folder: The agent's folder.

    Returns:
        Every problem found; empty if the agent is valid.
    """
    file = folder / AGENT_FILE
    if not file.is_file():
        return [Issue(file=folder, message=f"not an agent folder: no {AGENT_FILE}")]
    try:
        document = read_document(file)
        agent = validate_document(document, Agent)
    except ConfigError as error:
        return list(error.issues)

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
    return issues


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
