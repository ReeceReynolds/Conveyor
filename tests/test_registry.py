"""Agent snapshots and diffs: building from folders, identity, and how changes are described."""

import shutil
from pathlib import Path
from typing import Any, get_args

import pytest
from inline_snapshot import snapshot
from pydantic import BaseModel, JsonValue, ValidationError

from conveyor.contracts import resolve_contract_schemas
from conveyor.model import Agent, load_agent_file
from conveyor.registry import (
    AgentDiff,
    AgentSnapshot,
    Block,
    Component,
    EvalFile,
    JsonSchema,
    Primitive,
    SnapshotError,
    build_snapshot,
    canonical_bytes,
    content_id,
    diff_snapshots,
    render,
    short_id,
    snapshot_from_bytes,
    summarise,
)
from conveyor.registry.canonical import CanonicalFormError, canonical_json, load_canonical_json
from conveyor.registry.diff import json_changes, text_diff

REGISTRY = Path(__file__).parent / "fixtures" / "registry"

TASK_LIST: JsonSchema = {
    "$defs": {
        "Task": {
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "acceptance_criteria": {"items": {"type": "string"}, "type": "array"},
            },
            "required": ["id", "title", "acceptance_criteria"],
            "type": "object",
        }
    },
    "properties": {"tasks": {"items": {"$ref": "#/$defs/Task"}, "type": "array"}},
    "required": ["tasks"],
    "title": "TaskList",
    "type": "object",
}
CODE_CHANGES_V1: JsonSchema = {
    "properties": {
        "branch": {"type": "string"},
        "commits": {"type": "integer"},
        "files": {"items": {"type": "string"}, "type": "array"},
    },
    "required": ["branch", "files"],
    "title": "CodeChanges",
    "type": "object",
}
CODE_CHANGES_V2: JsonSchema = {
    "properties": {
        "branch": {"type": "string"},
        "commits": {"items": {"type": "string"}, "type": "array"},
        "files": {"items": {"type": "string"}, "type": "array"},
        "pull_request_title": {"type": "string"},
    },
    "required": ["branch", "files", "pull_request_title"],
    "title": "CodeChanges",
    "type": "object",
}


def _schemas(code_changes: JsonSchema = CODE_CHANGES_V1) -> dict[str, JsonSchema]:
    return {"contracts.TaskList": TASK_LIST, "contracts.CodeChanges": code_changes}


def _fixture(version: str, code_changes: JsonSchema = CODE_CHANGES_V1) -> AgentSnapshot:
    folder = REGISTRY / version / "implementer"
    return build_snapshot(folder, load_agent_file(folder / "agent.yaml"), _schemas(code_changes))


def _edit(snapshot: AgentSnapshot, edits: dict[str, Any]) -> AgentSnapshot:
    """Copy a snapshot with dotted-path fields replaced, validating the result."""
    data = snapshot.model_dump(mode="json")
    for path, value in edits.items():
        *parents, last = path.split(".")
        node = data
        for key in parents:
            node = node[key]
        node[last] = value
    return AgentSnapshot.model_validate(data)


BASE = AgentSnapshot(
    agent=Agent.model_validate(
        {
            "name": "implementer",
            "brief": {
                "instructions": "prompt.md",
                "input": "contracts.TaskList",
                "output": "contracts.CodeChanges",
            },
            "capabilities": {
                "model": {
                    "provider": "openrouter",
                    "id": "anthropic/claude-sonnet",
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "routing": {"only": ["anthropic"], "allow_fallbacks": False},
                },
                "tools": ["repo.read_file", "repo.write_file"],
                "permissions": {"network": False, "secrets": ["GITHUB_TOKEN", "NPM_TOKEN"]},
            },
            "quality_gate": {"suite": "evals", "min_pass_rate": 0.8, "repeats": 3},
        }
    ),
    instructions="Implement the tasks.\nKeep changes small.\n",
    input_schema=TASK_LIST,
    output_schema=CODE_CHANGES_V1,
    eval_files=(
        EvalFile.of("cases/a.yaml", "input: a\n"),
        EvalFile.of("cases/b.yaml", "input: b\n"),
    ),
)


