"""The `conveyor` command line, through Typer's test runner."""

import textwrap
from pathlib import Path

import pytest
from inline_snapshot import snapshot
from typer.testing import CliRunner

from conveyor import __version__
from conveyor.cli import app

runner = CliRunner()


@pytest.fixture
def broken_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A small project with problems in a factory and an agent, run from its parent folder."""
    monkeypatch.chdir(tmp_path)
    agent = tmp_path / "p" / "agents" / "a"
    (agent / "evals").mkdir(parents=True)
    (agent / "prompt.md").write_text("# Prompt\n")
    (agent / "agent.yaml").write_text(
        textwrap.dedent(
            """\
            name: a
            brief:
              { instructions: prompt.md, input: contracts.In, output: contracts.Out, colour: red }
            capabilities:
              model: { provider: anthropic, id: claude }
            quality_gate: { suite: evals, min_pass_rate: 2 }
            """
        )
    )
    factories = tmp_path / "p" / "factories"
    factories.mkdir()
    (factories / "f.yaml").write_text(
        textwrap.dedent(
            """\
            name: f
            trigger: { manual: true }
            stages:
              - { id: x, agent: a }
              - { id: x, agent: ghost }
            outcome: { scorers: [scorers.done] }
            """
        )
    )
    return Path("p")


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"conveyor {__version__}\n"


def test_no_arguments_shows_help_as_a_usage_error() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "validate" in result.output


def test_validate_valid_example_exits_zero(example: Path) -> None:
    result = runner.invoke(app, ["validate", str(example)])

    assert result.exit_code == 0
    assert result.output == "Validated 4 agents and 1 factory: no problems found.\n"


def test_validate_prints_every_problem_and_exits_one(broken_project: Path) -> None:
    result = runner.invoke(app, ["validate", str(broken_project)])

    assert result.exit_code == 1
    assert result.output == snapshot("""\
p/agents/a/agent.yaml:3:74: brief.colour: unknown field
p/agents/a/agent.yaml:6:46: quality_gate.min_pass_rate: input should be less than or equal to 1
p/factories/f.yaml:5:11: stages[1].id: duplicate stage id 'x' (first used by stages[0])
p/factories/f.yaml:5:21: stages[1].agent: agent not found: no folder p/agents/ghost
Found 4 problems in 1 agent and 1 factory.
""")


def test_validate_single_agent_folder(broken_project: Path) -> None:
    result = runner.invoke(app, ["validate", str(broken_project / "agents" / "a")])

    assert result.exit_code == 1
    assert result.output.endswith("Found 2 problems in 1 agent.\n")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["validate"], "Missing argument"),
        (["validate", "nowhere"], "does not exist"),
        (["validate", "--colour"], "No such option"),
    ],
)
def test_usage_errors_exit_two(args: list[str], message: str) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert message in result.output


def test_nothing_to_validate_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("empty").mkdir()

    result = runner.invoke(app, ["validate", "empty"])

    assert result.exit_code == 2
    assert "has no agent.yaml" in result.output
