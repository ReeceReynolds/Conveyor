#!/usr/bin/env python3
"""Claude Code PreToolUse hook: refuse edits to generated, tool-owned and secret files.

Reads the hook payload (JSON) from stdin. If the tool would write a protected path, exits with
code 2 and explains on stderr how to make the change properly; Claude Code shows that message
to the agent and cancels the edit. Any other path, and any unexpected error, exits 0 so a
broken hook never blocks the session. Standard library only.
"""

import json
import sys
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

PROJECT_DIR = Path(__file__).resolve().parents[2]

_LOCK = "uv.lock is generated: change dependencies with `uv add` / `uv remove`."
_PNPM_LOCK = (
    "ui/pnpm-lock.yaml is generated: change dependencies with `pnpm -C ui add` / "
    "`pnpm -C ui remove`."
)
_SCHEMAS = (
    "schemas/ is generated: change the models in src/conveyor/model/, then run `make schemas`."
)
_RELEASE = "release-please owns this file; it is written from PR titles, never by hand."
_UI_BUILD = "src/conveyor/_ui/ is UI build output: edit ui/src/ and run `make ui-check`."
_ENV = "Never edit .env files: credentials come from the environment, not the repository."

# fnmatch's `*` also matches `/`, so `*/name` covers a file of that name in any subfolder.
RULES: tuple[tuple[str, str], ...] = (
    ("uv.lock", _LOCK),
    ("*/uv.lock", _LOCK),
    ("ui/pnpm-lock.yaml", _PNPM_LOCK),
    ("schemas/*.json", _SCHEMAS),
    ("CHANGELOG.md", _RELEASE),
    (".release-please-manifest.json", _RELEASE),
    ("src/conveyor/_ui/*", _UI_BUILD),
    (".env", _ENV),
    (".env.*", _ENV),
    ("*/.env", _ENV),
    ("*/.env.*", _ENV),
)
"""Protected path patterns, relative to the project root, and the remediation for each."""

ALLOWED = frozenset({".env.example"})
"""File names that match a rule above but are meant to be committed and edited."""


def target_path(payload: object) -> str | None:
    """Extract the path the tool is about to write.

    Args:
        payload: The decoded hook input.

    Returns:
        The file path, or `None` if the payload names none.
    """
    match payload:
        case {"tool_input": {"file_path": str(path)}}:
            return path
        case {"tool_input": {"notebook_path": str(path)}}:
            return path
        case _:
            return None


def relative_to_project(path: str) -> PurePosixPath | None:
    """Express `path` relative to the project root.

    Args:
        path: An absolute path, or one relative to the project root.

    Returns:
        The relative POSIX path, or `None` if the path is outside the project.
    """
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else PROJECT_DIR / candidate
    try:
        return PurePosixPath(absolute.resolve().relative_to(PROJECT_DIR).as_posix())
    except ValueError:
        return None


def violation(path: PurePosixPath) -> str | None:
    """Find the rule a path breaks.

    Args:
        path: A path relative to the project root.

    Returns:
        The remediation message, or `None` if the path may be edited.
    """
    if path.name in ALLOWED:
        return None
    text = path.as_posix()
    for pattern, message in RULES:
        if fnmatchcase(text, pattern):
            return message
    return None


def main() -> int:
    """Run the hook.

    Returns:
        2 to block the edit, 0 to allow it.
    """
    try:
        path = target_path(json.loads(sys.stdin.read() or "null"))
        relative = relative_to_project(path) if path else None
        message = violation(relative) if relative else None
    except (ValueError, OSError):
        return 0
    if message is None:
        return 0
    print(f"Blocked edit to {relative}: {message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
