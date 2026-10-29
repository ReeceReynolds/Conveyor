"""The `conveyor agent` commands, through Typer's test runner."""

import getpass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from inline_snapshot import snapshot
from typer.testing import CliRunner, Result

from conveyor.cli import app
from conveyor.cli_agent import Clock
from conveyor.storage import STATE_DIR, Store

runner = CliRunner()

WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
OLD_MODEL = "id: anthropic/claude-sonnet"
NEW_MODEL = "id: openai/gpt-5"


def _agent(*args: str, minutes: int = 0) -> Result:
    """Run `conveyor agent ...` at a pinned time."""
    clock = Clock(now=lambda: WHEN + timedelta(minutes=minutes))
    return runner.invoke(app, ["agent", *args], obj=clock)


def _redacted(text: str, project: Path, name: str = "implementer") -> str:
    """Replace an agent's content IDs with `<vN>`, so outputs do not pin the example's hashes."""
    with Store.open(project) as store:
        records = store.registry.history(name)
    for record in reversed(records):
        text = text.replace(record.content_id, f"<v{record.sequence} id>")
        text = text.replace(record.content_id[:12], f"<v{record.sequence}>")
    return text


def _plain(output: str) -> str:
    """The words of an output, without the box Rich draws around usage errors."""
    return " ".join(output.translate(str.maketrans("", "", "│╭╮╰╯─")).split())


def _switch_model(project: Path, old: str = OLD_MODEL, new: str = NEW_MODEL) -> None:
    file = project / "agents" / "implementer" / "agent.yaml"
    file.write_text(file.read_text().replace(old, new))