def _ascii(text: str) -> str:
    """Spell the minus sign in line counts as `-`, which Ruff does not mistake for a typo."""
    return text.replace("\N{MINUS SIGN}", "-")


def _summary(old: AgentSnapshot, new: AgentSnapshot) -> str:
    diff = diff_snapshots(old, new)
    return _ascii(summarise(diff, name="implementer", old_label="v1", new_label="v2"))


def _render(old: AgentSnapshot, new: AgentSnapshot, name: str = "implementer") -> str:
    return _ascii(render(diff_snapshots(old, new), name=name, old_label="v1", new_label="v2"))


# --- Building snapshots -----------------------------------------------------------------------


def test_build_snapshot_reads_the_agent_folder() -> None:
    snapshot_ = _fixture("v1")

    assert snapshot_.format == 1
    assert snapshot_.agent.name == "implementer"
    assert snapshot_.instructions.startswith("# Implementer\n")
    assert snapshot_.output_schema == CODE_CHANGES_V1
    # `.gitkeep` is tooling, not part of the Quality Gate.
    assert [file.path for file in snapshot_.eval_files] == [
        "cases/add-endpoint.yaml",
        "cases/rename-function.yaml",
    ]


def test_content_id_is_pinned() -> None:
    # If this changes, the canonical form changed: bump `format` and record it in ADR 0013.
    snapshot_ = _fixture("v1")

    assert content_id(snapshot_) == snapshot(
        "47de746256d1d80188d3fba5867d472d909cd799b792413fa43baff095ff4ac2"
    )
    assert short_id(content_id(snapshot_)) == content_id(snapshot_)[:12]


def test_canonical_bytes_are_sorted_compact_json() -> None:
    data = canonical_bytes(BASE)

    assert data.startswith(b'{"agent":{"brief":{"input":"contracts.TaskList",')
    assert b'"format":1' in data
    assert b"\n" not in data.replace(b"\\n", b"")
    assert snapshot_from_bytes(data) == BASE


def test_line_endings_and_byte_order_marks_do_not_change_identity(tmp_path: Path) -> None:
    folder = tmp_path / "implementer"
    shutil.copytree(REGISTRY / "v1" / "implementer", folder)
    for file in (folder / "prompt.md", folder / "evals" / "cases" / "add-endpoint.yaml"):
        crlf = file.read_text().replace("\n", "\r\n")
        file.write_bytes(b"\xef\xbb\xbf" + crlf.encode())

    agent = load_agent_file(folder / "agent.yaml")
    windows = build_snapshot(folder, agent, _schemas())

    assert content_id(windows) == content_id(_fixture("v1"))
    assert "\r" not in windows.instructions


def test_the_folder_location_is_not_part_of_identity(tmp_path: Path) -> None:
    folder = tmp_path / "elsewhere" / "implementer"
    shutil.copytree(REGISTRY / "v1" / "implementer", folder)

    moved = build_snapshot(folder, load_agent_file(folder / "agent.yaml"), _schemas())

    assert content_id(moved) == content_id(_fixture("v1"))


def test_eval_suite_skips_tooling_files(tmp_path: Path) -> None:
    suite = tmp_path / "evals"
    files = {
        ".gitkeep": "",
        ".pytest_cache/state": "x",
        "__pycache__/checks.cpython-314.pyc": "x",
        "checks.pyc": "x",
        "checks.py": "def check() -> None: ...\n",
        "cases/.DS_Store": "x",
        "cases/deep/case.yaml": "input: x\n",
    }
    for name, content in files.items():
        (suite / name).parent.mkdir(parents=True, exist_ok=True)
        (suite / name).write_text(content)
    (tmp_path / "prompt.md").write_text("Go.\n")

    snapshot_ = build_snapshot(tmp_path, BASE.agent, _schemas())

    assert [file.path for file in snapshot_.eval_files] == ["cases/deep/case.yaml", "checks.py"]


def test_a_single_file_eval_suite(tmp_path: Path) -> None:
    (tmp_path / "prompt.md").write_text("Go.\n")
    (tmp_path / "evals.yaml").write_text("cases: []\n")
    agent = _edit(BASE, {"agent.quality_gate.suite": "evals.yaml"}).agent

    snapshot_ = build_snapshot(tmp_path, agent, _schemas())

    assert snapshot_.eval_files == (EvalFile.of("evals.yaml", "cases: []\n"),)


