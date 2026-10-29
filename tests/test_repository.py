"""The repository's own structure: docs, agent guidance, skills, hooks and architecture.

These checks keep the harness that guides coding agents consistent with the code. Every
failure message says how to fix the problem.
"""

import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ADR_DIR = ROOT / "docs" / "adr"
SKILLS_DIR = ROOT / ".claude" / "skills"
HOOKS_DIR = ROOT / ".claude" / "hooks"
SKIPPED_DIRS = frozenset({".git", ".venv", "node_modules", "_ui", ".pytest_cache", "dist"})
ROOT_AGENTS_MAX_LINES = 150
NESTED_AGENTS_MAX_LINES = 80

_FENCED_CODE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_LINK_TARGET = re.compile(r"\]\(([^)\s]+)")
_ADR_FILE = re.compile(r"^(\d{4})-.+\.md$")
_MAKE_TARGET = re.compile(r"^([a-zA-Z][\w-]*):", re.MULTILINE)
_MAKE_COMMAND = re.compile(r"(?:^|\s)make ([a-z][\w-]*)")


def _files(name: str) -> Iterator[Path]:
    """Yield every file called `name` in the repository, skipping tool and build folders."""
    for path in sorted(ROOT.rglob(name)):
        if not SKIPPED_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _agents_files() -> list[Path]:
    return list(_files("AGENTS.md"))


def _code(text: str) -> list[str]:
    """Return the contents of fenced code blocks and inline code spans."""
    return [*_FENCED_CODE.findall(text), *(span.strip("`") for span in _INLINE_CODE.findall(text))]


def _prose(text: str) -> str:
    """Return `text` with code removed, so example links inside code are not checked."""
    return _INLINE_CODE.sub("", _FENCED_CODE.sub("", text))


def _linked_docs() -> list[Path]:
    docs = [*_agents_files(), ROOT / "README.md", ROOT / "CONTRIBUTING.md"]
    docs += sorted((ROOT / "docs").rglob("*.md"))
    docs += sorted(SKILLS_DIR.rglob("*.md"))
    # The ADR template's links are placeholders by design.
    return [doc for doc in docs if doc != ADR_DIR / "0000-template.md"]


def _layer_modules() -> set[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    layers = next(contract["layers"] for contract in contracts if contract["type"] == "layers")
    return {
        module.strip().strip("()").strip()
        for layer in layers
        for module in re.split(r"[|:]", layer)
    }


def _frontmatter(text: str) -> dict[str, str]:
    """Parse a `---`-delimited block of `key: value` lines at the start of `text`."""
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        return {}
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def test_every_adr_is_indexed_and_numbered_once() -> None:
    files = [path.name for path in sorted(ADR_DIR.glob("*.md")) if _ADR_FILE.match(path.name)]
    index = (ADR_DIR / "README.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"\]\((\d{4}-[^)]+\.md)\)", index))
    numbers = Counter(name[:4] for name in files)

    duplicates = sorted(number for number, count in numbers.items() if count > 1)
    assert not duplicates, (
        f"ADR numbers used more than once: {duplicates}. Renumber the newer ADR to the next free "
        "number (see .claude/skills/add-adr/SKILL.md)."
    )
    unlisted = sorted(set(files) - listed - {"0000-template.md"})
    assert not unlisted, (
        f"ADRs missing from docs/adr/README.md: {unlisted}. Add a row to the index table."
    )
    missing = sorted(listed - set(files))
    assert not missing, (
        f"docs/adr/README.md lists ADRs that do not exist: {missing}. Fix the link or add the file."
    )


@pytest.mark.parametrize("doc", _linked_docs(), ids=_relative)
def test_relative_links_resolve(doc: Path) -> None:
    targets = _LINK_TARGET.findall(_prose(doc.read_text(encoding="utf-8")))
    broken = [
        target
        for target in targets
        if not re.match(r"^[a-z]+:", target)
        and not target.startswith("#")
        and not (doc.parent / target.split("#", 1)[0]).exists()
    ]

    assert not broken, (
        f"{_relative(doc)} links to paths that do not exist: {broken}. Links are relative to "
        "the file; fix the path or remove the link."
    )