@pytest.fixture
def project(example_project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The reference factory, as the current directory, so `--project` can be left out."""
    monkeypatch.chdir(example_project)
    monkeypatch.setattr(getpass, "getuser", lambda: "ada")
    return example_project


def test_the_milestone_acceptance_flow(example_project: Path) -> None:
    """Publish the example's implementer, switch its model, publish again and diff."""
    root = ["--project", str(example_project)]
    author = ["--author", "ada"]

    first = _agent("publish", "implementer", "-m", "initial", *author, *root)
    _switch_model(example_project)
    working = _agent("diff", "implementer", "--working", "--summary", *root)
    second = _agent("publish", "implementer", "-m", "Switch to GPT-5", *author, *root,
        minutes=5,
    )  # fmt: skip
    diff = _agent("diff", "implementer", "--summary", *root)
    history = _agent("history", "implementer", *root)

    assert [first.exit_code, working.exit_code, second.exit_code] == [0, 0, 0]
    assert [diff.exit_code, history.exit_code] == [0, 0]
    assert _redacted(first.output, example_project) == snapshot(
        "Published implementer v1 (<v1>): first version\n"
    )
    assert working.output == snapshot(
        "implementer v1 → working copy: Capabilities changed; model profile changed; model"
        " switched (anthropic/claude-sonnet → openai/gpt-5)\n"
    )
    assert _redacted(second.output, example_project) == snapshot(
        "Published implementer v2 (<v2>): Capabilities changed; model profile changed; model"
        " switched (anthropic/claude-sonnet → openai/gpt-5)\n"
    )
    assert diff.output == (
        "implementer v1 → v2: Capabilities changed; model profile changed; model switched"
        " (anthropic/claude-sonnet → openai/gpt-5)\n"
    )
    assert _redacted(history.output, example_project) == snapshot("""\
v2  <v2>  2026-10-28 12:05  ada  Switch to GPT-5
v1  <v1>  2026-10-28 12:00  ada  initial
""")


# --- publish ----------------------------------------------------------------------------------


def test_publish_defaults_to_the_current_project_and_user(project: Path) -> None:
    result = _agent("publish", "implementer", "-m", "initial")

    assert result.exit_code == 0
    with Store.open(project) as store:
        latest = store.registry.latest("implementer")
    assert latest is not None
    assert (latest.author, latest.message, latest.created_at) == ("ada", "initial", WHEN)


def test_publish_records_the_current_time_by_default(project: Path) -> None:
    before = datetime.now(UTC)
    result = runner.invoke(app, ["agent", "publish", "implementer", "-m", "initial"])
    after = datetime.now(UTC)

    assert result.exit_code == 0
    with Store.open(project) as store:
        latest = store.registry.latest("implementer")
    assert latest is not None
    assert before <= latest.created_at <= after


def test_publishing_unchanged_content_publishes_nothing(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")

    result = _agent("publish", "implementer", "-m", "again", minutes=5)

    assert result.exit_code == 0
    assert _redacted(result.output, project) == snapshot(
        "implementer is unchanged since v1 (<v1>); nothing published\n"
    )


def test_publish_prints_the_problems_of_an_invalid_agent(project: Path) -> None:
    file = project / "agents" / "implementer" / "agent.yaml"
    file.write_text(file.read_text().replace("repeats: 3", "repeats: 0\ncolour: red"))

    result = _agent("publish", "implementer", "-m", "initial")

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "agents/implementer/agent.yaml:21:12: quality_gate.repeats: input should be greater than"
        " or equal to 1",
        "agents/implementer/agent.yaml:22:1: colour: unknown field",
        "Found 2 problems in implementer; nothing published.",
    ]

    assert not (project / STATE_DIR).exists()


@pytest.mark.usefixtures("project")
def test_publish_reports_an_unknown_agent() -> None:
    result = _agent("publish", "ghost", "-m", "initial")

    assert result.exit_code == 1
    assert result.output == snapshot("""\
agents/ghost: not an agent folder: no agent.yaml
Found 1 problem in ghost; nothing published.
""")


@pytest.mark.usefixtures("project")
def test_publish_needs_an_author_when_the_user_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def unknown() -> str:
        raise OSError

    monkeypatch.setattr(getpass, "getuser", unknown)

    refused = _agent("publish", "implementer", "-m", "initial")
    accepted = _agent("publish", "implementer", "-m", "initial", "--author", "ci")

    assert refused.exit_code == 2
    assert "pass --author" in refused.output
    assert accepted.exit_code == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["publish", "implementer"], "Missing option '--message'"),
        (["publish", "implementer", "-m", "  "], "must not be blank"),
        (["publish", "implementer", "-m", "m", "--author", ""], "must not be blank"),
        (["publish", "Implementer", "-m", "m"], "not an agent name"),
        (["publish", "../implementer", "-m", "m"], "not an agent name"),
        (["history", "a/b"], "not an agent name"),
        (["show", "Bad@v1"], "not an agent name"),
        (["diff", "implementer", "v1", "v2", "--working"], "give either TO or --working"),
    ],
)
@pytest.mark.usefixtures("project")
def test_usage_errors_exit_two(args: list[str], message: str) -> None:
    result = _agent(*args)

    assert result.exit_code == 2
    assert message in _plain(result.output)


@pytest.mark.parametrize("command", ["publish", "history", "show", "diff"])
def test_a_folder_without_agents_is_not_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.chdir(tmp_path)
    args = [command, "implementer", *(["-m", "m"] if command == "publish" else [])]

    result = _agent(*args)

    assert result.exit_code == 2
    assert f"{Path()} is not a Conveyor project: it has no agents/ folder" in _plain(result.output)
    assert not (tmp_path / STATE_DIR).exists()


# --- history ----------------------------------------------------------------------------------