def test_a_single_file_eval_suite_diffs_under_its_own_name(tmp_path: Path) -> None:
    (tmp_path / "prompt.md").write_text("Go.\n")
    (tmp_path / "evals.yaml").write_text("cases: []\n")
    agent = _edit(BASE, {"agent.quality_gate.suite": "evals.yaml"}).agent
    old = build_snapshot(tmp_path, agent, _schemas())
    (tmp_path / "evals.yaml").write_text("cases: [a]\n")
    new = build_snapshot(tmp_path, agent, _schemas())

    (change,) = [change for _, _, change in diff_snapshots(old, new).changes()]

    assert change.text_diff is not None
    assert change.text_diff.unified.splitlines()[:2] == ["--- a/evals.yaml", "+++ b/evals.yaml"]


def _layout(root: Path, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(content)


_GOOD = {"implementer/prompt.md": b"Go.\n", "implementer/evals/a.yaml": b"x: 1\n"}


def _snapshot_error(agent: Agent, schemas: dict[str, JsonSchema] | None = None) -> str:
    with pytest.raises(SnapshotError) as caught:
        build_snapshot(Path("implementer"), agent, _schemas() if schemas is None else schemas)
    return str(caught.value)


def test_build_snapshot_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    errors: dict[str, str] = {}

    errors["missing input schema"] = _snapshot_error(BASE.agent, {})
    errors["missing output schema"] = _snapshot_error(BASE.agent, {"contracts.TaskList": {}})
    errors["missing instructions"] = _snapshot_error(BASE.agent)
    _layout(tmp_path, {"implementer/prompt.md": b"Go \xff\n"})
    errors["instructions not UTF-8"] = _snapshot_error(BASE.agent)
    _layout(tmp_path, {"implementer/prompt.md": b"Go.\n"})
    errors["missing suite"] = _snapshot_error(BASE.agent)
    _layout(tmp_path, {"implementer/evals/a.yaml": b"\xc3\x28"})
    errors["eval file not UTF-8"] = _snapshot_error(BASE.agent)
    _layout(tmp_path, _GOOD)
    (tmp_path / "implementer/evals/linked.yaml").symlink_to(tmp_path / "implementer/prompt.md")
    errors["link in suite"] = _snapshot_error(BASE.agent)
    (tmp_path / "implementer/evals/linked.yaml").unlink()
    (tmp_path / "implementer/suite").symlink_to(tmp_path / "implementer/evals")
    errors["suite is a link"] = _snapshot_error(
        _edit(BASE, {"agent.quality_gate.suite": "suite"}).agent
    )
    (tmp_path / "implementer/linked").symlink_to(tmp_path / "implementer/evals")
    errors["folder on the way is a link"] = _snapshot_error(
        _edit(BASE, {"agent.brief.instructions": "linked/a.yaml"}).agent
    )
    errors["suite inside a linked folder"] = _snapshot_error(
        _edit(BASE, {"agent.quality_gate.suite": "linked/a.yaml"}).agent
    )
    (tmp_path / "implementer/dangling.md").symlink_to(tmp_path / "nowhere.md")
    errors["dangling link"] = _snapshot_error(
        _edit(BASE, {"agent.brief.instructions": "dangling.md"}).agent
    )
    (tmp_path / "implementer/evals/folder.yaml").mkdir()
    errors["instructions are a folder"] = _snapshot_error(
        _edit(BASE, {"agent.brief.instructions": "evals/folder.yaml"}).agent
    )
    # Valid as agent.yaml, but beyond the integers JSON carries exactly.
    data = BASE.agent.model_dump()
    data["capabilities"]["model"]["max_tokens"] = 2**60
    huge = Agent.model_validate(data)
    errors["not representable"] = _snapshot_error(huge).splitlines()[0]

    assert errors == snapshot(
        {
            "missing input schema": "no JSON Schema given for input contract 'contracts.TaskList'",
            "missing output schema": (
                "no JSON Schema given for output contract 'contracts.CodeChanges'"
            ),
            "missing instructions": "implementer/prompt.md: file not found",
            "instructions not UTF-8": (
                "implementer/prompt.md: not UTF-8 text (invalid byte at offset 3)"
            ),
            "missing suite": "implementer/evals: eval suite not found",
            "eval file not UTF-8": (
                "implementer/evals/a.yaml: not UTF-8 text (invalid byte at offset 0)"
            ),
            "link in suite": "implementer/evals/linked.yaml: symbolic links are not followed",
            "suite is a link": "implementer/suite: eval suite is a symbolic link",
            "folder on the way is a link": "implementer/linked: symbolic links are not followed",
            "suite inside a linked folder": "implementer/linked: symbolic links are not followed",
            "dangling link": "implementer/dangling.md: symbolic links are not followed",
            "instructions are a folder": "implementer/evals/folder.yaml: not a regular file",
            "not representable": (
                "implementer: cannot snapshot agent 'implementer': 1 validation error for"
                " AgentSnapshot"
            ),
        }
    )


# --- Validation and reading back --------------------------------------------------------------


def test_eval_files_are_sorted_and_unique() -> None:
    a, b = EvalFile.of("a.yaml", "a\n"), EvalFile.of("b.yaml", "b\n")

    shuffled = BASE.model_copy(update={"eval_files": ()})
    assert AgentSnapshot.model_validate(
        {**shuffled.model_dump(), "eval_files": [b, a]}
    ).eval_files == (a, b)
    with pytest.raises(ValidationError, match=r"duplicate eval file 'a\.yaml'"):
        AgentSnapshot.model_validate({**shuffled.model_dump(), "eval_files": [a, a]})


@pytest.mark.parametrize(
    "path", ["", "/abs.yaml", "a//b.yaml", "./a.yaml", "a/../b.yaml", "a\\b.yaml", "a/"]
)
def test_eval_file_paths_must_be_relative_posix(path: str) -> None:
    with pytest.raises(ValidationError, match="must be a relative POSIX path"):
        EvalFile.of(path, "")


def test_eval_file_digest_must_match_content() -> None:
    with pytest.raises(ValidationError, match="digest does not match content"):
        EvalFile(path="a.yaml", digest="0" * 64, content="a\n")


def test_schemas_must_have_a_canonical_form() -> None:
    with pytest.raises(ValidationError, match="no canonical JSON form"):
        _edit(BASE, {"output_schema": {"maximum": float("inf")}})


def test_snapshot_from_bytes_rejects_anything_not_canonical() -> None:
    data = canonical_bytes(BASE)
    errors: dict[str, str] = {}
    for label, bad in {
        "not JSON": b"{",
        "not UTF-8": b'"\xff"',
        "whitespace": data[:1] + b" " + data[1:],
        "unsupported format": data.replace(b'"format":1', b'"format":2'),
        "default left out": data.replace(b',"format":1', b""),
    }.items():
        with pytest.raises(SnapshotError) as caught:
            snapshot_from_bytes(bad)
        errors[label] = str(caught.value).splitlines()[0]

    assert errors == snapshot(
        {
            "not JSON": (
                "not a canonical agent snapshot: not valid UTF-8 JSON: Expecting property name"
                " enclosed in double quotes: line 1 column 2 (char 1)"
            ),
            "not UTF-8": (
                "not a canonical agent snapshot: not valid UTF-8 JSON: 'utf-8' codec can't decode"
                " byte 0xff in position 1: invalid start byte"
            ),
            "whitespace": (
                "not a canonical agent snapshot: JSON is not in canonical form (RFC 8785)"
            ),
            "unsupported format": (
                "not a canonical agent snapshot: 1 validation error for AgentSnapshot"
            ),
            "default left out": "not a canonical agent snapshot: content changes when read back",
        }
    )


def test_canonical_json_round_trips_awkward_numbers() -> None:
    value: JsonValue = {"big": 1e20, "huge": 1e21, "zero": -0.0, "int": 2**53 - 1, "tiny": 5e-324}

    data = canonical_json(value)

    assert data == snapshot(
        b'{"big":100000000000000000000,"huge":1e+21,"int":9007199254740991,"tiny":5e-324,"zero":0}'
    )
    assert canonical_json(load_canonical_json(data)) == data
    with pytest.raises(CanonicalFormError, match="no canonical JSON form"):
        canonical_json({"nan": float("nan")})
    with pytest.raises(CanonicalFormError, match="no canonical JSON form"):
        canonical_json(2**53)


@pytest.mark.parametrize("bad", ["", "ABC", "0" * 63, "0" * 65, "G" * 64])
def test_short_id_rejects_malformed_ids(bad: str) -> None:
    with pytest.raises(ValueError, match="not a content ID"):
        short_id(bad)


# --- Diffs ------------------------------------------------------------------------------------


def _reference_implementer(example: Path) -> AgentSnapshot:
    """The reference factory's implementer, with the schemas of its real contracts."""
    folder = example / "agents" / "implementer"
    agent = load_agent_file(folder / "agent.yaml")
    schemas = resolve_contract_schemas(example, [agent.brief.input, agent.brief.output])
    return build_snapshot(folder, agent, schemas)


def _reversed_keys(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _reversed_keys(value[key]) for key in reversed(value)}
    if isinstance(value, list):
        return [_reversed_keys(item) for item in value]
    return value


def test_real_contract_schemas_hash_the_same_in_any_key_order(example: Path) -> None:
    # `contract_schema` keeps Pydantic's field order; the canonical form must not depend on it.
    implementer = _reference_implementer(example)
    data = implementer.model_dump()
    data["input_schema"] = _reversed_keys(implementer.input_schema)
    data["output_schema"] = _reversed_keys(implementer.output_schema)

    reordered = AgentSnapshot.model_validate(data)

    assert implementer.output_schema["title"] == "CodeChanges"
    assert list(reordered.output_schema) != list(implementer.output_schema)
    assert content_id(reordered) == content_id(implementer)
    assert snapshot_from_bytes(canonical_bytes(implementer)) == implementer


def test_switching_the_reference_agent_model(example: Path) -> None:
    """The milestone's acceptance sentence, on the reference factory's implementer."""
    v1 = _reference_implementer(example)
    v2 = _edit(v1, {"agent.capabilities.model.id": "openai/gpt-5"})

    assert _summary(v1, v2) == snapshot(
        "implementer v1 → v2: Capabilities changed; model profile changed; model switched"
        " (anthropic/claude-sonnet → openai/gpt-5)"
    )


def test_identical_snapshots_have_no_changes() -> None:
    diff = diff_snapshots(_fixture("v1"), _fixture("v1"))

    assert diff.empty
    assert diff == AgentDiff()
    assert summarise(diff, name="implementer", old_label="v1", new_label="v1") == snapshot(
        "implementer v1 → v1: no changes"
    )
    assert render(diff, name="implementer", old_label="v1", new_label="v1") == snapshot(
        "implementer v1 → v1: no changes\n"
    )


def test_line_counts_use_a_true_minus_sign() -> None:
    diff = diff_snapshots(BASE, _edit(BASE, {"instructions": "Implement the tasks.\n"}))

    summary = summarise(diff, name="implementer", old_label="v1", new_label="v2")

    assert summary.endswith("instructions edited (+0 \N{MINUS SIGN}1 lines)")


def test_a_realistic_change_summary_is_capped() -> None:
    v1, v2 = _fixture("v1"), _fixture("v2", CODE_CHANGES_V2)

    assert _summary(v1, v2) == snapshot(
        "implementer v1 → v2: Brief changed; instructions changed; instructions edited"
        " (+3 -1 lines); contract pair changed; output contract changed; Capabilities changed;"
        " model profile changed; model switched (anthropic/claude-sonnet → openai/gpt-5);"
        " temperature changed (0.0 → 0.2); routing providers changed (anthropic → openai);"
        " toolkit changed; tool added (github.create_pull_request); and 6 more"
    )
    assert _summary(v2, v1) == snapshot(
        "implementer v1 → v2: Brief changed; instructions changed; instructions edited"
        " (+1 -3 lines); contract pair changed; output contract changed; Capabilities changed;"
        " model profile changed; model switched (openai/gpt-5 → anthropic/claude-sonnet);"
        " temperature changed (0.2 → 0.0); routing providers changed (openai → anthropic);"
        " toolkit changed; tool removed (github.create_pull_request); and 6 more"
    )


def test_a_realistic_change_renders_in_full() -> None:
    v1, v2 = _fixture("v1"), _fixture("v2", CODE_CHANGES_V2)

    assert _render(v1, v2) == (
        snapshot("""\
implementer v1 → v2
  Brief
    instructions
      instructions edited (+3 -1 lines)
        --- a/prompt.md
        +++ b/prompt.md
        @@ -1,7 +1,9 @@
         # Implementer
         \n\
        -Implement each task as code changes on a branch.
        +Implement each task as code changes on a branch, then open a pull request.
         \n\
         - Work through the tasks in dependency order.
         - Keep each change small and focused on its task.
         - Write tests alongside the code they cover.
        +- Run the tests before opening the pull request.
        +- Link every commit to the task it implements.
    contract pair
      output contract changed
        /properties/commits/items added ({"type": "string"})
        /properties/commits/type changed ("integer" → "array")
        /properties/pull_request_title added ({"type": "string"})
        /required changed (["branch", "files"] → ["branch", "files", "pull_request_title"])
  Capabilities
    model profile
      model switched (anthropic/claude-sonnet → openai/gpt-5)
      temperature changed (0.0 → 0.2)
      routing providers changed (anthropic → openai)
    toolkit
      tool added (github.create_pull_request)
      network permission granted
      secret added (GITHUB_TOKEN)
  Quality Gate
    eval suite
      pass threshold raised (0.8 → 0.9)
      eval case edited (cases/add-endpoint.yaml, +2 -2 lines)
        --- a/evals/cases/add-endpoint.yaml
        +++ b/evals/cases/add-endpoint.yaml
        @@ -3,6 +3,6 @@
           tasks:
             - id: t1
               title: Add GET /health
        -      acceptance_criteria: [returns 200, has a test]
        +      acceptance_criteria: [returns 200, has a test, documented in the README]
         expected:
        -  files_changed: 2
        +  files_changed: 3
      eval case added (cases/multi-file-refactor.yaml)
        --- a/evals/cases/multi-file-refactor.yaml
        +++ b/evals/cases/multi-file-refactor.yaml
        @@ -0,0 +1,8 @@
        +name: multi-file-refactor
        +input:
        +  tasks:
        +    - id: t1
        +      title: Extract the retry loop into a helper
        +      acceptance_criteria: [no behaviour change, helper has tests]
        +expected:
        +  files_changed: 4
      eval case removed (cases/rename-function.yaml)
        --- a/evals/cases/rename-function.yaml
        +++ b/evals/cases/rename-function.yaml
        @@ -1,8 +0,0 @@
        -name: rename-function
        -input:
        -  tasks:
        -    - id: t1
        -      title: Rename parse() to parse_config()
        -      acceptance_criteria: [all call sites updated]
        -expected:
        -  files_changed: 3
""")
    )


_WITHOUT_ROUTING = {
    "agent.capabilities.model.provider": "anthropic",
    "agent.capabilities.model.routing": None,
}
_PHRASE_CASES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "provider": ({}, _WITHOUT_ROUTING),
    "routing added": (_WITHOUT_ROUTING, {}),
    "temperature": ({}, {"agent.capabilities.model.temperature": 0.5}),
    "top_p": ({}, {"agent.capabilities.model.top_p": 0.9}),
    "max_tokens": ({}, {"agent.capabilities.model.max_tokens": None}),
    "any provider": ({}, {"agent.capabilities.model.routing.only": None}),
    "fallbacks": ({}, {"agent.capabilities.model.routing.allow_fallbacks": True}),
    "no fallbacks": ({"agent.capabilities.model.routing.allow_fallbacks": True}, {}),
    "tools": ({}, {"agent.capabilities.tools": ["repo.write_file", "repo.search"]}),
    "tool order": ({}, {"agent.capabilities.tools": ["repo.write_file", "repo.read_file"]}),
    "network": ({"agent.capabilities.permissions.network": True}, {}),
    "secrets": ({}, {"agent.capabilities.permissions.secrets": ["NPM_TOKEN", "GITHUB_TOKEN"]}),
    "secret removed": ({}, {"agent.capabilities.permissions.secrets": ["NPM_TOKEN"]}),
    "instructions": ({}, {"instructions": "Implement the tasks.\n"}),
    "instructions file": ({}, {"agent.brief.instructions": "system.md"}),
    "input contract": ({}, {"agent.brief.input": "contracts.Plan"}),
    "eval suite": ({}, {"agent.quality_gate.suite": "tests/evals"}),
    "threshold": ({}, {"agent.quality_gate.min_pass_rate": 0.5}),
    "repeats up": ({}, {"agent.quality_gate.repeats": 5}),
    "repeats down": ({}, {"agent.quality_gate.repeats": 1}),
    "eval files": (
        {},
        {"eval_files": [EvalFile.of("cases/a.yaml", "input: z").model_dump()]},
    ),
    "renamed": ({}, {"agent.name": "builder"}),
    "long value": ({}, {"agent.capabilities.model.id": "vendor/" + "x" * 60}),
}


