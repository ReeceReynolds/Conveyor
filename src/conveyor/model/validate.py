"""Validate whatever a path points at: an agent folder, a factory file or a whole project."""

from pathlib import Path

from pydantic import Field

from conveyor.model.base import ConfigModel
from conveyor.model.checks import (
    AGENT_FILE,
    AGENTS_DIR,
    FACTORIES_DIR,
    check_agent_folder,
    check_factory_file,
)
from conveyor.model.errors import Issue

YAML_SUFFIXES = frozenset({".yaml", ".yml"})


class NothingToValidateError(Exception):
    """Raised when a path holds no agent or factory to validate."""


class ValidationReport(ConfigModel):
    """The outcome of validating a path."""

    agents: tuple[Path, ...] = Field(description="Agent folders validated.")
    factories: tuple[Path, ...] = Field(description="Factory files validated.")
    issues: tuple[Issue, ...] = Field(description="Every problem found, in file order.")

    @property
    def ok(self) -> bool:
        """Whether no problems were found."""
        return not self.issues


class _Validator:
    """Validates agents and factories, checking each agent folder only once."""

    def __init__(self) -> None:
        self.agents: dict[Path, Path] = {}
        self.factories: list[Path] = []
        self.issues: list[Issue] = []

    def agent(self, folder: Path) -> list[Issue]:
        key = folder.resolve()
        if key in self.agents:
            return []
        self.agents[key] = folder
        return check_agent_folder(folder)

    def add_agent(self, folder: Path) -> None:
        self.issues.extend(self.agent(folder))

    def add_factory(self, file: Path) -> None:
        self.factories.append(file)
        self.issues.extend(check_factory_file(file, self.agent))

    def report(self) -> ValidationReport:
        return ValidationReport(
            agents=tuple(self.agents.values()),
            factories=tuple(self.factories),
            issues=tuple(sorted(self.issues, key=Issue.sort_key)),
        )


def validate_path(path: Path) -> ValidationReport:
    """Validate an agent folder, a factory file, or a project directory.

    A project directory is validated as every folder in `agents/` and every YAML file in
    `factories/`. An `agent.yaml` file is validated as its folder; any other YAML file as a
    factory.

    Args:
        path: What to validate.

    Returns:
        What was validated and every problem found.

    Raises:
        NothingToValidateError: If the path does not exist or holds nothing to validate.
    """
    validator = _Validator()
    if path.is_file():
        if path.name == AGENT_FILE:
            validator.add_agent(path.parent)
        elif path.suffix in YAML_SUFFIXES:
            validator.add_factory(path)
        else:
            msg = f"{path} is not a YAML file"
            raise NothingToValidateError(msg)
    elif (path / AGENT_FILE).is_file():
        validator.add_agent(path)
    elif path.is_dir():
        factories = sorted(
            file
            for file in (path / FACTORIES_DIR).glob("*")
            if file.is_file() and file.suffix in YAML_SUFFIXES
        )
        agents = sorted(folder for folder in (path / AGENTS_DIR).glob("*") if folder.is_dir())
        if not factories and not agents:
            msg = f"{path} has no {AGENT_FILE}, {FACTORIES_DIR}/ or {AGENTS_DIR}/ to validate"
            raise NothingToValidateError(msg)
        for file in factories:
            validator.add_factory(file)
        for folder in agents:
            validator.add_agent(folder)
    else:
        msg = f"{path} does not exist"
        raise NothingToValidateError(msg)
    return validator.report()
