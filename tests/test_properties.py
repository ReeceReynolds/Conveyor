"""Property tests: stage-graph rules and model -> YAML -> model round trips."""

import re
from pathlib import Path, PurePosixPath

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from conveyor.model import (
    Agent,
    AgentStage,
    Brief,
    Capabilities,
    Factory,
    HumanGateStage,
    HumanReview,
    HumanReviewScorer,
    ModelProfile,
    OnReject,
    OperationStage,
    Outcome,
    Permissions,
    QualityGate,
    Routing,
    Stage,
    Trigger,
    dump_yaml,
)
from conveyor.model.factory import StageLink, raw_stage_graph_violations, stage_graph_violations
from conveyor.model.loader import parse_yaml, validate_document
from conveyor.model.types import (
    DOTTED_REF_PATTERN,
    ENV_VAR_PATTERN,
    NO_SPACE_PATTERN,
    SLUG_PATTERN,
    TOOL_NAME_PATTERN,
)

FILE = Path("generated.yaml")

# Built from parts rather than `from_regex`, which makes nested factories too slow to shrink.
# The `matches_pattern` test below keeps these in step with the real patterns.
_words = st.text("abcxyz0129", min_size=1, max_size=4)
slugs = st.lists(_words, min_size=1, max_size=3).map("-".join)
_identifiers = st.tuples(st.sampled_from("abcXYZ_"), st.text("abcXYZ019_", max_size=4)).map("".join)
dotted_refs = st.lists(_identifiers, min_size=2, max_size=3).map(".".join)
env_vars = st.from_regex(ENV_VAR_PATTERN, fullmatch=True)
tool_names = st.from_regex(TOOL_NAME_PATTERN, fullmatch=True)
# A letter or digit, then any printable non-space text, including characters YAML must quote.
no_space = (
    st.tuples(
        st.sampled_from("aZ09"),
        st.text(st.characters(exclude_categories=("Cc", "Cs", "Z")), max_size=10),
    )
    .map("".join)
    .filter(lambda text: re.fullmatch(NO_SPACE_PATTERN, text) is not None)
)
relative_paths = st.lists(
    st.from_regex(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,8}", fullmatch=True).filter(
        lambda part: part not in {".", ".."}
    ),
    min_size=1,
    max_size=3,
).map(lambda parts: PurePosixPath(*parts))


def _unique[T](
    elements: st.SearchStrategy[T], max_size: int = 3
) -> st.SearchStrategy[tuple[T, ...]]:
    return st.lists(elements, unique=True, max_size=max_size).map(tuple)


def _maybe[T](elements: st.SearchStrategy[T]) -> st.SearchStrategy[T | None]:
    return st.none() | elements


@st.composite
def model_profiles(draw: st.DrawFn) -> ModelProfile:
    provider = draw(st.sampled_from(["openrouter", "anthropic", "openai"]) | slugs)
    routing = st.builds(
        Routing, only=_maybe(_unique(slugs, max_size=2)), allow_fallbacks=st.booleans()
    )
    return ModelProfile(
        provider=provider,
        id=draw(no_space),
        temperature=draw(_maybe(st.floats(0, 2))),
        top_p=draw(_maybe(st.floats(0, 1))),
        max_tokens=draw(_maybe(st.integers(1, 1_000_000))),
        routing=draw(_maybe(routing)) if provider == "openrouter" else None,
    )


agents = st.builds(
    Agent,
    name=slugs,
    brief=st.builds(Brief, instructions=relative_paths, input=dotted_refs, output=dotted_refs),
    capabilities=st.builds(
        Capabilities,
        model=model_profiles(),
        tools=_unique(tool_names),
        permissions=st.builds(Permissions, network=st.booleans(), secrets=_unique(env_vars)),
    ),
    quality_gate=st.builds(
        QualityGate,
        suite=relative_paths,
        min_pass_rate=st.floats(0, 1),
        repeats=st.integers(1, 100),
    ),
)