def test_every_kind_of_change_has_a_phrase() -> None:
    summaries = {
        label: _summary(_edit(BASE, old), _edit(BASE, new))
        for label, (old, new) in _PHRASE_CASES.items()
    }

    assert summaries == snapshot(
        {
            "provider": (
                "implementer v1 → v2: Capabilities changed; model profile changed; provider"
                " switched (openrouter → anthropic); routing removed"
            ),
            "routing added": (
                "implementer v1 → v2: Capabilities changed; model profile changed; provider"
                " switched (anthropic → openrouter); routing added"
            ),
            "temperature": (
                "implementer v1 → v2: Capabilities changed; model profile changed; temperature"
                " changed (0.2 → 0.5)"
            ),
            "top_p": (
                "implementer v1 → v2: Capabilities changed; model profile changed; top_p set (0.9)"
            ),
            "max_tokens": (
                "implementer v1 → v2: Capabilities changed; model profile changed; max_tokens"
                " unset (was 4096)"
            ),
            "any provider": (
                "implementer v1 → v2: Capabilities changed; model profile changed; routing"
                " providers changed (anthropic → any)"
            ),
            "fallbacks": (
                "implementer v1 → v2: Capabilities changed; model profile changed; fallbacks"
                " allowed"
            ),
            "no fallbacks": (
                "implementer v1 → v2: Capabilities changed; model profile changed; fallbacks"
                " disallowed"
            ),
            "tools": (
                "implementer v1 → v2: Capabilities changed; toolkit changed; tool removed"
                " (repo.read_file); tool added (repo.search)"
            ),
            "tool order": (
                "implementer v1 → v2: Capabilities changed; toolkit changed; tools reordered"
            ),
            "network": (
                "implementer v1 → v2: Capabilities changed; toolkit changed; network permission"
                " revoked"
            ),
            "secrets": (
                "implementer v1 → v2: Capabilities changed; toolkit changed; secrets reordered"
            ),
            "secret removed": (
                "implementer v1 → v2: Capabilities changed; toolkit changed; secret removed"
                " (GITHUB_TOKEN)"
            ),
            "instructions": (
                "implementer v1 → v2: Brief changed; instructions changed; instructions edited"
                " (+0 -1 lines)"
            ),
            "instructions file": (
                "implementer v1 → v2: Brief changed; instructions changed; instructions file"
                " renamed (prompt.md → system.md)"
            ),
            "input contract": (
                "implementer v1 → v2: Brief changed; contract pair changed; input contract"
                " switched (contracts.TaskList → contracts.Plan)"
            ),
            "eval suite": (
                "implementer v1 → v2: Quality Gate changed; eval suite changed; eval suite moved"
                " (evals → tests/evals)"
            ),
            "threshold": (
                "implementer v1 → v2: Quality Gate changed; eval suite changed; pass threshold"
                " lowered (0.8 → 0.5)"
            ),
            "repeats up": (
                "implementer v1 → v2: Quality Gate changed; eval suite changed; repeats increased"
                " (3 → 5)"
            ),
            "repeats down": (
                "implementer v1 → v2: Quality Gate changed; eval suite changed; repeats decreased"
                " (3 → 1)"
            ),
            "eval files": (
                "implementer v1 → v2: Quality Gate changed; eval suite changed; eval case edited"
                " (cases/a.yaml, +1 -1 lines); eval case removed (cases/b.yaml)"
            ),
            "renamed": "implementer v1 → v2: renamed (implementer → builder)",
            "long value": (
                "implementer v1 → v2: Capabilities changed; model profile changed; model switched"
                " (anthropic/claude-sonnet → vendor/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx…)"
            ),
        }
    )


