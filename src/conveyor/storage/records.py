"""Frozen value types for runs, as they cross the storage package's boundary.

Each record mirrors rows of the run tables in `conveyor.storage.schema` (ADRs 0016 to 0022),
without exposing them: repositories turn rows into these records and back. The `StrEnum`s are
the single source of the status and kind values; the schema builds its check constraints from
them, and a test checks that the migrations hold exactly the same values.

Records hold no database code and are compared by value.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from conveyor.storage.objects import DIGEST_PATTERN

NAME_MAX_LENGTH: Final = 255
"""The longest name (factory, stage, agent, contract, queue) the run tables store."""

RUN_ID_PATTERN: Final = r"[0-9a-f]{12}7[0-9a-f]{3}[89ab][0-9a-f]{15}"
"""A run ID: a UUIDv7 as 32 lowercase hex characters, so IDs sort by creation time."""

COMMIT_PATTERN: Final = r"[0-9a-f]{40}(?:[0-9a-f]{24})?"
"""A Git object name: SHA-1 (40 hex characters) or SHA-256 (64)."""

NANODOLLARS_PER_DOLLAR: Final = 10**9
"""Costs are stored as whole billionths of a US dollar, so sums are exact on every backend.

An attempt's cost is the exact sum of its calls' costs in dollars, rounded half-even to a
nanodollar once, on the total (never per call).
"""


class RunStatus(StrEnum):
    """Where a run is in its life (ADR 0018)."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


FINISHED_RUN_STATUSES: Final = frozenset(
    {RunStatus.COMPLETED, RunStatus.REJECTED, RunStatus.FAILED}
)
"""Run statuses that end a run; a run has a `finished_at` exactly when it has one of them."""


class StageKind(StrEnum):
    """What works a stage: an agent, a built-in operation or a person at a gate."""

    AGENT = "agent"
    OPERATION = "operation"
    GATE = "gate"


class AttemptStatus(StrEnum):
    """The status of one stage attempt (ADR 0018).

    Agent and operation attempts use `running`, `succeeded`, `rejected`, `failed` and
    `interrupted`; gate attempts use `waiting`, `approved` and `rejected`.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    WAITING = "waiting"
    APPROVED = "approved"


WORK_ATTEMPT_STATUSES: Final = (
    AttemptStatus.RUNNING,
    AttemptStatus.SUCCEEDED,
    AttemptStatus.REJECTED,
    AttemptStatus.FAILED,
    AttemptStatus.INTERRUPTED,
)
"""The statuses an agent or operation attempt can have, in ADR 0018's order."""

GATE_ATTEMPT_STATUSES: Final = (
    AttemptStatus.WAITING,
    AttemptStatus.APPROVED,
    AttemptStatus.REJECTED,
)
"""The statuses a gate attempt can have, in ADR 0018's order."""

UNFINISHED_ATTEMPT_STATUSES: Final = frozenset({AttemptStatus.RUNNING, AttemptStatus.WAITING})
"""Attempt statuses with no `finished_at`; every other status has one."""

OUTPUT_ATTEMPT_STATUSES: Final = frozenset({AttemptStatus.SUCCEEDED, AttemptStatus.REJECTED})
"""Statuses with which an agent or operation attempt must have an output artifact."""


class CostSource(StrEnum):
    """Where an attempt's cost figure came from (ADR 0022)."""

    PROVIDER = "provider"
    """The provider's billed figure, such as OpenRouter's reported cost."""
    CALCULATED = "calculated"
    """Calculated from token counts with `genai-prices`."""
    MIXED = "mixed"
    """Some of the attempt's calls had a billed figure and the others a calculated one."""


class DecisionKind(StrEnum):
    """What a person decided on: a human gate, or a rework loop that ran out (ADR 0016)."""

    GATE = "gate"
    ESCALATION = "escalation"


class Decision(StrEnum):
    """A person's decision at a gate or on an escalated run."""

    APPROVE = "approve"
    REJECT = "reject"


