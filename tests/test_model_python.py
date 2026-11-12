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


def test_operation_parameters_are_held_as_tuples() -> None:
    data = {"id": "test", "operation": "run-tests", "with": {"command": ["pytest", "-q"]}}

    stage = OperationStage.model_validate(data)

    assert stage.with_ == {"command": ("pytest", "-q")}
    assert stage == OperationStage(id="test", operation="run-tests", with_=stage.with_)


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"x": object()}, "must be a string, number, boolean, null, list or mapping, got 'object'"),
        ({("a", "b"): 1}, "must be a parameter name like 'timeout_seconds', got a tuple"),
        ("text", "must be a mapping of parameters, got 'text'"),
    ],
)
def test_operation_parameters_must_be_json_values(parameters: object, message: str) -> None:
    with pytest.raises(ValidationError) as caught:
        OperationStage.model_validate({"id": "test", "operation": "run", "with": parameters})

    assert [error["msg"] for error in caught.value.errors()] == [message]


def test_parameters_are_only_allowed_on_operation_stages() -> None:
    with pytest.raises(ValidationError, match="'with' is only allowed on operation stages"):
        AgentStage.model_validate({"id": "work", "agent": "worker", "with": {}})


def test_factory_has_a_serialization_schema_with_parameters() -> None:
    stage = Factory.model_json_schema(mode="serialization")["$defs"]["OperationStage"]

    assert stage["properties"]["with"]["additionalProperties"] is False
    assert stage["properties"]["with"]["default"] == {}


def test_operation_parameters_serialize_as_json() -> None:
    data = {"id": "test", "operation": "run", "with": {"command": ["pytest", "-q"]}}

    stage = OperationStage.model_validate(data)

    assert stage.model_dump(mode="json") == {**data, "on_reject": None}
