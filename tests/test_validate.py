"""Filesystem rules and path discovery, using the project fixtures and the reference factory."""

from pathlib import Path

import pytest
from inline_snapshot import snapshot

from conveyor.model import NothingToValidateError, validate_path
from conveyor.model.checks import (
    agent_project_root,
    check_agent_folder,
    check_factory_file,
    project_root,
)
from conveyor.model.errors import Issue, format_loc


def _triples(issues: tuple[Issue, ...] | list[Issue]) -> list[tuple[str, str, str]]:
    """Each issue as (file:line:column, field path, message), for readable snapshots."""
    return [
        (
            ":".join(
                str(part) for part in (issue.file, issue.line, issue.column) if part is not None
            ),
            format_loc(issue.loc),
            issue.message,
        )
        for issue in issues
    ]


def test_reference_factory_is_valid(example: Path) -> None:
    report = validate_path(example)

    assert report.ok, [issue.render() for issue in report.issues]
    assert sorted(folder.name for folder in report.agents) == [
        "code-reviewer",
        "implementer",
        "requirements-analyst",
        "task-planner",
    ]
    assert [file.name for file in report.factories] == ["prd-to-pr.yaml"]


@pytest.mark.usefixtures("in_fixtures")
def test_project_reports_every_folder_problem_once() -> None:
    report = validate_path(Path("projects/layout"))

    assert not report.ok
    # `good` is referenced twice and also listed under agents/, yet validated once.
    assert sorted(folder.name for folder in report.agents) == [
        "broken",
        "good",
        "misnamed",
        "no-agent-yaml",
        "no-evals",
        "no-prompt",
    ]
    assert _triples(report.issues) == snapshot(
        [
            (
                "projects/layout/agents/broken/agent.yaml:1:1",
                "capabilities",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:1:1",
                "quality_gate",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:2:1",
                "brief.input",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:2:1",
                "brief.instructions",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:2:1",
                "brief.output",
                "required field is missing",
            ),
            (
                "projects/layout/agents/misnamed/agent.yaml:1:7",
                "name",
                "must match the folder name 'misnamed'",
            ),
            ("projects/layout/agents/no-agent-yaml", "", "not an agent folder: no agent.yaml"),
            (
                "projects/layout/agents/no-evals/agent.yaml:5:24",
                "quality_gate.suite",
                "eval suite 'evals' not found",
            ),
            (
                "projects/layout/agents/no-prompt/agent.yaml:2:24",
                "brief.instructions",
                "file 'prompt.md' not found",
            ),
            (
                "projects/layout/factories/pipeline.yaml:9:12",
                "stages[2].agent",
                "agent not found: no folder projects/layout/agents/ghost",
            ),
        ]
    )


@pytest.mark.usefixtures("in_fixtures")
@pytest.mark.parametrize(
    "path",
    [
        "projects/layout/agents/good",
        "projects/layout/agents/good/agent.yaml",
        "projects/flat/factory.yaml",
        "projects/flat",
        "projects/agents-only",
        "factories/valid-minimal.yaml",
    ],
)
def test_valid_paths_of_every_kind(path: str) -> None:
    report = validate_path(Path(path))

    assert report.ok, [issue.render() for issue in report.issues]


@pytest.mark.usefixtures("in_fixtures")
def test_flat_project_validates_its_factory_and_agents() -> None:
    report = validate_path(Path("projects/flat"))

    # No factories/ folder: only agents/ is discovered; the flat factory file is validated
    # when passed directly.
    assert [folder.name for folder in report.agents] == ["solo"]
    assert report.factories == ()


@pytest.mark.usefixtures("in_fixtures")
@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("projects/layout/factories/notes.txt", "is not a YAML file"),
        ("projects", "has no agent.yaml, factories/ or agents/ to validate"),
        ("does-not-exist", "does not exist"),
    ],
)
def test_nothing_to_validate(path: str, message: str) -> None:
    with pytest.raises(NothingToValidateError, match=message):
        validate_path(Path(path))


def test_project_root(tmp_path: Path) -> None:
    assert project_root(tmp_path / "factories" / "f.yaml") == tmp_path
    assert project_root(tmp_path / "f.yaml") == tmp_path


@pytest.mark.usefixtures("in_fixtures")
def test_factory_check_defaults_to_checking_each_reference() -> None:
    issues = check_factory_file(Path("projects/layout/factories/pipeline.yaml"))

    # Without de-duplication, an agent referenced twice is reported twice.
    assert [issue.message for issue in issues].count("must match the folder name 'misnamed'") == 1
    assert len(issues) == 2


