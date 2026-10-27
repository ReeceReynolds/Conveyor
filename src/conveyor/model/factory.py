"""The factory level of the factory model: agents, operations and human gates in order.

These models describe a factory file. Structural rules that span stages (unique ids, rework
loops that point backwards) are enforced here, so a `Factory` instance is always a valid graph.
Whether referenced agents exist on disk is checked by `conveyor.model.checks`.
"""

from collections.abc import Sequence
from typing import Annotated, Literal, NamedTuple, Self

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    Tag,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from conveyor.model.base import ConfigModel, RuleViolation, raise_violations
from conveyor.model.types import (
    NON_EMPTY,
    UNIQUE,
    DottedRef,
    RatingScale,
    Slug,
    StrictBool,
    StrictInt,
    Token,
)


class Trigger(ConfigModel):
    """What starts the factory. At least one start must be enabled."""

    manual: StrictBool = Field(default=False, description="Whether a person can start a run.")
    events: Annotated[tuple[Token, ...], UNIQUE] = Field(
        default=(),
        description="External events that start a run.",
        examples=[["github.issue.labelled:ready-for-build"]],
    )

    @model_validator(mode="after")
    def _has_a_start(self) -> Self:
        if not self.manual and not self.events:
            raise PydanticCustomError(
                "no_trigger",
                "set 'manual: true' or list 'events' so the factory can start",
            )
        return self


class OnReject(ConfigModel):
    """A bounded rework loop: where rejected work goes and when to stop retrying."""

    return_to: Slug = Field(description="Id of an earlier stage that receives the rejected work.")
    max_iterations: Annotated[StrictInt, Field(ge=1)] = Field(
        description="How many times work may be returned before the run escalates."
    )
    then: Literal["escalate"] = Field(
        default="escalate", description="What happens when the iterations run out."
    )


class _StageBase(ConfigModel):
    id: Slug = Field(description="Unique id of the stage within the factory.")
    on_reject: OnReject | None = Field(
        default=None, description="Rework loop taken when this stage rejects its input."
    )


class AgentStage(_StageBase):
    """A stage worked by an agent."""

    agent: Slug = Field(description="Name of the agent, resolved to the folder agents/<name>/.")


class OperationStage(_StageBase):
    """A deterministic step, such as fetching a file or running tests."""

    operation: Slug = Field(description="Name of the operation to run.")


class HumanGateStage(_StageBase):
    """A stage where a person approves or rejects the work."""

    human_gate: Literal[True] = Field(description="Marks the stage as a human gate.")


_STAGE_KINDS = {"agent": "agent_stage", "operation": "operation_stage", "human_gate": "gate_stage"}


def _stage_tag(value: object) -> str | None:
    match value:
        case AgentStage():
            return "agent_stage"
        case OperationStage():
            return "operation_stage"
        case HumanGateStage():
            return "gate_stage"
        case dict():
            tags = [tag for key, tag in _STAGE_KINDS.items() if key in value]
            return tags[0] if len(tags) == 1 else None
        case _:
            return None


Stage = Annotated[
    Annotated[AgentStage, Tag("agent_stage")]
    | Annotated[OperationStage, Tag("operation_stage")]
    | Annotated[HumanGateStage, Tag("gate_stage")],
    Discriminator(
        _stage_tag,
        custom_error_type="stage_kind",
        custom_error_message="must set exactly one of 'agent', 'operation' or 'human_gate'",
    ),
]
"""One position in the factory: exactly one of an agent, an operation or a human gate."""


class HumanReview(ConfigModel):
    """A score given by a person reviewing the run's output."""

    scale: RatingScale = Field(description="Inclusive rating scale, such as '1-5'.")
    optional: StrictBool = Field(
        default=False, description="Whether a run can be complete without this score."
    )


class HumanReviewScorer(ConfigModel):
    """An outcome scorer that asks a person for a rating."""

    human_review: HumanReview = Field(description="How the person rates the outcome.")


def _scorer_tag(value: object) -> str | None:
    match value:
        case str():
            return "scorer_ref"
        case HumanReviewScorer() | dict():
            return "human_review_scorer"
        case _:
            return None


Scorer = Annotated[
    Annotated[DottedRef, Tag("scorer_ref")]
    | Annotated[HumanReviewScorer, Tag("human_review_scorer")],
    Discriminator(
        _scorer_tag,
        custom_error_type="scorer_kind",
        custom_error_message="must be a dotted reference or a 'human_review' mapping",
    ),
]
"""An outcome scorer: a dotted reference to scoring code, or a human review."""

UNION_TAGS = frozenset({*_STAGE_KINDS.values(), "scorer_ref", "human_review_scorer"})
"""Tags pydantic inserts into error locations for the unions above; not part of the YAML."""


class Outcome(ConfigModel):
    """How the factory owner scores what a run produced."""

    scorers: Annotated[tuple[Scorer, ...], NON_EMPTY, UNIQUE] = Field(
        description="Outcome scorers, applied to every run."
    )


