#!/usr/bin/env python3
"""Claude Code PostToolUse hook: format and lint each file right after it is edited.

Python files get `ruff format` then `ruff check --fix`; files under `ui/` that Biome handles get
`biome check --write`. If problems remain, the hook prints a `{"decision": "block"}` response
with the tool output so the agent fixes them at once. A missing tool, a path outside the project
and any unexpected error exit 0 silently, so a broken hook never blocks the session. Standard
library only.
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
UI_DIR = PROJECT_DIR / "ui"
BIOME_SUFFIXES = frozenset(
    {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".json",
        ".jsonc",
        ".css",
        ".graphql",
        ".gql",
    }
)
"""File types Biome formats and lints."""

TIMEOUT_SECONDS = 25
"""Per command; two commands stay inside Claude Code's 60-second hook budget."""

MAX_REASON_CHARS = 4000
"""Longest tool output passed back to the agent."""


def edited_file(payload: object) -> Path | None:
    """Extract the edited file from the hook payload, if it is inside the project.

    Args:
        payload: The decoded hook input.

    Returns:
        The absolute path of an existing file in the project, or `None`.
    """
    match payload:
        case {"tool_input": {"file_path": str(path)}}:
            candidate = Path(path)
        case _:
            return None
    absolute = (candidate if candidate.is_absolute() else PROJECT_DIR / candidate).resolve()
    if not absolute.is_file() or not absolute.is_relative_to(PROJECT_DIR):
        return None
    return absolute


def commands_for(file: Path) -> list[list[str]]:
    """Choose the formatter and linter commands for a file.

    Args:
        file: An absolute path inside the project.

    Returns:
        Commands to run in order; the last one decides whether problems remain.
    """
    if file.suffix == ".py":
        return [
            ["uv", "run", "--frozen", "ruff", "format", str(file)],
            ["uv", "run", "--frozen", "ruff", "check", "--fix", str(file)],
        ]
    if file.suffix in BIOME_SUFFIXES and file.is_relative_to(UI_DIR):
        relative = file.relative_to(UI_DIR).as_posix()
        return [["pnpm", "-C", "ui", "exec", "biome", "check", "--write", relative]]
    return []


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one command from the project root, capturing its output.

    Args:
        command: The program and its arguments.

    Returns:
        The finished process.
    """
    return subprocess.run(  # noqa: S603 -- fixed argv built above; the only input is a path
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def main() -> int:
    """Run the hook.

    Returns:
        Always 0; remaining problems are reported through stdout as a block decision.
    """
    try:
        file = edited_file(json.loads(sys.stdin.read() or "null"))
        if file is None:
            return 0
        for command in commands_for(file):
            result = run(command)
            if result.returncode != 0:
                output = (result.stdout + result.stderr).strip()[-MAX_REASON_CHARS:]
                reason = f"`{' '.join(command)}` reported problems; fix them now:\n{output}"
                print(json.dumps({"decision": "block", "reason": reason}))
                return 0
    except (ValueError, OSError, subprocess.SubprocessError):
        # Not JSON, a missing tool (FileNotFoundError) or a timeout: never block the session.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
