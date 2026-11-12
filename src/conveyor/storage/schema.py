"""The relational schema, as typed SQLAlchemy 2.0 declarative models.

These models are the source of truth for the schema; the Alembic migrations in `migrations/`
must produce exactly the same tables, which a test checks. Rows are internal to the storage
package: callers receive Pydantic records instead (`conveyor.storage.records` for runs).

Two groups of tables:

- the agent registry: `agents` and `agent_versions` (ADR 0013);
- runs (ADRs 0016 to 0022): `runs`, `run_pins`, `stage_attempts`, `stage_attempt_context`,
  `artifacts`, `run_decisions` and `spans`. Rows are immutable records of what happened, so
  most tables use natural keys (a run ID, `(run, stage, attempt)`, `(digest, contract)`,
  `(trace, span)`), which make replayed writes no-ops and let rows refer to each other
  without looking up surrogate IDs. Status and kind columns are checked against the
  `StrEnum`s in `conveyor.storage.records`.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import override

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from conveyor.storage.records import (
    FINISHED_RUN_STATUSES,
    GATE_ATTEMPT_STATUSES,
    NAME_MAX_LENGTH,
    OUTPUT_ATTEMPT_STATUSES,
    UNFINISHED_ATTEMPT_STATUSES,
    WORK_ATTEMPT_STATUSES,
    AttemptStatus,
    CostSource,
    Decision,
    DecisionKind,
    RunStatus,
    SpanKind,
    SpanStatusCode,
    StageKind,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Deterministic constraint names, so migrations can refer to them on every backend."""

DIGEST_LENGTH = 64
NAME_LENGTH = NAME_MAX_LENGTH
RUN_ID_LENGTH = 32
"""A run ID is a UUIDv7 as 32 hex characters (`conveyor.storage.records.RUN_ID_PATTERN`)."""
COMMIT_LENGTH = 64
"""Room for a SHA-256 Git object name; SHA-1 names are 40 characters."""
TRACE_ID_LENGTH = 32
SPAN_ID_LENGTH = 16
TRACEPARENT_LENGTH = 55


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware UTC datetime, stored as a naive UTC timestamp.

    SQLite has no timezone-aware type, and Postgres `timestamptz` converts on read, so storing
    naive UTC is the portable choice. Naive datetimes are rejected rather than guessed at.
    """

    impl = DateTime(timezone=False)
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Convert an aware datetime to naive UTC for storage.

        Args:
            value: The datetime to store.
            dialect: The database dialect (unused).

        Returns:
            The same instant as a naive UTC datetime.

        Raises:
            ValueError: If `value` is naive.
        """
        del dialect
        if value is None:
            return None
        if value.utcoffset() is None:
            msg = f"refusing to store a naive datetime: {value.isoformat()}"
            raise ValueError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Mark a stored naive UTC timestamp as UTC.

        Args:
            value: The stored timestamp.
            dialect: The database dialect (unused).

        Returns:
            The timestamp as an aware UTC datetime.
        """
        del dialect
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """Declarative base whose metadata uses the naming convention above."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class AgentRow(Base):
    """An agent that has at least one published version."""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(NAME_LENGTH), unique=True)


class AgentVersionRow(Base):
    """One immutable version of an agent.

    `(agent_id, sequence)` is unique; `content_id` is not, because reverting to earlier content
    creates a new sequence with an old content id. The parent link is a foreign key into this
    table, so it always names an existing version of the same agent.
    """

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "sequence"),
        ForeignKeyConstraint(
            ["agent_id", "parent_sequence"],
            ["agent_versions.agent_id", "agent_versions.sequence"],
            name="fk_agent_versions_parent",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            # Spelled out so a NULL parent never makes the check unknown (which would pass).
            "(parent_sequence IS NULL AND sequence = 1)"
            " OR (parent_sequence IS NOT NULL AND parent_sequence = sequence - 1)",
            name="parent_is_previous",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    sequence: Mapped[int] = mapped_column()
    content_id: Mapped[str] = mapped_column(String(DIGEST_LENGTH), index=True)
    parent_sequence: Mapped[int | None] = mapped_column()
    author: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    snapshot_digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH))


