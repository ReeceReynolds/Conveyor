"""Configuration problems, located precisely enough to fix without searching."""

from collections.abc import Iterable
from pathlib import Path

from pydantic import Field

from conveyor.model.base import ConfigModel, Loc


def format_loc(loc: Loc) -> str:
    """Render a location the way it reads in YAML, e.g. `stages[4].on_reject.return_to`.

    Args:
        loc: Mapping keys and sequence indexes, outermost first.

    Returns:
        The dotted path, or an empty string for the document root.
    """
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            parts.append(f".{part}" if parts else part)
    return "".join(parts)


class Issue(ConfigModel):
    """One problem in a configuration file or folder."""

    file: Path = Field(description="The file or folder the problem is in.")
    line: int | None = Field(default=None, ge=1, description="1-based line, when known.")
    column: int | None = Field(default=None, ge=1, description="1-based column, when known.")
    loc: Loc = Field(default=(), description="Field path within the file.")
    message: str = Field(description="What is wrong.")

    def render(self) -> str:
        """Format as `file:line:column: field.path: message`, omitting unknown parts.

        Returns:
            A single line suitable for terminals and editors.
        """
        where = str(self.file)
        if self.line is not None:
            where += f":{self.line}"
            if self.column is not None:
                where += f":{self.column}"
        path = format_loc(self.loc)
        return f"{where}: {path}: {self.message}" if path else f"{where}: {self.message}"

    def sort_key(self) -> tuple[str, int, int, str, str]:
        """Order issues by file, then position, then path.

        Returns:
            A key for `sorted`.
        """
        return (
            str(self.file),
            self.line or 0,
            self.column or 0,
            format_loc(self.loc),
            self.message,
        )


class ConfigError(Exception):
    """Raised when a configuration file cannot be loaded. Carries every problem found."""

    def __init__(self, issues: Iterable[Issue]) -> None:
        """Create the error.

        Args:
            issues: The problems found; at least one.
        """
        self.issues: tuple[Issue, ...] = tuple(sorted(issues, key=Issue.sort_key))
        super().__init__("\n".join(issue.render() for issue in self.issues))