def test_history_aligns_columns_and_shows_first_message_lines(project: Path) -> None:
    prompt = project / "agents" / "implementer" / "prompt.md"
    _agent("publish", "implementer", "-m", "initial", "--author", "Ada Lovelace")
    for sequence in range(2, 11):
        prompt.write_text(f"{prompt.read_text()}Revision {sequence}.\n")
        message = f"Revise {sequence}\n\nDetails."
        _agent("publish", "implementer", "-m", message, minutes=sequence)

    result = _agent("history", "implementer")

    assert result.exit_code == 0
    with Store.open(project) as store:
        ids = [record.content_id[:12] for record in store.registry.history("implementer")]
    lines = result.output.splitlines()
    assert [line.split()[1] for line in lines] == ids
    # Every short ID is 12 characters, so blanking them keeps the columns as printed.
    blanked = [line.replace(line.split()[1], "<short id12>") for line in lines]
    assert blanked[:2] == snapshot(
        [
            "v10  <short id12>  2026-10-28 12:10  ada           Revise 10",
            "v9   <short id12>  2026-10-28 12:09  ada           Revise 9",
        ]
    )
    assert blanked[-1] == snapshot("v1   <short id12>  2026-10-28 12:00  Ada Lovelace  initial")
    assert len(lines) == 10


@pytest.mark.usefixtures("project")
def test_history_of_an_unpublished_agent_fails() -> None:
    result = _agent("history", "implementer")

    assert result.exit_code == 1
    assert result.output == "agent 'implementer' has no published versions\n"


# --- show -------------------------------------------------------------------------------------


def test_show_describes_a_version(project: Path) -> None:
    evals = project / "agents" / "implementer" / "evals"
    (evals / "cases").mkdir()
    (evals / "cases" / "small-change.yaml").write_text("task: rename a variable\n")
    (evals / "README.md").write_text("Évals for the implementer.\n")
    _agent("publish", "implementer", "-m", "initial\n\nWith two eval files.")

    result = _agent("show", "implementer")

    assert result.exit_code == 0
    assert _redacted(result.output, project) == snapshot("""\
implementer v1 (<v1>)
Content ID:   <v1 id>
Follows:      nothing (first version)
Author:       ada
Published:    2026-10-28 12:00:00 UTC
Message:      initial

              With two eval files.

agent.yaml
    brief: {input: contracts.TaskList, instructions: prompt.md, output:
        contracts.CodeChanges}
    capabilities:
      model:
        id: anthropic/claude-sonnet
        provider: openrouter
        routing:
          allow_fallbacks: false
          only: [anthropic]
        temperature: 0.0
    name: implementer
    quality_gate: {min_pass_rate: 0.9, repeats: 3, suite: evals}

Instructions: prompt.md (146 bytes)
Eval suite:   evals (2 files, 52 bytes)
    README.md (28 bytes)
    cases/small-change.yaml (24 bytes)
""")