# --- Runs (ADRs 0016 to 0022) ----------------------------------------------------------------

KIND_LENGTH = 16
"""Room for any status or kind value in `conveyor.storage.records`."""


def _one_of(column: str, values: Iterable[StrEnum]) -> str:
    """SQL that holds when `column` is one of `values`, listed in the order given."""
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


def _in_order[E: StrEnum](kind: type[E], subset: frozenset[E]) -> list[E]:
    """The members of `subset` in declaration order, so generated SQL is deterministic."""
    return [member for member in kind if member in subset]


def _together(*columns: str) -> str:
    """SQL that holds when the columns are all NULL or all set."""
    unset = " AND ".join(f"{column} IS NULL" for column in columns)
    present = " AND ".join(f"{column} IS NOT NULL" for column in columns)
    return f"({unset}) OR ({present})"


def _exactly_when(condition: str, consequence: str) -> str:
    """SQL that holds when `consequence` is true exactly when `condition` is.

    Neither may ever be unknown (NULL), or the check would pass whatever they say.
    """
    return f"(({condition}) AND ({consequence})) OR (NOT ({condition}) AND NOT ({consequence}))"


def _only(column: str, characters: str) -> str:
    """SQL that holds when `column` holds no character outside `characters`.

    Nested `replace` calls behave the same on SQLite and Postgres (both case-sensitive),
    unlike `GLOB` and regular expressions, which differ between them.
    """
    stripped = column
    for character in characters:
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({stripped}) = 0"


_WORK_KINDS = (StageKind.AGENT, StageKind.OPERATION)
_USAGE_COLUMNS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


class RunRow(Base):
    """One execution of a factory on one input, and how it was started.

    The ID is a UUIDv7 as 32 lowercase hex characters: unique without coordination, sortable
    by creation time, and the run's DBOS workflow ID. The factory file and input are stored
    by digest in the object store, so a run records exactly what it ran.

    - `traceparent` is the W3C trace context of the run's one trace (ADR 0022). It is NULL
      only before the run's first span is created.
    - `repo_path`, `sandbox_image`, `max_stage_requests` and `max_run_tokens` are the options
      the run was started with, as `conveyor run show` displays them; a NULL budget means no
      limit, and a NULL image means the default image.
    - `repo_bundle_digest` is the sha256 of the Git bundle the workspace was cloned from. It
      is kept to verify the clone only and is not in the object store: code lives in Git
      (ADR 0016).
    - The exported bundle is written to `.conveyor/runs/<run id>/<branch slug>.bundle`, where
      the branch slug is `branch` with every `/` replaced by `-`; `export_digest` is its
      sha256 and `head_commit` the branch's last commit in it (ADR 0021).
    """

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(f"length(id) = {RUN_ID_LENGTH}", name="id_length"),
        CheckConstraint(_only("id", "0123456789abcdef"), name="id_lowercase_hex"),
        CheckConstraint("max_stage_requests >= 1", name="max_stage_requests_positive"),
        CheckConstraint("max_run_tokens >= 1", name="max_run_tokens_positive"),
        CheckConstraint(_one_of("status", RunStatus), name="status_valid"),
        CheckConstraint(
            _exactly_when(
                _one_of("status", _in_order(RunStatus, FINISHED_RUN_STATUSES)),
                "finished_at IS NOT NULL",
            ),
            name="finished_when_done",
        ),
    )

    id: Mapped[str] = mapped_column(String(RUN_ID_LENGTH), primary_key=True)
    factory: Mapped[str] = mapped_column(String(NAME_LENGTH))
    factory_digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH))
    input_digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH))
    status: Mapped[str] = mapped_column(String(KIND_LENGTH))
    application_version: Mapped[str] = mapped_column(String(NAME_LENGTH))
    queue_name: Mapped[str] = mapped_column(String(NAME_LENGTH))
    traceparent: Mapped[str | None] = mapped_column(String(TRACEPARENT_LENGTH))
    repo_path: Mapped[str | None] = mapped_column(Text)
    sandbox_image: Mapped[str | None] = mapped_column(Text)
    max_stage_requests: Mapped[int | None] = mapped_column()
    max_run_tokens: Mapped[int | None] = mapped_column(BigInteger)
    repo_bundle_digest: Mapped[str | None] = mapped_column(String(DIGEST_LENGTH))
    base_commit: Mapped[str | None] = mapped_column(String(COMMIT_LENGTH))
    branch: Mapped[str | None] = mapped_column(String(NAME_LENGTH))
    export_digest: Mapped[str | None] = mapped_column(String(DIGEST_LENGTH))
    head_commit: Mapped[str | None] = mapped_column(String(COMMIT_LENGTH))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RunPinRow(Base):
    """The agent version a run uses, one per agent (ADR 0017).

    The foreign key into `agent_versions` means a pin always names a published version; its
    content ID is read from there. Which stages use the agent is in the factory file.
    """

    __tablename__ = "run_pins"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "agent_id"),
        ForeignKeyConstraint(
            ["agent_id", "sequence"],
            ["agent_versions.agent_id", "agent_versions.sequence"],
            name="fk_run_pins_agent_version",
        ),
    )

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    agent_id: Mapped[int] = mapped_column()
    sequence: Mapped[int] = mapped_column()


