"""Every model rule, exercised through YAML fixtures so positions are realistic."""

from collections.abc import Callable
from pathlib import Path

import pytest
from inline_snapshot import snapshot

from conveyor.model import Agent, ConfigError, Factory, load_agent_file, load_factory_file
from conveyor.model.errors import format_loc


def _errors(load: Callable[[Path], object], file: Path) -> list[tuple[str, str, str]]:
    """Load `file` expecting failure; return each issue as (line:column, field path, message)."""
    with pytest.raises(ConfigError) as caught:
        load(file)
    return [
        (f"{issue.line}:{issue.column}", format_loc(issue.loc), issue.message)
        for issue in caught.value.issues
    ]


@pytest.mark.usefixtures("in_fixtures")
def test_valid_agents_load() -> None:
    full = load_agent_file(Path("agents/valid-full.yaml"))
    minimal = load_agent_file(Path("agents/valid-minimal.yaml"))

    assert isinstance(full, Agent)
    assert full.capabilities.model.routing is not None
    assert full.capabilities.model.routing.only == ("anthropic", "amazon-bedrock")
    assert full.capabilities.permissions.secrets == ("GITHUB_TOKEN",)
    assert minimal.capabilities.tools == ()
    assert not minimal.capabilities.permissions.network
    assert minimal.quality_gate.repeats == 1


@pytest.mark.usefixtures("in_fixtures")
def test_valid_factory_loads() -> None:
    factory = load_factory_file(Path("factories/valid-minimal.yaml"))

    assert isinstance(factory, Factory)
    assert [stage.id for stage in factory.stages] == ["only"]


@pytest.mark.usefixtures("in_fixtures")
def test_invalid_agents_report_every_problem() -> None:
    results = {
        file.name: _errors(load_agent_file, file)
        for file in sorted(Path("agents").glob("invalid-*.yaml"))
    }

    assert results == snapshot(
        {
            "invalid-brief.yaml": [
                ("2:1", "brief.output", "required field is missing"),
                (
                    "3:17",
                    "brief.instructions",
                    "must be a relative path inside the folder, got '/etc/prompt.md'",
                ),
                (
                    "4:10",
                    "brief.input",
                    "must be a dotted reference like 'contracts.TaskList', got 'TaskList'",
                ),
                (
                    "7:24",
                    "quality_gate.suite",
                    "must be a relative path inside the folder, got '../evals'",
                ),
            ],
            "invalid-missing-blocks.yaml": [
                ("1:1", "capabilities", "required field is missing"),
                ("1:1", "quality_gate", "required field is missing"),
                ("3:1", "qualitygate", "unknown field"),
            ],
            "invalid-model.yaml": [
                (
                    "5:15",
                    "capabilities.model.provider",
                    "must be a lowercase slug like 'task-planner', got 'Open Router'",
                ),
                (
                    "6:9",
                    "capabilities.model.id",
                    "must start with a letter or digit and contain no spaces, got 'claude sonnet'",
                ),
                (
                    "7:18",
                    "capabilities.model.temperature",
                    "input should be less than or equal to 2",
                ),
                ("8:12", "capabilities.model.top_p", "input should be a valid number"),
                (
                    "9:17",
                    "capabilities.model.max_tokens",
                    "input should be greater than or equal to 1",
                ),
                ("10:5", "capabilities.model.seed", "unknown field"),
            ],
            "invalid-name.yaml": [
                ("1:7", "name", "must be a lowercase slug like 'task-planner', got 'Task_Planner'")
            ],
            "invalid-not-a-mapping.yaml": [("1:1", "", "must be a mapping of fields")],
            "invalid-quality-gate.yaml": [
                ("7:18", "quality_gate.min_pass_rate", "input should be less than or equal to 1"),
                ("8:12", "quality_gate.repeats", "input should be greater than or equal to 1"),
            ],
            "invalid-routing-provider.yaml": [
                (
                    "7:14",
                    "capabilities.model.routing",
                    "routing is only supported for provider 'openrouter'",
                )
            ],
            "invalid-routing.yaml": [
                (
                    "7:34",
                    "capabilities.model.routing.only[1]",
                    "duplicate entry 'anthropic' (same as item 0)",
                ),
                (
                    "7:63",
                    "capabilities.model.routing.allow_fallbacks",
                    "input should be a valid boolean",
                ),
            ],
            "invalid-toolkit.yaml": [
                (
                    "5:29",
                    "capabilities.tools[2]",
                    "must be a tool name like 'github.create_pull_request', got 'Run Shell'",
                ),
                ("7:14", "capabilities.permissions.network", "input should be a valid boolean"),
                (
                    "8:29",
                    "capabilities.permissions.secrets[1]",
                    "must be an environment variable name like 'GITHUB_TOKEN', got 'github_token'",
                ),
                ("9:5", "capabilities.permissions.paths", "unknown field"),
            ],
        }
    )