@pytest.mark.parametrize("agents", _agents_files(), ids=_relative)
def test_agents_md_is_short(agents: Path) -> None:
    limit = ROOT_AGENTS_MAX_LINES if agents.parent == ROOT else NESTED_AGENTS_MAX_LINES
    lines = len(agents.read_text(encoding="utf-8").splitlines())

    assert lines <= limit, (
        f"{_relative(agents)} has {lines} lines (limit {limit}). AGENTS.md is a map: move "
        "procedures into a skill under .claude/skills/ and local rules into a nested AGENTS.md."
    )


@pytest.mark.parametrize("agents", _agents_files(), ids=_relative)
def test_agents_md_has_claude_md_pointer(agents: Path) -> None:
    claude = agents.parent / "CLAUDE.md"
    content = claude.read_text(encoding="utf-8") if claude.is_file() else None

    assert content == "@AGENTS.md\n", (
        f"{_relative(claude)} must contain exactly '@AGENTS.md' (and a newline) so Claude Code "
        "loads the AGENTS.md beside it. Create or rewrite it with that single line."
    )


def test_make_targets_in_agents_md_exist() -> None:
    targets = set(_MAKE_TARGET.findall((ROOT / "Makefile").read_text(encoding="utf-8")))
    mentioned = {
        (_relative(agents), name)
        for agents in _agents_files()
        for code in _code(agents.read_text(encoding="utf-8"))
        for name in _MAKE_COMMAND.findall(code)
    }
    unknown = sorted((file, name) for file, name in mentioned if name not in targets)

    assert not unknown, (
        f"AGENTS.md files mention make targets the Makefile does not define: {unknown}. Fix "
        "the command, or add the target (with a `## description`) to the Makefile."
    )


def test_every_package_is_in_the_layers_contract() -> None:
    packages = sorted(
        f"conveyor.{init.parent.name}" for init in (ROOT / "src" / "conveyor").glob("*/__init__.py")
    )
    missing = [package for package in packages if package not in _layer_modules()]

    assert packages, "no packages found under src/conveyor/"
    assert not missing, (
        f"{missing} are not in the import-linter layers contract. Add each to the `layers` "
        "list in pyproject.toml at the right level (see .claude/skills/add-package/SKILL.md)."
    )


@pytest.mark.parametrize(
    "skill", sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir()), ids=_relative
)
def test_skill_has_frontmatter(skill: Path) -> None:
    file = skill / "SKILL.md"
    fields = _frontmatter(file.read_text(encoding="utf-8")) if file.is_file() else {}

    assert fields.get("name") == skill.name, (
        f"{_relative(file)} needs YAML frontmatter between '---' lines with "
        f"'name: {skill.name}' (matching its folder)."
    )
    assert fields.get("description"), (
        f"{_relative(file)} needs a 'description:' in its frontmatter saying what it does and "
        "'Use when ...'."
    )


def _run_hook(name: str, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- runs our own hook script with the test interpreter
        [sys.executable, str(HOOKS_DIR / name)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _edit(path: str) -> str:
    return json.dumps({"tool_name": "Edit", "tool_input": {"file_path": path}})


@pytest.mark.parametrize(
    ("path", "remedy"),
    [
        ("uv.lock", "uv add"),
        (str(ROOT / "uv.lock"), "uv add"),
        ("ui/pnpm-lock.yaml", "pnpm -C ui add"),
        ("schemas/agent.schema.json", "make schemas"),
        ("CHANGELOG.md", "release-please"),
        (".release-please-manifest.json", "release-please"),
        ("src/conveyor/_ui/assets/index.js", "build output"),
        (".env", "environment"),
        (".env.local", "environment"),
    ],
)
def test_protect_files_hook_blocks_generated_and_secret_files(path: str, remedy: str) -> None:
    result = _run_hook("protect_files.py", _edit(path))

    assert result.returncode == 2, result.stderr
    assert remedy in result.stderr


@pytest.mark.parametrize(
    "stdin",
    [
        _edit("src/conveyor/cli.py"),
        _edit(str(ROOT / "docs" / "adr" / "README.md")),
        _edit(".env.example"),
        _edit("/somewhere/else/uv.lock"),
        json.dumps({"tool_input": {}}),
        "not json",
        "",
    ],
)
def test_protect_files_hook_allows_everything_else(stdin: str) -> None:
    result = _run_hook("protect_files.py", stdin)

    assert result.returncode == 0, result.stderr
    assert not result.stderr