class ArtifactRow(Base):
    """A typed artifact: canonical JSON in the object store, validated against a contract.

    The same bytes under the same contract are one artifact, however many attempts produce
    them; attempts link to their output.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        PrimaryKeyConstraint("digest", "contract"),
        CheckConstraint("size >= 1", name="size_positive"),
    )

    digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH))
    contract: Mapped[str] = mapped_column(String(NAME_LENGTH))
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


def _artifact_link(role: str) -> ForeignKeyConstraint:
    """A foreign key from an attempt's `<role>_digest, <role>_contract` to an artifact."""
    return ForeignKeyConstraint(
        [f"{role}_digest", f"{role}_contract"],
        ["artifacts.digest", "artifacts.contract"],
        name=f"fk_stage_attempts_{role}",
    )


class StageAttemptRow(Base):
    """One execution of one stage of a run (ADRs 0016, 0018, 0021, 0022).

    Keyed by run, stage and attempt, so writing an attempt again is a no-op.

    - `seq` totally orders the attempts of a run, from 1. The repository assigns it inside
      the transaction that writes the attempt (one more than the run's highest), so it is
      the order the attempts started in. Routing by ADR 0016 ("the most recent artifact",
      "produced after the input") uses `seq`, never wall-clock time.
    - Artifacts are referred to by digest and contract; each pair is NULL or names a stored
      artifact. The context artifacts are rows of `stage_attempt_context`.
    - Usage is the sum over the attempt's model calls: `requests` and the input, output,
      cache-read and cache-write token counts. Gate attempts have none, and are never rework.
    - Cost is in whole nanodollars, exact on every backend (SQLite has no exact decimal
      type): the attempt's total in dollars, summed exactly and then rounded half-even to a
      nanodollar once. `cost_source` is `provider` or `calculated` when every call's figure
      came from that source, and `mixed` when they came from both.
    """

    __tablename__ = "stage_attempts"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "stage", "attempt"),
        UniqueConstraint("run_id", "seq"),
        _artifact_link("input"),
        _artifact_link("output"),
        _artifact_link("rework"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint("iteration >= 0", name="iteration_not_negative"),
        CheckConstraint(_one_of("kind", StageKind), name="kind_valid"),
        CheckConstraint(
            f"(kind = '{StageKind.GATE}' AND {_one_of('status', GATE_ATTEMPT_STATUSES)})"
            f" OR ({_one_of('kind', _WORK_KINDS)} AND {_one_of('status', WORK_ATTEMPT_STATUSES)})",
            name="status_valid",
        ),
        CheckConstraint(
            _exactly_when(
                _one_of("status", _in_order(AttemptStatus, UNFINISHED_ATTEMPT_STATUSES)),
                "finished_at IS NULL",
            ),
            name="finished_when_done",
        ),
        CheckConstraint("finished_at >= started_at", name="finished_after_start"),
        CheckConstraint(_together("input_digest", "input_contract"), name="input_complete"),
        CheckConstraint(_together("output_digest", "output_contract"), name="output_complete"),
        CheckConstraint(
            _together("rework_stage", "rework_digest", "rework_contract"),
            name="rework_complete",
        ),
        CheckConstraint("rework_stage IS NULL OR iteration >= 1", name="rework_after_first"),
        CheckConstraint(
            f"kind = '{StageKind.GATE}'"
            f" OR NOT ({_one_of('status', _in_order(AttemptStatus, OUTPUT_ATTEMPT_STATUSES))})"
            " OR output_digest IS NOT NULL",
            name="output_when_done",
        ),
        CheckConstraint(
            " AND ".join(f"{column} >= 0" for column in _USAGE_COLUMNS),
            name="usage_not_negative",
        ),
        CheckConstraint(_together("cost_nanodollars", "cost_source"), name="cost_complete"),
        CheckConstraint("cost_nanodollars >= 0", name="cost_not_negative"),
        CheckConstraint(_one_of("cost_source", CostSource), name="cost_source_valid"),
        CheckConstraint(
            f"kind <> '{StageKind.GATE}' OR ("
            + " AND ".join(f"{column} = 0" for column in _USAGE_COLUMNS)
            + " AND cost_nanodollars IS NULL)",
            name="gate_has_no_usage",
        ),
        CheckConstraint(
            f"kind <> '{StageKind.GATE}' OR rework_stage IS NULL", name="gate_is_not_rework"
        ),
    )

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    stage: Mapped[str] = mapped_column(String(NAME_LENGTH))
    attempt: Mapped[int] = mapped_column()
    seq: Mapped[int] = mapped_column()
    iteration: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(KIND_LENGTH))
    status: Mapped[str] = mapped_column(String(KIND_LENGTH))
    input_digest: Mapped[str | None] = mapped_column(String(DIGEST_LENGTH))
    input_contract: Mapped[str | None] = mapped_column(String(NAME_LENGTH))
    output_digest: Mapped[str | None] = mapped_column(String(DIGEST_LENGTH))
    output_contract: Mapped[str | None] = mapped_column(String(NAME_LENGTH))
    rework_stage: Mapped[str | None] = mapped_column(String(NAME_LENGTH))
    rework_digest: Mapped[str | None] = mapped_column(String(DIGEST_LENGTH))
    rework_contract: Mapped[str | None] = mapped_column(String(NAME_LENGTH))
    base_commit: Mapped[str | None] = mapped_column(String(COMMIT_LENGTH))
    head_commit: Mapped[str | None] = mapped_column(String(COMMIT_LENGTH))
    requests: Mapped[int] = mapped_column()
    input_tokens: Mapped[int] = mapped_column()
    output_tokens: Mapped[int] = mapped_column()
    cache_read_tokens: Mapped[int] = mapped_column()
    cache_write_tokens: Mapped[int] = mapped_column()
    cost_nanodollars: Mapped[int | None] = mapped_column(BigInteger)
    cost_source: Mapped[str | None] = mapped_column(String(KIND_LENGTH))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class StageAttemptContextRow(Base):
    """One context artifact passed to an attempt, at its position in the envelope.

    A join table rather than a JSON list, so every context artifact is a checked foreign key
    and "which attempts saw this artifact" is a query.
    """

    __tablename__ = "stage_attempt_context"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "stage", "attempt", "position"),
        ForeignKeyConstraint(
            ["run_id", "stage", "attempt"],
            ["stage_attempts.run_id", "stage_attempts.stage", "stage_attempts.attempt"],
            name="fk_stage_attempt_context_attempt",
        ),
        ForeignKeyConstraint(
            ["artifact_digest", "artifact_contract"],
            ["artifacts.digest", "artifacts.contract"],
            name="fk_stage_attempt_context_artifact",
        ),
        CheckConstraint("position >= 0", name="position_not_negative"),
    )

    run_id: Mapped[str] = mapped_column(String(RUN_ID_LENGTH))
    stage: Mapped[str] = mapped_column(String(NAME_LENGTH))
    attempt: Mapped[int] = mapped_column()
    position: Mapped[int] = mapped_column()
    artifact_digest: Mapped[str] = mapped_column(String(DIGEST_LENGTH))
    artifact_contract: Mapped[str] = mapped_column(String(NAME_LENGTH))