class SpanKind(StrEnum):
    """An OpenTelemetry span kind, in lower case."""

    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanStatusCode(StrEnum):
    """An OpenTelemetry span status code, in lower case."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


type Timestamp = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""A timezone-aware datetime, normalised to UTC."""

type Digest = Annotated[str, StringConstraints(pattern=rf"^{DIGEST_PATTERN}$")]
"""A sha256 digest: 64 lowercase hexadecimal characters."""

type RunId = Annotated[str, StringConstraints(pattern=rf"^{RUN_ID_PATTERN}$")]
"""A run ID; see `RUN_ID_PATTERN`."""

type Commit = Annotated[str, StringConstraints(pattern=rf"^{COMMIT_PATTERN}$")]
"""A full Git commit SHA."""

type Name = Annotated[str, StringConstraints(min_length=1, max_length=NAME_MAX_LENGTH)]
"""A factory, stage, agent, contract or queue name."""

type Count = Annotated[int, Field(ge=0)]
"""A count that cannot be negative, such as a number of tokens."""

type Attributes = dict[str, JsonValue]
"""Span or event attributes, as JSON values."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunOptions(_Record):
    """How a run was started, as `conveyor run show` displays it."""

    repo_path: str | None = Field(
        default=None, min_length=1, description="The target repository, as given to `--repo`."
    )
    sandbox_image: str | None = Field(
        default=None, min_length=1, description="The sandbox image; `None` for the default."
    )
    max_stage_requests: int | None = Field(
        default=None, ge=1, description="Most model requests one stage attempt may make."
    )
    max_run_tokens: int | None = Field(
        default=None, ge=1, description="Most tokens the whole run may use."
    )


class RunRecord(_Record):
    """One execution of a factory on one input (ADR 0016).

    `traceparent` is `None` only before the run's first span is created. The exported bundle
    is written to `.conveyor/runs/<run id>/<branch slug>.bundle`, where the branch slug is
    `branch` with every `/` replaced by `-`.
    """

    id: RunId = Field(description="The run ID, also the run's DBOS workflow ID.")
    factory: Name = Field(description="The factory's name.")
    factory_digest: Digest = Field(description="Object store digest of the factory file.")
    input_digest: Digest = Field(description="Object store digest of the run's input file.")
    status: RunStatus = Field(description="Where the run is in its life.")
    application_version: Name = Field(
        description="The DBOS application version the run's workflow was started under."
    )
    queue_name: Name = Field(description="The run's own DBOS queue, used to resume it.")
    traceparent: (
        Annotated[str, StringConstraints(pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")]
        | None
    ) = Field(
        default=None,
        description="W3C trace context of the run's trace, so later processes continue it.",
    )
    options: RunOptions = Field(default_factory=RunOptions, description="How the run was started.")
    repo_bundle_digest: Digest | None = Field(
        default=None,
        description=(
            "sha256 of the Git bundle the workspace was cloned from, kept to verify the clone;"
            " the bundle is not in the object store."
        ),
    )
    base_commit: Commit | None = Field(
        default=None, description="The repository commit the run's workspace started from."
    )
    branch: Name | None = Field(default=None, description="The branch the run's work is on.")
    export_digest: Digest | None = Field(
        default=None,
        description="sha256 of `.conveyor/runs/<run id>/<branch slug>.bundle`, the export.",
    )
    head_commit: Commit | None = Field(
        default=None, description="The last commit of the run's branch, as exported."
    )
    error: str | None = Field(default=None, description="Why the run failed, if it did.")
    created_at: Timestamp = Field(description="When the run was created.")
    updated_at: Timestamp = Field(description="When the run's row last changed.")
    finished_at: Timestamp | None = Field(
        default=None, description="When the run reached a finished status."
    )

    @model_validator(mode="after")
    def _finished_when_finished(self) -> Self:
        if (self.status in FINISHED_RUN_STATUSES) != (self.finished_at is not None):
            msg = "finished_at must be set exactly when the run has finished"
            raise ValueError(msg)
        return self


class PinRecord(_Record):
    """The published agent version a run uses for every stage of that agent (ADR 0017)."""

    run_id: RunId = Field(description="The run that holds the pin.")
    agent: Name = Field(description="The agent's name.")
    sequence: int = Field(ge=1, description="The pinned version's sequence (`v1`, `v2`, ...).")
    content_id: Digest = Field(description="The pinned version's content ID.")


class ArtifactRef(_Record):
    """A reference to an artifact: its content and the contract it was validated against."""

    digest: Digest = Field(description="Object store digest of the canonical JSON.")
    contract: Name = Field(
        description="The contract identity: the dotted reference as written, or a built-in name."
    )


class ArtifactRecord(ArtifactRef):
    """A stored artifact: the typed, immutable output of a stage attempt (ADR 0016).

    An artifact is identified by its digest and contract together, so identical output from
    two attempts is one artifact; each attempt links to it as its output.
    """

    size: int = Field(ge=1, description="Size of the canonical JSON in bytes.")
    created_at: Timestamp = Field(description="When the artifact was first stored.")


class ReworkRecord(_Record):
    """Why an attempt is rework: which stage rejected and with what verdict (ADR 0016)."""

    stage: Name = Field(description="The stage whose rejection sent the work back.")
    verdict: ArtifactRef = Field(description="The rejecting stage's verdict artifact.")


class CostRecord(_Record):
    """What an attempt cost, and where the figure came from (ADR 0022).

    The amount is the attempt's total, rounded half-even to a nanodollar; the source is
    `mixed` when some calls were billed and others calculated.
    """

    nanodollars: Count = Field(description="The cost in billionths of a US dollar.")
    source: CostSource = Field(description="Where the figures of the attempt's calls came from.")

    @property
    def dollars(self) -> Decimal:
        """The cost in US dollars, exactly."""
        return Decimal(self.nanodollars) / NANODOLLARS_PER_DOLLAR


class StageAttemptRecord(_Record):
    """One execution of one stage in a run (ADRs 0016, 0018, 0021, 0022).

    `(run_id, stage, attempt)` identifies an attempt; writing it again is a no-op. `seq`
    orders a run's attempts, and routing uses it, never timestamps.
    """

    run_id: RunId = Field(description="The run the attempt belongs to.")
    stage: Name = Field(description="The stage's id in the factory file.")
    attempt: int = Field(ge=1, description="Which execution of the stage in the run, from 1.")
    seq: int = Field(
        ge=1, description="Position among all the run's attempts, from 1, in start order."
    )
    iteration: Count = Field(
        description="How many times work had been returned when this attempt ran; 0 at first."
    )
    kind: StageKind = Field(description="What works the stage.")
    status: AttemptStatus = Field(description="The attempt's status, valid for its kind.")
    input: ArtifactRef | None = Field(
        default=None, description="The primary input artifact, if the stage has one."
    )
    context: tuple[ArtifactRef, ...] = Field(
        default=(), description="Read-only context artifacts, in the order they were passed."
    )
    rework: ReworkRecord | None = Field(
        default=None, description="Why the work came back, on a rework attempt."
    )
    output: ArtifactRef | None = Field(default=None, description="The artifact it produced.")
    base_commit: Commit | None = Field(
        default=None, description="The workspace commit the attempt started from."
    )
    head_commit: Commit | None = Field(
        default=None, description="The workspace commit the attempt ended on."
    )
    requests: Count = Field(default=0, description="Model requests made.")
    input_tokens: Count = Field(default=0, description="Model input tokens used.")
    output_tokens: Count = Field(default=0, description="Model output tokens used.")
    cache_read_tokens: Count = Field(default=0, description="Input tokens read from a cache.")
    cache_write_tokens: Count = Field(default=0, description="Input tokens written to a cache.")
    cost: CostRecord | None = Field(default=None, description="What the attempt cost, if known.")
    error: str | None = Field(default=None, description="A short summary of why it failed.")
    started_at: Timestamp = Field(description="When the attempt started.")
    finished_at: Timestamp | None = Field(default=None, description="When the attempt ended.")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        allowed = GATE_ATTEMPT_STATUSES if self.kind is StageKind.GATE else WORK_ATTEMPT_STATUSES
        if self.status not in allowed:
            msg = f"a {self.kind} attempt cannot be {self.status}"
            raise ValueError(msg)
        if (self.status in UNFINISHED_ATTEMPT_STATUSES) == (self.finished_at is not None):
            msg = "finished_at must be set exactly when the attempt has finished"
            raise ValueError(msg)
        if self.finished_at is not None and self.finished_at < self.started_at:
            msg = "an attempt cannot finish before it starts"
            raise ValueError(msg)
        if self.kind is StageKind.GATE and (self.rework is not None or self.has_usage):
            msg = "a gate attempt has no usage, cost or rework"
            raise ValueError(msg)
        if self.rework is not None and self.iteration == 0:
            msg = "a rework attempt must have an iteration of at least 1"
            raise ValueError(msg)
        if (
            self.kind is not StageKind.GATE
            and self.status in OUTPUT_ATTEMPT_STATUSES
            and self.output is None
        ):
            msg = f"a {self.status} {self.kind} attempt must have an output"
            raise ValueError(msg)
        return self

    @property
    def has_usage(self) -> bool:
        """Whether the attempt made any model request, used any token or has a cost."""
        counts = (
            self.requests,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
        )
        return any(counts) or self.cost is not None


class RunDecisionRecord(_Record):
    """A person's decision at a gate or on an escalated run, kept apart from attempts.

    Approving an escalation leaves the rejected attempt `rejected`; the override is this
    record (ADR 0016). `(run_id, stage, attempt)` names the attempt decided on, and a run
    has at most one decision per attempt.
    """

    run_id: RunId = Field(description="The run decided on.")
    stage: Name = Field(description="The gate stage, or the stage that escalated.")
    attempt: int = Field(
        ge=1, description="The waiting gate attempt, or the rejected attempt that escalated."
    )
    kind: DecisionKind = Field(description="Whether a gate or an escalation was decided.")
    decision: Decision = Field(description="Approve or reject.")
    note: str | None = Field(default=None, description="The person's reason, if they gave one.")
    author: str = Field(min_length=1, description="Who decided.")
    decided_at: Timestamp = Field(description="When they decided.")


class SpanEventRecord(_Record):
    """An event recorded on a span, such as an exception."""

    name: str = Field(description="The event's name.")
    time: Timestamp = Field(description="When the event happened.")
    attributes: Attributes = Field(default_factory=dict, description="The event's attributes.")


class SpanRecord(_Record):
    """A finished OpenTelemetry span of a run (ADR 0022)."""

    run_id: RunId = Field(description="The run the span belongs to.")
    stage: Name | None = Field(
        default=None, description="The stage of the attempt the span belongs to, if any."
    )
    attempt: int | None = Field(
        default=None, ge=1, description="The attempt the span belongs to, if any."
    )
    trace_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")] = Field(
        description="The trace ID, as 32 lowercase hex characters."
    )
    span_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")] = Field(
        description="The span ID, as 16 lowercase hex characters."
    )
    parent_span_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")] | None = Field(
        default=None, description="The parent span's ID; `None` for a root span."
    )
    name: str = Field(min_length=1, description="The span's name.")
    kind: SpanKind = Field(description="The span kind.")
    start_time: Timestamp = Field(description="When the span started.")
    end_time: Timestamp = Field(description="When the span ended.")
    status_code: SpanStatusCode = Field(description="The span's status code.")
    status_message: str | None = Field(default=None, description="The status description.")
    attributes: Attributes = Field(default_factory=dict, description="The span's attributes.")
    events: tuple[SpanEventRecord, ...] = Field(default=(), description="The span's events.")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.stage is None) != (self.attempt is None):
            msg = "stage and attempt must be given together"
            raise ValueError(msg)
        if self.end_time < self.start_time:
            msg = "a span cannot end before it starts"
            raise ValueError(msg)
        return self