@st.composite
def factories(draw: st.DrawFn) -> Factory:
    ids = draw(st.lists(slugs, unique=True, min_size=1, max_size=6))
    stages: list[Stage] = []
    for index, stage_id in enumerate(ids):
        on_reject = None
        if index and draw(st.booleans()):
            target = draw(st.sampled_from(ids[:index]))
            on_reject = OnReject(return_to=target, max_iterations=draw(st.integers(1, 10)))
        kind = draw(st.sampled_from(["agent", "operation", "human_gate"]))
        if kind == "agent":
            stages.append(AgentStage(id=stage_id, agent=draw(slugs), on_reject=on_reject))
        elif kind == "operation":
            stages.append(OperationStage(id=stage_id, operation=draw(slugs), on_reject=on_reject))
        else:
            stages.append(HumanGateStage(id=stage_id, human_gate=True, on_reject=on_reject))
    scales = st.tuples(st.integers(0, 9), st.integers(1, 10)).filter(lambda b: b[0] < b[1])
    human = st.builds(
        HumanReviewScorer,
        human_review=st.builds(
            HumanReview, scale=scales.map(lambda b: f"{b[0]}-{b[1]}"), optional=st.booleans()
        ),
    )
    manual = draw(st.booleans())
    events = draw(st.lists(no_space, unique=True, min_size=0 if manual else 1, max_size=2))
    trigger = Trigger(manual=manual, events=tuple(events))
    scorers = draw(st.lists(dotted_refs | human, min_size=1, max_size=3, unique=True))
    return Factory(
        name=draw(slugs),
        trigger=trigger,
        stages=tuple(stages),
        outcome=Outcome(scorers=tuple(scorers)),
    )


@pytest.mark.parametrize(
    ("strategy", "pattern"), [(slugs, SLUG_PATTERN), (dotted_refs, DOTTED_REF_PATTERN)]
)
@given(data=st.data())
def test_strategies_match_pattern(
    strategy: st.SearchStrategy[str], pattern: str, data: st.DataObject
) -> None:
    assert re.fullmatch(pattern, data.draw(strategy))


@given(agents)
def test_agent_survives_yaml_round_trip(agent: Agent) -> None:
    assert validate_document(parse_yaml(dump_yaml(agent), FILE), Agent) == agent


@given(factories())
def test_factory_survives_yaml_round_trip(factory: Factory) -> None:
    assert validate_document(parse_yaml(dump_yaml(factory), FILE), Factory) == factory


# Stage graphs over a tiny id alphabet, so duplicates and dangling targets are common.
ids = st.sampled_from(["a", "b", "c", "d"])
graphs = st.lists(st.tuples(ids, st.none() | ids | st.just("zz")), min_size=1, max_size=6)


def _expected_problems(graph: list[tuple[str, str | None]]) -> set[tuple[str | int, ...]]:
    first: dict[str, int] = {}
    problems: set[tuple[str | int, ...]] = set()
    for index, (stage_id, _) in enumerate(graph):
        if stage_id in first:
            problems.add(("stages", index, "id"))
        first.setdefault(stage_id, index)
    for index, (_, target) in enumerate(graph):
        if target is not None and not first.get(target, index) < index:
            problems.add(("stages", index, "on_reject", "return_to"))
    return problems


def _factory_data(graph: list[tuple[str, str | None]]) -> dict[str, object]:
    stages: list[dict[str, object]] = []
    for stage_id, target in graph:
        stage: dict[str, object] = {"id": stage_id, "operation": "work"}
        if target is not None:
            stage["on_reject"] = {"return_to": target, "max_iterations": 1}
        stages.append(stage)
    return {
        "name": "graph",
        "trigger": {"manual": True},
        "stages": stages,
        "outcome": {"scorers": ["scorers.done"]},
    }


@given(graphs)
def test_factory_accepts_exactly_the_valid_stage_graphs(
    graph: list[tuple[str, str | None]],
) -> None:
    expected = _expected_problems(graph)
    data = _factory_data(graph)

    if expected:
        with pytest.raises(ValidationError) as caught:
            Factory.model_validate(data)
        assert {error["loc"] for error in caught.value.errors()} == expected
    else:
        assert len(Factory.model_validate(data).stages) == len(graph)


@given(graphs)
def test_raw_graph_check_agrees_with_the_model(graph: list[tuple[str, str | None]]) -> None:
    links = [StageLink(stage_id, target) for stage_id, target in graph]

    raw = raw_stage_graph_violations(_factory_data(graph))

    assert [v.loc for v in raw] == [("stages", *v.loc) for v in stage_graph_violations(links)]
    assert {v.loc for v in raw} == _expected_problems(graph)