class StageLink(NamedTuple):
    """The parts of a stage that the stage-graph rules look at.

    Attributes:
        id: The stage id.
        return_to: The rework target, if the stage has a rework loop.
    """

    id: str
    return_to: str | None


def stage_graph_violations(links: Sequence[StageLink | None]) -> list[RuleViolation]:
    """Check the rules that span stages.

    Stage ids must be unique, and a rework loop's `return_to` must name a stage that comes
    strictly earlier, so every loop goes backwards and the graph stays a bounded line.

    Args:
        links: Each stage's id and rework target, in order; `None` for a stage too malformed
            to read, which is skipped but keeps its index.

    Returns:
        Every violation found, with locations relative to the list of stages.
    """
    violations: list[RuleViolation] = []
    first_index: dict[str, int] = {}
    for index, link in enumerate(links):
        if link is None:
            continue
        if link.id in first_index:
            message = (
                f"duplicate stage id {link.id!r} (first used by stages[{first_index[link.id]}])"
            )
            violations.append(RuleViolation((index, "id"), "duplicate", message, link.id))
        else:
            first_index[link.id] = index

    for index, link in enumerate(links):
        if link is None or link.return_to is None:
            continue
        target = link.return_to
        target_index = first_index.get(target)
        if target_index is None:
            message = f"{target!r} is not a stage in this factory"
        elif target_index == index:
            message = "a stage cannot return work to itself"
        elif target_index > index:
            message = (
                f"must name an earlier stage, but {target!r} comes later (stages[{target_index}])"
            )
        else:
            continue
        loc = (index, "on_reject", "return_to")
        violations.append(RuleViolation(loc, "return_to", message, target))
    return violations


def _link(stage: Stage) -> StageLink:
    return StageLink(stage.id, stage.on_reject.return_to if stage.on_reject else None)


class _LooseOnReject(BaseModel):
    return_to: str


class _LooseStage(BaseModel):
    id: str
    on_reject: object = None


class _LooseFactory(BaseModel):
    stages: list[object]


class _LooseAgentStage(BaseModel):
    agent: Slug


def _loose_link(raw: object) -> StageLink | None:
    try:
        stage = _LooseStage.model_validate(raw)
    except ValidationError:
        return None
    try:
        return_to = _LooseOnReject.model_validate(stage.on_reject).return_to
    except ValidationError:
        return_to = None
    return StageLink(stage.id, return_to)


def raw_stage_graph_violations(data: object) -> list[RuleViolation]:
    """Check the stage-graph rules on unvalidated factory data, as far as it can be read.

    Pydantic only runs the graph rules once every stage is valid. When a factory fails
    validation, this finds the graph problems the person would otherwise discover only after
    fixing everything else.

    Args:
        data: The factory as plain data, typically parsed YAML.

    Returns:
        Violations with locations relative to the factory.
    """
    try:
        stages = _LooseFactory.model_validate(data).stages
    except ValidationError:
        return []
    return [
        violation._replace(loc=("stages", *violation.loc))
        for violation in stage_graph_violations([_loose_link(raw) for raw in stages])
    ]


def agent_references(stages: Sequence[Stage]) -> list[tuple[int, str]]:
    """List the agent each agent stage uses.

    Args:
        stages: The factory's stages, in order.

    Returns:
        (stage index, agent name) pairs.
    """
    return [(i, stage.agent) for i, stage in enumerate(stages) if isinstance(stage, AgentStage)]


def raw_agent_references(data: object) -> list[tuple[int, str]]:
    """List the agents an unvalidated factory references, as far as it can be read.

    Lets agent folders be checked even when the factory itself has problems.

    Args:
        data: The factory as plain data, typically parsed YAML.

    Returns:
        (stage index, agent name) pairs for every stage with a valid agent name.
    """
    try:
        stages = _LooseFactory.model_validate(data).stages
    except ValidationError:
        return []
    references: list[tuple[int, str]] = []
    for index, raw in enumerate(stages):
        try:
            references.append((index, _LooseAgentStage.model_validate(raw).agent))
        except ValidationError:
            continue
    return references


class Factory(ConfigModel):
    """An ordered process of stages with triggers, rework loops and an outcome definition."""

    name: Slug = Field(description="The factory's name.", examples=["prd-to-pr"])
    trigger: Trigger = Field(description="What starts a run.")
    stages: Annotated[tuple[Stage, ...], NON_EMPTY] = Field(description="The stages, in order.")
    outcome: Outcome = Field(description="How each run's output is scored.")

    # A field validator rather than a model validator, so graph problems are reported even
    # when another field (say `outcome`) is also invalid.
    @field_validator("stages")
    @classmethod
    def _valid_stage_graph(cls, stages: tuple[Stage, ...]) -> tuple[Stage, ...]:
        violations = stage_graph_violations([_link(stage) for stage in stages])
        if violations:
            raise_violations("stages", violations)
        return stages