def test_show_selects_versions_by_ref(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")
    _switch_model(project)
    _agent("publish", "implementer", "-m", "Switch to GPT-5")
    with Store.open(project) as store:
        first = store.registry.get("implementer", 1)

    by_sequence = _agent("show", "implementer@v1")
    by_prefix = _agent("show", f"implementer@{first.content_id[:6]}")
    latest = _agent("show", "implementer@latest")

    assert by_sequence.output == by_prefix.output
    assert by_sequence.output.startswith(f"implementer v1 ({first.content_id[:12]})\n")
    assert "Follows:      v1\n" in latest.output
    assert "id: openai/gpt-5" in latest.output


@pytest.mark.parametrize(
    ("ref", "exit_code", "message"),
    [
        ("v7", 1, "agent 'implementer' has no version v7"),
        ("xyz", 2, "not a version: 'xyz'"),
        ("", 2, "not a version: ''"),
    ],
)
@pytest.mark.usefixtures("project")
def test_show_rejects_bad_refs(ref: str, exit_code: int, message: str) -> None:
    _agent("publish", "implementer", "-m", "initial")

    result = _agent("show", f"implementer@{ref}")

    assert result.exit_code == exit_code
    assert message in _plain(result.output)


def test_a_corrupt_registry_is_reported(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")
    with Store.open(project) as store:
        digest = store.registry.get("implementer", 1).snapshot_digest
    (project / STATE_DIR / "objects" / digest[:2] / digest[2:]).write_bytes(b"{}")

    result = _agent("show", "implementer")

    assert result.exit_code == 1
    assert result.output.startswith(
        f"The registry in . cannot be read: object {digest} is corrupt: its content hashes to "
    )


# --- diff -------------------------------------------------------------------------------------


def test_diff_renders_every_change_in_full(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")
    _switch_model(project)
    prompt = project / "agents" / "implementer" / "prompt.md"
    prompt.write_text(prompt.read_text() + "Keep every change small.\n")
    _agent("publish", "implementer", "-m", "Switch to GPT-5")

    result = _agent("diff", "implementer")

    assert result.exit_code == 0
    assert result.output == snapshot("""\
implementer v1 → v2
  Brief
    instructions
      instructions edited (+1 \N{MINUS SIGN}0 lines)
        --- a/prompt.md
        +++ b/prompt.md
        @@ -3,3 +3,4 @@
         Implement the tasks as code changes on a branch.
         \n\
         Placeholder instructions. The real prompt is written once agent execution lands.
        +Keep every change small.
  Capabilities
    model profile
      model switched (anthropic/claude-sonnet → openai/gpt-5)
""")


def test_diff_compares_any_two_versions(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")
    _switch_model(project)
    _agent("publish", "implementer", "-m", "Switch to GPT-5")
    _switch_model(project, NEW_MODEL, "id: google/gemini")
    _agent("publish", "implementer", "-m", "Switch to Gemini")

    explicit = _agent("diff", "implementer", "v3", "v1", "--summary")
    to_latest = _agent("diff", "implementer", "v1", "--summary")

    assert explicit.output == snapshot(
        "implementer v3 → v1: Capabilities changed; model profile changed; model switched"
        " (google/gemini → anthropic/claude-sonnet)\n"
    )
    assert to_latest.output.startswith("implementer v1 → v3: ")


def test_diff_working_compares_from_any_version(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")
    _switch_model(project)
    _agent("publish", "implementer", "-m", "Switch to GPT-5")

    latest = _agent("diff", "implementer", "--working")
    from_v1 = _agent("diff", "implementer", "v1", "--working", "--summary")

    assert latest.output == "implementer v2 → working copy: no changes\n"
    assert from_v1.output.startswith("implementer v1 → working copy: Capabilities changed;")


def test_diff_exit_code(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")

    same = _agent("diff", "implementer", "--working", "--exit-code")
    _switch_model(project)
    different = _agent("diff", "implementer", "--working", "--exit-code", "--summary")
    without_flag = _agent("diff", "implementer", "--working", "--summary")

    assert (same.exit_code, different.exit_code, without_flag.exit_code) == (0, 1, 0)
    assert different.output == without_flag.output


def test_diff_with_a_single_version_suggests_working(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")

    result = _agent("diff", "implementer")

    assert result.exit_code == 1
    assert _redacted(result.output, project) == snapshot(
        "implementer has only one version, v1 (<v1>); use --working to compare it with"
        " agents/implementer/ on disk\n"
    )


@pytest.mark.usefixtures("project")
def test_diff_of_an_unpublished_agent_fails() -> None:
    result = _agent("diff", "implementer", "--working")

    assert result.exit_code == 1
    assert result.output == "agent 'implementer' has no published versions\n"


def test_diff_working_reports_an_invalid_working_copy(project: Path) -> None:
    _agent("publish", "implementer", "-m", "initial")
    (project / "agents" / "implementer" / "prompt.md").unlink()

    result = _agent("diff", "implementer", "--working")

    assert result.exit_code == 1
    assert result.output == snapshot("""\
agents/implementer/agent.yaml:5:17: brief.instructions: file 'prompt.md' not found
Found 1 problem in implementer; cannot compare the working copy.
""")


def test_agent_without_a_command_shows_help() -> None:
    result = runner.invoke(app, ["agent"])

    assert result.exit_code == 2
    for command in ("publish", "history", "show", "diff"):
        assert command in result.output
