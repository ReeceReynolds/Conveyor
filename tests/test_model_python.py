"""The models used directly from Python: immutability and the same rules as YAML."""

from pathlib import PurePosixPath

import pytest
from pydantic import ValidationError

from conveyor.model import (
    AgentStage,
    Factory,
    HumanReview,
    HumanReviewScorer,
    OperationStage,
    Outcome,
    QualityGate,
    Trigger,
)
from conveyor.model.factory import raw_agent_references, raw_stage_graph_violations

OUTCOME = Outcome(scorers=("scorers.done",))


def test_models_are_frozen_and_hashable() -> None:
    gate = QualityGate(suite=PurePosixPath("evals"), min_pass_rate=0.5)

    with pytest.raises(ValidationError, match="frozen"):
        gate.repeats = 2
    assert hash(gate) == hash(QualityGate(suite=PurePosixPath("evals"), min_pass_rate=0.5))


def test_stage_instances_are_accepted_and_kept() -> None:
    stages = (AgentStage(id="work", agent="worker"), OperationStage(id="test", operation="run"))

    factory = Factory(name="f", trigger=Trigger(manual=True), stages=stages, outcome=OUTCOME)

    assert factory.stages == stages


def test_graph_rules_apply_to_python_construction() -> None:
    stages = (OperationStage(id="same", operation="a"), OperationStage(id="same", operation="b"))

    with pytest.raises(ValidationError, match="duplicate stage id 'same'"):
        Factory(name="f", trigger=Trigger(manual=True), stages=stages, outcome=OUTCOME)


def test_duplicate_scorer_mappings_are_rejected_without_a_long_repr() -> None:
    review = HumanReviewScorer(human_review=HumanReview(scale="1-5"))

    with pytest.raises(ValidationError) as caught:
        Outcome(scorers=(review, review))

    assert [error["msg"] for error in caught.value.errors()] == ["duplicate entry (same as item 0)"]


@pytest.mark.parametrize(
    "suite", ["..\\evals", "evals\\..\\..\\x", "\\evals", "C:evals", "C:\\evals"]
)
def test_relative_paths_cannot_escape_on_windows(suite: str) -> None:
    with pytest.raises(ValidationError, match="must be a relative path inside the folder"):
        QualityGate(suite=PurePosixPath(suite), min_pass_rate=0.5)


@pytest.mark.parametrize("value", ["5-5", "x-y", "1-"])
def test_rating_scale_needs_ascending_bounds(value: str) -> None:
    with pytest.raises(ValidationError, match="must be a rating scale"):
        HumanReview(scale=value)


@pytest.mark.parametrize("data", [None, {"stages": "no"}, {"stages": [1, {"id": 2}]}])
def test_raw_graph_check_ignores_unreadable_data(data: object) -> None:
    assert raw_stage_graph_violations(data) == []


def test_raw_agent_references_skip_unreadable_stages() -> None:
    data = {"stages": [{"agent": "good"}, {"agent": "Bad Name"}, "text", {"operation": "x"}]}

    assert raw_agent_references(data) == [(0, "good")]
    assert raw_agent_references({"stages": "no"}) == []