class RunDecisionRow(Base):
    """A person's decision at a gate or on an escalated run, kept apart from attempts.

    A decision belongs to one attempt: for a gate, the gate attempt that waits; for an
    escalation, the rejected attempt that escalated. Approving an escalation leaves that
    attempt `rejected`; this row records the override (ADR 0016). Keyed by the attempt, so
    a retried decision is a no-op for the repository and a second, different one is refused.
    """

    __tablename__ = "run_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "stage", "attempt"),
        ForeignKeyConstraint(
            ["run_id", "stage", "attempt"],
            ["stage_attempts.run_id", "stage_attempts.stage", "stage_attempts.attempt"],
            name="fk_run_decisions_attempt",
        ),
        CheckConstraint(_one_of("kind", DecisionKind), name="kind_valid"),
        CheckConstraint(_one_of("decision", Decision), name="decision_valid"),
    )

    run_id: Mapped[str] = mapped_column(String(RUN_ID_LENGTH))
    stage: Mapped[str] = mapped_column(String(NAME_LENGTH))
    attempt: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(KIND_LENGTH))
    decision: Mapped[str] = mapped_column(String(KIND_LENGTH))
    note: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SpanRow(Base):
    """A finished OpenTelemetry span of a run (ADR 0022).

    Keyed by trace and span ID, so storing a span again is a no-op. A span inside a stage
    attempt names it by `(run_id, stage, attempt)`; a run-level span leaves both NULL, and a
    foreign key with a NULL column is not checked. The attempt row must be written (as
    `running` or `waiting`) before any of its spans. Attributes and events are JSON text.
    """

    __tablename__ = "spans"
    __table_args__ = (
        PrimaryKeyConstraint("trace_id", "span_id"),
        ForeignKeyConstraint(
            ["run_id", "stage", "attempt"],
            ["stage_attempts.run_id", "stage_attempts.stage", "stage_attempts.attempt"],
            name="fk_spans_attempt",
        ),
        CheckConstraint(_one_of("kind", SpanKind), name="kind_valid"),
        CheckConstraint(_one_of("status_code", SpanStatusCode), name="status_code_valid"),
        CheckConstraint(_together("stage", "attempt"), name="attempt_complete"),
        CheckConstraint("end_time >= start_time", name="ends_after_start"),
    )

    trace_id: Mapped[str] = mapped_column(String(TRACE_ID_LENGTH))
    span_id: Mapped[str] = mapped_column(String(SPAN_ID_LENGTH))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    stage: Mapped[str | None] = mapped_column(String(NAME_LENGTH))
    attempt: Mapped[int | None] = mapped_column()
    parent_span_id: Mapped[str | None] = mapped_column(String(SPAN_ID_LENGTH))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(KIND_LENGTH))
    start_time: Mapped[datetime] = mapped_column(UTCDateTime)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime)
    status_code: Mapped[str] = mapped_column(String(KIND_LENGTH))
    status_message: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[str] = mapped_column(Text)
    events: Mapped[str] = mapped_column(Text)