def test_rename_renders_before_the_blocks() -> None:
    new = _edit(BASE, {"agent.name": "builder", "agent.capabilities.tools": []})

    assert _render(BASE, new, "builder") == (
        snapshot("""\
builder v1 → v2
  renamed (implementer → builder)
  Capabilities
    toolkit
      tool removed (repo.read_file)
      tool removed (repo.write_file)
""")
    )


def test_diffs_are_typed_and_serialisable() -> None:
    diff = diff_snapshots(_fixture("v1"), _fixture("v2", CODE_CHANGES_V2))

    assert AgentDiff.model_validate_json(diff.model_dump_json()) == diff
    assert [block.name for block in diff.blocks] == [
        Block.BRIEF,
        Block.CAPABILITIES,
        Block.QUALITY_GATE,
    ]
    first = next(diff.changes())
    assert first[:2] == (Block.BRIEF, Component.INSTRUCTIONS)
    assert first[2].kind is Primitive.INSTRUCTION
    contract = [change for _, _, change in diff.changes() if change.field == "output_schema"]
    assert [(change.change, change.item) for change in contract] == snapshot(
        [
            ("added", "/properties/commits/items"),
            ("changed", "/properties/commits/type"),
            ("added", "/properties/pull_request_title"),
            ("changed", "/required"),
        ]
    )


