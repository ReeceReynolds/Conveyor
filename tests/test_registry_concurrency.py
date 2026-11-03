"""Publishing one agent from several processes at once, as several terminals or CI jobs would.

Each test starts its publishers in separate processes (spawned, so nothing is shared but the
project folder) and releases them together from a barrier, so their publishes overlap.
"""

import multiprocessing
from datetime import UTC, datetime
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path
from typing import NamedTuple

from conveyor.registry import publish, snapshot_working_copy
from conveyor.storage import Store

AGENT = "implementer"
PUBLISHERS = 6
# Generous: every publisher must first start an interpreter and import Conveyor.
TIMEOUT_SECONDS = 120


class Outcome(NamedTuple):
    """What one publisher saw, in plain values that cross a process boundary."""

    created: bool
    sequence: int
    parent_sequence: int | None
    diff_from: str | None


def _publish_together(project: Path, barrier: Barrier, outcomes: Queue[Outcome | str]) -> None:
    """Wait for every publisher, then publish; report the outcome, or the error, on the queue."""
    try:
        # Warm up first (imports, contract resolution), so the publishes start together.
        snapshot_working_copy(project, AGENT)
        barrier.wait(TIMEOUT_SECONDS)
        result = publish(project, AGENT, author="ada", message="concurrent", now=datetime.now(UTC))
        outcomes.put(
            Outcome(
                created=result.created,
                sequence=result.record.sequence,
                parent_sequence=result.record.parent_sequence,
                diff_from=None if result.diff is None else result.diff.old_label,
            )
        )
    # A traceback in a child process would be lost; the parent fails on any error string.
    except Exception as error:  # noqa: BLE001 -- report every failure back to the parent
        outcomes.put(f"{type(error).__name__}: {error}")


def _publish_concurrently(project: Path) -> list[Outcome]:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(PUBLISHERS)
    outcomes: Queue[Outcome | str] = context.Queue()
    processes = [
        context.Process(target=_publish_together, args=(project, barrier, outcomes))
        for _ in range(PUBLISHERS)
    ]
    for process in processes:
        process.start()
    results = [outcomes.get(timeout=TIMEOUT_SECONDS) for _ in processes]
    for process in processes:
        process.join(TIMEOUT_SECONDS)
    errors = [result for result in results if isinstance(result, str)]
    assert errors == []
    return sorted(result for result in results if not isinstance(result, str))


def _history(project: Path) -> list[tuple[int, str]]:
    with Store.open(project) as store:
        return [(record.sequence, record.content_id) for record in store.registry.history(AGENT)]


def test_concurrent_first_publishes_record_one_version(example_project: Path) -> None:
    outcomes = _publish_concurrently(example_project)

    unchanged = Outcome(created=False, sequence=1, parent_sequence=None, diff_from=None)
    created = Outcome(created=True, sequence=1, parent_sequence=None, diff_from=None)
    assert outcomes == [unchanged] * (PUBLISHERS - 1) + [created]
    assert [sequence for sequence, _ in _history(example_project)] == [1]


def test_concurrent_publishes_of_an_edit_record_one_version_diffed_from_its_parent(
    example_project: Path,
) -> None:
    publish(example_project, AGENT, author="ada", message="initial", now=datetime.now(UTC))
    file = example_project / "agents" / AGENT / "agent.yaml"
    file.write_text(file.read_text().replace("anthropic/claude-sonnet", "openai/gpt-5"))

    outcomes = _publish_concurrently(example_project)

    unchanged = Outcome(created=False, sequence=2, parent_sequence=1, diff_from=None)
    created = Outcome(created=True, sequence=2, parent_sequence=1, diff_from="v1")
    assert outcomes == [unchanged] * (PUBLISHERS - 1) + [created]
    history = _history(example_project)
    assert [sequence for sequence, _ in history] == [2, 1]
    assert history[0][1] != history[1][1]