@pytest.mark.usefixtures("in_fixtures")
def test_agent_folder_check_reports_invalid_config() -> None:
    issues = check_agent_folder(Path("projects/layout/agents/broken"))

    assert _triples(issues) == snapshot(
        [
            (
                "projects/layout/agents/broken/agent.yaml:1:1",
                "capabilities",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:1:1",
                "quality_gate",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:2:1",
                "brief.input",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:2:1",
                "brief.instructions",
                "required field is missing",
            ),
            (
                "projects/layout/agents/broken/agent.yaml:2:1",
                "brief.output",
                "required field is missing",
            ),
        ]
    )


@pytest.mark.usefixtures("in_fixtures")
def test_project_reports_unresolvable_contracts_on_their_lines() -> None:
    report = validate_path(Path("projects/contracts"))

    assert sorted(folder.name for folder in report.agents) == [
        "broken",
        "missing",
        "no-schema",
        "resolves",
        "too-wide",
    ]
    # `broken` also has a config problem; every problem is still reported in one pass.
    assert _triples(report.issues) == snapshot(
        [
            (
                "projects/contracts/agents/broken/agent.yaml:4:10",
                "brief.input",
                "cannot resolve contract 'contracts.broken.Anything': importing "
                "'contracts.broken' raised RuntimeError: database not configured",
            ),
            (
                "projects/contracts/agents/broken/agent.yaml:5:11",
                "brief.output",
                "cannot resolve contract 'contracts.NotAModel': 'NotAModel' is a class but "
                "not a Pydantic model (it must subclass BaseModel)",
            ),
            (
                "projects/contracts/agents/broken/agent.yaml:8:46",
                "quality_gate.min_pass_rate",
                "input should be less than or equal to 1",
            ),
            (
                "projects/contracts/agents/missing/agent.yaml:4:10",
                "brief.input",
                "cannot resolve contract 'schemas.Request': no module 'schemas' in the project "
                "(expected schemas.py or a schemas/ package)",
            ),
            (
                "projects/contracts/agents/missing/agent.yaml:5:11",
                "brief.output",
                "cannot resolve contract 'contracts.Absent': module 'contracts' has no "
                "attribute 'Absent'",
            ),
            (
                "projects/contracts/agents/no-schema/agent.yaml:2:42",
                "brief.input",
                "cannot resolve contract 'contracts.hooks.Hook': no JSON Schema can be "
                "generated for it: PydanticInvalidForJsonSchema: Cannot generate a JsonSchema "
                "for core_schema.CallableSchema",
            ),
            (
                "projects/contracts/agents/no-schema/agent.yaml:2:72",
                "brief.output",
                "cannot resolve contract 'contracts.value': 'value' is not a class but a "
                "value of type 'int'",
            ),
            (
                "projects/contracts/agents/too-wide/agent.yaml:2:42",
                "brief.input",
                "cannot resolve contract 'contracts.wide.Counter': its JSON Schema has a value "
                "JSON cannot carry exactly: integer 9223372036854775807 exceeds 2**53 - 1 at "
                "/properties/count/maximum",
            ),
        ]
    )


@pytest.mark.parametrize(
    ("brief", "resolved"),
    [
        # A malformed reference is reported by the model, so only `output` is resolved.
        ("{ instructions: prompt.md, input: TaskList, output: contracts.Absent }", ["output"]),
        ("[not, a, mapping]", []),
    ],
)
def test_invalid_agent_resolves_only_well_formed_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, brief: str, resolved: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    folder = Path("agents/a")
    folder.mkdir(parents=True)
    Path("contracts.py").write_text("")
    (folder / "agent.yaml").write_text(f"name: a\nbrief: {brief}\n")

    issues = check_agent_folder(folder)

    assert [
        issue.loc[1] for issue in issues if issue.message.startswith("cannot resolve contract")
    ] == resolved


@pytest.mark.usefixtures("in_fixtures")
def test_standalone_agent_skips_contract_resolution() -> None:
    # Its references name modules that exist nowhere, but there is no project to look in.
    report = validate_path(Path("standalone/loner"))

    assert report.ok, [issue.render() for issue in report.issues]


def test_agent_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "a").mkdir(parents=True)
    (tmp_path / "loose" / "b").mkdir(parents=True)

    assert agent_project_root(Path("agents/a")) == tmp_path.resolve()
    assert agent_project_root(Path("agents/a/../a")) == tmp_path.resolve()
    assert agent_project_root(Path("loose/b")) is None


def test_factory_check_reports_unparseable_files(tmp_path: Path) -> None:
    factory = tmp_path / "factory.yaml"
    factory.write_text("stages: [\n")

    issues = check_factory_file(factory)

    assert [(issue.line, issue.column) for issue in issues] == [(2, 1)]


def test_agent_check_reports_unparseable_files(tmp_path: Path) -> None:
    folder = tmp_path / "agents" / "a"
    folder.mkdir(parents=True)
    (folder / "agent.yaml").write_text("brief: {\n")

    issues = check_agent_folder(folder)

    assert [(issue.line, issue.column) for issue in issues] == [(2, 1)]