def test_text_diff_marks_a_missing_final_newline() -> None:
    diff = text_diff("a\nb\n", "a\nb", old_name="x", new_name="x")

    assert diff.unified == snapshot("""\
--- a/x
+++ b/x
@@ -1,2 +1,2 @@
 a
-b
+b
\\ No newline at end of file
""")
    assert (diff.added, diff.removed) == (1, 1)


def test_json_changes_escape_pointers_and_compare_types() -> None:
    old: JsonValue = {"a/b": {"~": 1}, "list": [1, 2], "flag": 1, "same": [1.0]}
    new: JsonValue = {"a/b": {"~": 2}, "list": [1, 2, 3], "flag": True, "same": [1]}

    assert list(json_changes(old, new)) == snapshot(
        [
            ("changed", "/a~1b/~0", 1, 2),
            ("changed", "/flag", 1, True),
            ("changed", "/list", [1, 2], [1, 2, 3]),
        ]
    )


def _leaf_fields(model: type[BaseModel], prefix: str = "") -> list[str]:
    fields: list[str] = []
    for name, info in model.model_fields.items():
        nested = [arg for arg in get_args(info.annotation) if isinstance(arg, type)]
        models = [
            arg
            for arg in [info.annotation, *nested]
            if isinstance(arg, type) and issubclass(arg, BaseModel)
        ]
        if models:
            fields.extend(_leaf_fields(models[0], f"{prefix}{name}."))
        else:
            fields.append(f"{prefix}{name}")
    return fields


def test_every_snapshot_field_is_diffed() -> None:
    """A new field must be added to `diff_snapshots`, its phrases and this list together."""
    assert _leaf_fields(AgentSnapshot) == snapshot(
        [
            "format",
            "agent.name",
            "agent.brief.instructions",
            "agent.brief.input",
            "agent.brief.output",
            "agent.capabilities.model.provider",
            "agent.capabilities.model.id",
            "agent.capabilities.model.temperature",
            "agent.capabilities.model.top_p",
            "agent.capabilities.model.max_tokens",
            "agent.capabilities.model.routing.only",
            "agent.capabilities.model.routing.allow_fallbacks",
            "agent.capabilities.tools",
            "agent.capabilities.permissions.network",
            "agent.capabilities.permissions.secrets",
            "agent.quality_gate.suite",
            "agent.quality_gate.min_pass_rate",
            "agent.quality_gate.repeats",
            "instructions",
            "input_schema",
            "output_schema",
            "eval_files.path",
            "eval_files.digest",
            "eval_files.content",
        ]
    )