@pytest.mark.usefixtures("in_fixtures")
def test_invalid_factories_report_every_problem() -> None:
    results = {
        file.name: _errors(load_factory_file, file)
        for file in sorted(Path("factories").glob("invalid-*.yaml"))
    }

    assert results == snapshot(
        {
            "invalid-duplicate-ids.yaml": [
                ("8:9", "stages[2].id", "duplicate stage id 'build' (first used by stages[0])"),
                ("10:9", "stages[3].id", "duplicate stage id 'test' (first used by stages[1])"),
            ],
            "invalid-empty.yaml": [
                ("3:9", "stages", "must list at least one item"),
                ("5:12", "outcome.scorers", "must list at least one item"),
            ],
            "invalid-return-to.yaml": [
                (
                    "6:29",
                    "stages[0].on_reject.return_to",
                    "must name an earlier stage, but 'review' comes later (stages[1])",
                ),
                ("9:29", "stages[1].on_reject.return_to", "a stage cannot return work to itself"),
                (
                    "9:53",
                    "stages[1].on_reject.max_iterations",
                    "input should be greater than or equal to 1",
                ),
                ("9:62", "stages[1].on_reject.then", "input should be 'escalate'"),
                (
                    "12:29",
                    "stages[2].on_reject.return_to",
                    "'deploy' is not a stage in this factory",
                ),
            ],
            "invalid-scorers.yaml": [
                (
                    "8:7",
                    "outcome.scorers[0]",
                    "must be a dotted reference like 'contracts.TaskList', got 'tests_pass'",
                ),
                (
                    "11:32",
                    "outcome.scorers[3].human_review.scale",
                    "must be a rating scale like '1-5', lowest first, got '5-1'",
                ),
                ("12:9", "outcome.scorers[4].human_review.scale", "required field is missing"),
                (
                    "13:7",
                    "outcome.scorers[5]",
                    "must be a dotted reference or a 'human_review' mapping",
                ),
            ],
            "invalid-stage-kind.yaml": [
                (
                    "4:5",
                    "stages[0]",
                    "must set exactly one of 'agent', 'operation' or 'human_gate'",
                ),
                (
                    "7:5",
                    "stages[1]",
                    "must set exactly one of 'agent', 'operation' or 'human_gate'",
                ),
                (
                    "8:5",
                    "stages[2]",
                    "must set exactly one of 'agent', 'operation' or 'human_gate'",
                ),
                ("10:17", "stages[3].human_gate", "input should be True"),
                (
                    "11:9",
                    "stages[4].id",
                    "must be a lowercase slug like 'task-planner', got 'Bad_Id'",
                ),
                (
                    "12:12",
                    "stages[4].agent",
                    "must be a lowercase slug like 'task-planner', got 'Implementer'",
                ),
                ("13:5", "stages[4].colour", "unknown field"),
            ],
            "invalid-trigger-events.yaml": [
                (
                    "3:18",
                    "trigger.events[1]",
                    "must start with a letter or digit and contain no spaces, got 'two words'",
                )
            ],
            "invalid-trigger.yaml": [
                ("3:3", "trigger", "set 'manual: true' or list 'events' so the factory can start")
            ],
        }
    )
