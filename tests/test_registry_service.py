"""The registry service: publishing agent folders, resolving refs and diffing versions."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import pytest
from inline_snapshot import snapshot

from conveyor.contracts import resolve_contract_schemas
from conveyor.model import Issue, load_agent_file
from conveyor.registry import (
    PublishError,
    PublishResult,
    RefProblem,
    SnapshotError,
    VersionRefError,
    WorkingCopy,
    build_snapshot,
    canonical_bytes,
    check_agent_name,
    content_id,
    diff_versions,
    load_snapshot,
    previous_version,
    publish,
    resolve,
    snapshot_working_copy,
)
from conveyor.registry import service as service_module
from conveyor.storage import STATE_DIR, AgentVersionRecord, Store

WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
AGENT = "implementer"
OLD_MODEL = "id: anthropic/claude-sonnet"
NEW_MODEL = "id: openai/gpt-5"


def _agent_file(project: Path, name: str = AGENT) -> Path:
    return project / "agents" / name / "agent.yaml"


def _switch_model(project: Path, old: str = OLD_MODEL, new: str = NEW_MODEL) -> None:
    file = _agent_file(project)
    text = file.read_text()
    assert old in text
    file.write_text(text.replace(old, new))


def _publish(project: Path, message: str = "change", *, minutes: int = 0) -> PublishResult:
    return publish(
        project, AGENT, author="ada", message=message, now=WHEN + timedelta(minutes=minutes)
    )


def _issues(error: PublishError, root: Path) -> list[str]:
    return [issue.render().replace(f"{root}/", "") for issue in error.issues]


# --- Publishing -------------------------------------------------------------------------------


def test_first_publish_records_version_one(example_project: Path) -> None:
    result = _publish(example_project, "initial")

    working = snapshot_working_copy(example_project, AGENT)
    assert result.created
    assert result.diff is None
    assert result.record == AgentVersionRecord(
        agent=AGENT,
        sequence=1,
        content_id=content_id(working),
        parent_sequence=None,
        author="ada",
        message="initial",
        created_at=WHEN,
        snapshot_digest=content_id(working),
    )
    with Store.open(example_project) as store:
        assert store.objects.get(result.record.snapshot_digest) == canonical_bytes(working)
        assert load_snapshot(store, result.record) == working


def test_the_working_copy_is_the_agent_folder_with_its_contracts(example_project: Path) -> None:
    folder = example_project / "agents" / AGENT
    agent = load_agent_file(folder / "agent.yaml")
    schemas = resolve_contract_schemas(example_project, [agent.brief.input, agent.brief.output])

    assert snapshot_working_copy(example_project, AGENT) == build_snapshot(folder, agent, schemas)


def test_publishing_unchanged_content_is_a_no_op(example_project: Path) -> None:
    first = _publish(example_project, "initial")

    again = _publish(example_project, "again", minutes=5)

    assert again == PublishResult(record=first.record, created=False, diff=None)
    with Store.open(example_project) as store:
        assert store.registry.history(AGENT) == (first.record,)


def test_publishing_a_change_records_the_next_version_and_its_diff(example_project: Path) -> None:
    first = _publish(example_project, "initial")
    _switch_model(example_project)

    second = _publish(example_project, "Switch to GPT-5", minutes=5)

    assert second.created
    assert (second.record.sequence, second.record.parent_sequence) == (2, 1)
    assert second.record.created_at == WHEN + timedelta(minutes=5)
    assert second.record.content_id != first.record.content_id
    assert second.diff is not None
    assert (second.diff.old_label, second.diff.new_label) == ("v1", "v2")
    assert second.diff.summary() == snapshot(
        "implementer v1 → v2: Capabilities changed; model profile changed; model switched"
        " (anthropic/claude-sonnet → openai/gpt-5)"
    )


def test_reverting_publishes_a_new_sequence_with_the_old_content(example_project: Path) -> None:
    first = _publish(example_project, "initial")
    _switch_model(example_project)
    _publish(example_project, "Switch to GPT-5", minutes=5)
    _switch_model(example_project, NEW_MODEL, OLD_MODEL)

    third = _publish(example_project, "Back to Claude", minutes=10)

    assert third.created
    assert (third.record.sequence, third.record.parent_sequence) == (3, 2)
    assert third.record.content_id == first.record.content_id
    assert third.diff is not None
    assert third.diff.summary().startswith("implementer v2 → v3: Capabilities changed;")
    with Store.open(example_project) as store:
        assert [record.sequence for record in store.registry.history(AGENT)] == [3, 2, 1]
        # A prefix of content shared by v1 and v3 names the newest of them.
        assert resolve(store, AGENT, first.record.content_id[:8]) == third.record


def test_publish_refuses_an_invalid_agent_and_stores_nothing(example_project: Path) -> None:
    file = _agent_file(example_project)
    file.write_text(file.read_text().replace("min_pass_rate: 0.9", "min_pass_rate: 2"))

    with pytest.raises(PublishError) as raised:
        _publish(example_project)

    assert raised.value.name == AGENT
    assert _issues(raised.value, example_project) == snapshot(
        [
            "agents/implementer/agent.yaml:20:18: quality_gate.min_pass_rate: input should be"
            " less than or equal to 1"
        ]
    )
    assert str(raised.value) == raised.value.issues[0].render()
    assert not (example_project / STATE_DIR).exists()


def test_publish_reports_a_missing_agent_folder(example_project: Path) -> None:
    with pytest.raises(PublishError) as raised:
        publish(example_project, "ghost", author="ada", message="m", now=WHEN)

    assert _issues(raised.value, example_project) == snapshot(
        ["agents/ghost: not an agent folder: no agent.yaml"]
    )


def test_files_that_cannot_be_snapshotted_are_reported_as_issues(example_project: Path) -> None:
    (example_project / "agents" / AGENT / "evals" / "case.bin").write_bytes(b"\xff\xfe")

    with pytest.raises(PublishError) as raised:
        snapshot_working_copy(example_project, AGENT)

    assert _issues(raised.value, example_project) == snapshot(
        ["agents/implementer/evals/case.bin: not UTF-8 text (invalid byte at offset 0)"]
    )


def _no_issues(_folder: Path) -> list[Issue]:
    return []


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (
            ("name: implementer", "name: [implementer]"),
            "agents/implementer/agent.yaml:2:7: name: input should be a valid string",
        ),
        (
            ("contracts.TaskList", "contracts.Missing"),
            "agents/implementer/agent.yaml: brief: cannot resolve contract 'contracts.Missing':"
            " module 'contracts' has no attribute 'Missing'",
        ),
    ],
)
def test_changes_after_validation_are_still_reported_as_issues(
    example_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    edit: tuple[str, str],
    expected: str,
) -> None:
    """Files can change between validating a folder and snapshotting it."""
    file = _agent_file(example_project)
    file.write_text(file.read_text().replace(*edit))
    monkeypatch.setattr(service_module, "check_agent_folder", _no_issues)

    with pytest.raises(PublishError) as raised:
        snapshot_working_copy(example_project, AGENT)

    assert _issues(raised.value, example_project) == [expected]


class _Arguments(NamedTuple):
    name: str = AGENT
    author: str = "ada"
    message: str = "m"
    now: datetime = WHEN


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        (_Arguments(message="  "), "a publish message is required"),
        (_Arguments(author=""), "a publish author is required"),
        (_Arguments(now=WHEN.replace(tzinfo=None)), "the publish time must be timezone-aware"),
        (_Arguments(name="../implementer"), "not an agent name: '../implementer'"),
    ],
)
def test_publish_rejects_bad_arguments(
    example_project: Path, arguments: _Arguments, error: str
) -> None:
    name, author, message, now = arguments

    with pytest.raises(ValueError, match=re.escape(error)):
        publish(example_project, name, author=author, message=message, now=now)
    assert not (example_project / STATE_DIR).exists()


@pytest.mark.parametrize("name", ["implementer", "a", "code-reviewer", "v2-agent"])
def test_agent_names_are_slugs(name: str) -> None:
    assert check_agent_name(name) == name


@pytest.mark.parametrize("name", ["", "Implementer", "a--b", "-a", "a/b", "..", "a b"])
def test_other_names_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="not an agent name"):
        check_agent_name(name)


# --- Resolving refs ---------------------------------------------------------------------------


@pytest.fixture
def two_versions(example_project: Path) -> tuple[AgentVersionRecord, AgentVersionRecord]:
    first = _publish(example_project, "initial").record
    _switch_model(example_project)
    second = _publish(example_project, "Switch to GPT-5", minutes=5).record
    return first, second


def test_resolve_by_latest_sequence_and_prefix(
    example_project: Path, two_versions: tuple[AgentVersionRecord, AgentVersionRecord]
) -> None:
    first, second = two_versions

    with Store.open(example_project) as store:
        assert resolve(store, AGENT, None) == second
        assert resolve(store, AGENT, "latest") == second
        assert resolve(store, AGENT, "v1") == first
        assert resolve(store, AGENT, "v2") == second
        assert resolve(store, AGENT, first.content_id[:4]) == first
        assert resolve(store, AGENT, first.content_id.upper()) == first
        assert previous_version(store, second) == first
        assert previous_version(store, first) is None


@pytest.mark.parametrize("ref", ["", "v", "v1.0", "V1", "abc", "head", "zzzz", "a" * 65, "v-1"])
def test_malformed_refs(example_project: Path, ref: str) -> None:
    with Store.open(example_project) as store, pytest.raises(VersionRefError) as raised:
        resolve(store, AGENT, ref)

    assert (raised.value.problem, raised.value.name, raised.value.ref) == (
        RefProblem.MALFORMED,
        AGENT,
        ref,
    )
    assert str(raised.value) == (
        f"not a version: {ref!r} (use latest, vN, or 4 to 64 hex characters of a content ID)"
    )


def test_refs_that_match_nothing(
    example_project: Path, two_versions: tuple[AgentVersionRecord, AgentVersionRecord]
) -> None:
    unused = next(
        prefix
        for prefix in ("0000", "1111", "2222")
        if not any(record.content_id.startswith(prefix) for record in two_versions)
    )
    with Store.open(example_project) as store:
        failures: list[tuple[RefProblem, str]] = []
        for name, ref in ((AGENT, "v3"), (AGENT, "v0"), (AGENT, unused), ("ghost", None)):
            with pytest.raises(VersionRefError) as raised:
                resolve(store, name, ref)
            failures.append((raised.value.problem, str(raised.value)))

    assert failures == [
        (RefProblem.NOT_FOUND, "agent 'implementer' has no version v3"),
        (RefProblem.NOT_FOUND, "agent 'implementer' has no version v0"),
        (RefProblem.NOT_FOUND, f"agent 'implementer' has no version with id prefix {unused!r}"),
        (RefProblem.NOT_FOUND, "agent 'ghost' has no published versions"),
    ]


def _record(store: Store, content: str) -> AgentVersionRecord:
    """Record a version whose content ID is chosen, not computed, to force a prefix clash."""
    return store.registry.add_version(
        agent=AGENT,
        content_id=content,
        author="ada",
        message="m",
        snapshot_digest=store.objects.put(content.encode()),
        created_at=WHEN,
    )


def test_an_ambiguous_prefix_lists_the_versions_it_matches(tmp_path: Path) -> None:
    first, second = "abcd" + "0" * 60, "abcd" + "1" * 60

    with Store.open(tmp_path) as store:
        _record(store, first)
        _record(store, second)
        assert resolve(store, AGENT, "abcd0").content_id == first
        with pytest.raises(VersionRefError) as raised:
            resolve(store, AGENT, "ABCD")

    assert raised.value.problem is RefProblem.AMBIGUOUS
    assert str(raised.value) == (
        f"prefix 'ABCD' matches several versions of 'implementer': {first}, {second}"
    )


def test_load_snapshot_checks_the_content_id(example_project: Path) -> None:
    record = _publish(example_project).record
    forged = record.model_copy(update={"content_id": "f" * 64})

    with Store.open(example_project) as store, pytest.raises(SnapshotError) as raised:
        load_snapshot(store, forged)

    assert str(raised.value) == (
        f"the stored snapshot of implementer v1 has content ID {record.content_id}, not {'f' * 64}"
    )


# --- Diffing ----------------------------------------------------------------------------------


def test_diff_between_stored_versions(
    example_project: Path, two_versions: tuple[AgentVersionRecord, AgentVersionRecord]
) -> None:
    first, second = two_versions

    with Store.open(example_project) as store:
        forward = diff_versions(store, AGENT, first, second)
        backward = diff_versions(store, AGENT, second, first)
        same = diff_versions(store, AGENT, second, second)

    assert forward.summary() == snapshot(
        "implementer v1 → v2: Capabilities changed; model profile changed; model switched"
        " (anthropic/claude-sonnet → openai/gpt-5)"
    )
    assert backward.summary().endswith("model switched (openai/gpt-5 → anthropic/claude-sonnet)")
    assert same.diff.empty
    assert same.render() == "implementer v2 → v2: no changes\n"


def test_diff_with_the_working_copy(example_project: Path) -> None:
    first = _publish(example_project, "initial").record
    working = WorkingCopy(example_project)
    prompt = example_project / "agents" / AGENT / "prompt.md"
    prompt.write_text(prompt.read_text() + "Keep every change small.\n")

    with Store.open(example_project) as store:
        ahead = diff_versions(store, AGENT, first, working)
        behind = diff_versions(store, AGENT, working, first)
        itself = diff_versions(store, AGENT, working, working)

    assert ahead.summary() == snapshot(
        "implementer v1 → working copy: Brief changed; instructions changed; instructions"
        " edited (+1 \N{MINUS SIGN}0 lines)"
    )
    assert behind.summary().startswith("implementer working copy → v1: Brief changed;")
    assert itself.diff.empty


def test_diff_with_an_invalid_working_copy_reports_its_issues(example_project: Path) -> None:
    first = _publish(example_project, "initial").record
    (example_project / "agents" / AGENT / "prompt.md").unlink()

    with Store.open(example_project) as store, pytest.raises(PublishError) as raised:
        diff_versions(store, AGENT, first, WorkingCopy(example_project))

    assert _issues(raised.value, example_project) == snapshot(
        ["agents/implementer/agent.yaml:5:17: brief.instructions: file 'prompt.md' not found"]
    )
