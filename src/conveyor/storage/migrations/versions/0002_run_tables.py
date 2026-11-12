"""Create the run tables: runs, pins, stage attempts, artifacts, decisions and spans.

Generated with Alembic autogenerate against a database at 0001, then tidied by hand. The
check constraints are written out as literals, not built from the record enums, so this
revision stays as it was applied even if the enums change; a test checks that they agree.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

# ruff: noqa: INP001 -- Alembic loads revision scripts by path; versions/ is not a package

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_FINISHED = "status IN ('completed', 'rejected', 'failed')"
_ATTEMPT_UNFINISHED = "status IN ('running', 'waiting')"
_USAGE = ("requests", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column[datetime]:
    """A naive UTC timestamp column, as `conveyor.storage.schema.UTCDateTime` stores it."""
    return sa.Column(name, sa.DateTime(timezone=False), nullable=nullable)


def _together(*columns: str) -> str:
    """SQL that holds when the columns are all NULL or all set."""
    unset = " AND ".join(f"{column} IS NULL" for column in columns)
    present = " AND ".join(f"{column} IS NOT NULL" for column in columns)
    return f"({unset}) OR ({present})"


def _only(column: str, characters: str) -> str:
    """SQL that holds when `column` holds no character outside `characters` (portable)."""
    stripped = column
    for character in characters:
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({stripped}) = 0"


def _artifact_link(table: str, role: str) -> sa.ForeignKeyConstraint:
    """A foreign key from `<role>_digest, <role>_contract` to an artifact."""
    return sa.ForeignKeyConstraint(
        [f"{role}_digest", f"{role}_contract"],
        ["artifacts.digest", "artifacts.contract"],
        name=op.f(f"fk_{table}_{role}"),
    )


def _attempt_link(table: str, name: str) -> sa.ForeignKeyConstraint:
    """A foreign key from `run_id, stage, attempt` to a stage attempt."""
    return sa.ForeignKeyConstraint(
        ["run_id", "stage", "attempt"],
        ["stage_attempts.run_id", "stage_attempts.stage", "stage_attempts.attempt"],
        name=op.f(f"fk_{table}_{name}"),
    )


def upgrade() -> None:
    """Create the run tables and their indexes."""
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("factory", sa.String(length=255), nullable=False),
        sa.Column("factory_digest", sa.String(length=64), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("application_version", sa.String(length=255), nullable=False),
        sa.Column("queue_name", sa.String(length=255), nullable=False),
        sa.Column("traceparent", sa.String(length=55), nullable=True),
        sa.Column("repo_path", sa.Text(), nullable=True),
        sa.Column("sandbox_image", sa.Text(), nullable=True),
        sa.Column("max_stage_requests", sa.Integer(), nullable=True),
        sa.Column("max_run_tokens", sa.BigInteger(), nullable=True),
        sa.Column("repo_bundle_digest", sa.String(length=64), nullable=True),
        sa.Column("base_commit", sa.String(length=64), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("export_digest", sa.String(length=64), nullable=True),
        sa.Column("head_commit", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("finished_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
        sa.CheckConstraint("length(id) = 32", name=op.f("ck_runs_id_length")),
        sa.CheckConstraint(_only("id", "0123456789abcdef"), name=op.f("ck_runs_id_lowercase_hex")),
        sa.CheckConstraint(
            "max_stage_requests >= 1", name=op.f("ck_runs_max_stage_requests_positive")
        ),
        sa.CheckConstraint("max_run_tokens >= 1", name=op.f("ck_runs_max_run_tokens_positive")),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'waiting', 'escalated', 'completed', 'rejected',"
            " 'failed')",
            name=op.f("ck_runs_status_valid"),
        ),
        sa.CheckConstraint(
            f"(({_RUN_FINISHED}) AND (finished_at IS NOT NULL))"
            f" OR (NOT ({_RUN_FINISHED}) AND NOT (finished_at IS NOT NULL))",
            name=op.f("ck_runs_finished_when_done"),
        ),
    )
    op.create_table(
        "run_pins",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "agent_id", name=op.f("pk_run_pins")),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_run_pins_run_id_runs")),
        sa.ForeignKeyConstraint(
            ["agent_id", "sequence"],
            ["agent_versions.agent_id", "agent_versions.sequence"],
            name=op.f("fk_run_pins_agent_version"),
        ),
    )
    op.create_table(
        "artifacts",
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("contract", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("digest", "contract", name=op.f("pk_artifacts")),
        sa.CheckConstraint("size >= 1", name=op.f("ck_artifacts_size_positive")),
    )
    op.create_table(
        "stage_attempts",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=255), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=True),
        sa.Column("input_contract", sa.String(length=255), nullable=True),
        sa.Column("output_digest", sa.String(length=64), nullable=True),
        sa.Column("output_contract", sa.String(length=255), nullable=True),
        sa.Column("rework_stage", sa.String(length=255), nullable=True),
        sa.Column("rework_digest", sa.String(length=64), nullable=True),
        sa.Column("rework_contract", sa.String(length=255), nullable=True),
        sa.Column("base_commit", sa.String(length=64), nullable=True),
        sa.Column("head_commit", sa.String(length=64), nullable=True),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_nanodollars", sa.BigInteger(), nullable=True),
        sa.Column("cost_source", sa.String(length=16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _timestamp("started_at"),
        _timestamp("finished_at", nullable=True),
        sa.PrimaryKeyConstraint("run_id", "stage", "attempt", name=op.f("pk_stage_attempts")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_stage_attempts_run_id_runs")
        ),
        sa.UniqueConstraint("run_id", "seq", name=op.f("uq_stage_attempts_run_id_seq")),
        _artifact_link("stage_attempts", "input"),
        _artifact_link("stage_attempts", "output"),
        _artifact_link("stage_attempts", "rework"),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_stage_attempts_seq_positive")),
        sa.CheckConstraint("attempt >= 1", name=op.f("ck_stage_attempts_attempt_positive")),
        sa.CheckConstraint("iteration >= 0", name=op.f("ck_stage_attempts_iteration_not_negative")),
        sa.CheckConstraint(
            "kind IN ('agent', 'operation', 'gate')", name=op.f("ck_stage_attempts_kind_valid")
        ),
        sa.CheckConstraint(
            "(kind = 'gate' AND status IN ('waiting', 'approved', 'rejected'))"
            " OR (kind IN ('agent', 'operation')"
            " AND status IN ('running', 'succeeded', 'rejected', 'failed', 'interrupted'))",
            name=op.f("ck_stage_attempts_status_valid"),
        ),
        sa.CheckConstraint(
            f"(({_ATTEMPT_UNFINISHED}) AND (finished_at IS NULL))"
            f" OR (NOT ({_ATTEMPT_UNFINISHED}) AND NOT (finished_at IS NULL))",
            name=op.f("ck_stage_attempts_finished_when_done"),
        ),
        sa.CheckConstraint(
            "finished_at >= started_at", name=op.f("ck_stage_attempts_finished_after_start")
        ),
        sa.CheckConstraint(
            _together("input_digest", "input_contract"),
            name=op.f("ck_stage_attempts_input_complete"),
        ),
        sa.CheckConstraint(
            _together("output_digest", "output_contract"),
            name=op.f("ck_stage_attempts_output_complete"),
        ),
        sa.CheckConstraint(
            _together("rework_stage", "rework_digest", "rework_contract"),
            name=op.f("ck_stage_attempts_rework_complete"),
        ),
        sa.CheckConstraint(
            "rework_stage IS NULL OR iteration >= 1",
            name=op.f("ck_stage_attempts_rework_after_first"),
        ),
        sa.CheckConstraint(
            "kind = 'gate' OR NOT (status IN ('succeeded', 'rejected'))"
            " OR output_digest IS NOT NULL",
            name=op.f("ck_stage_attempts_output_when_done"),
        ),
        sa.CheckConstraint(
            " AND ".join(f"{column} >= 0" for column in _USAGE),
            name=op.f("ck_stage_attempts_usage_not_negative"),
        ),
        sa.CheckConstraint(
            _together("cost_nanodollars", "cost_source"),
            name=op.f("ck_stage_attempts_cost_complete"),
        ),
        sa.CheckConstraint(
            "cost_nanodollars >= 0", name=op.f("ck_stage_attempts_cost_not_negative")
        ),
        sa.CheckConstraint(
            "cost_source IN ('provider', 'calculated', 'mixed')",
            name=op.f("ck_stage_attempts_cost_source_valid"),
        ),
        sa.CheckConstraint(
            "kind <> 'gate' OR ("
            + " AND ".join(f"{column} = 0" for column in _USAGE)
            + " AND cost_nanodollars IS NULL)",
            name=op.f("ck_stage_attempts_gate_has_no_usage"),
        ),
        sa.CheckConstraint(
            "kind <> 'gate' OR rework_stage IS NULL",
            name=op.f("ck_stage_attempts_gate_is_not_rework"),
        ),
    )
    op.create_table(
        "stage_attempt_context",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=255), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("artifact_contract", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint(
            "run_id", "stage", "attempt", "position", name=op.f("pk_stage_attempt_context")
        ),
        _attempt_link("stage_attempt_context", "attempt"),
        _artifact_link("stage_attempt_context", "artifact"),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_stage_attempt_context_position_not_negative")
        ),
    )
    op.create_table(
        "run_decisions",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=255), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        _timestamp("decided_at"),
        sa.PrimaryKeyConstraint("run_id", "stage", "attempt", name=op.f("pk_run_decisions")),
        _attempt_link("run_decisions", "attempt"),
        sa.CheckConstraint(
            "kind IN ('gate', 'escalation')", name=op.f("ck_run_decisions_kind_valid")
        ),
        sa.CheckConstraint(
            "decision IN ('approve', 'reject')", name=op.f("ck_run_decisions_decision_valid")
        ),
    )
    op.create_table(
        "spans",
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=255), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("parent_span_id", sa.String(length=16), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        _timestamp("start_time"),
        _timestamp("end_time"),
        sa.Column("status_code", sa.String(length=16), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("attributes", sa.Text(), nullable=False),
        sa.Column("events", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("trace_id", "span_id", name=op.f("pk_spans")),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_spans_run_id_runs")),
        _attempt_link("spans", "attempt"),
        sa.CheckConstraint(
            "kind IN ('internal', 'server', 'client', 'producer', 'consumer')",
            name=op.f("ck_spans_kind_valid"),
        ),
        sa.CheckConstraint(
            "status_code IN ('unset', 'ok', 'error')", name=op.f("ck_spans_status_code_valid")
        ),
        sa.CheckConstraint(_together("stage", "attempt"), name=op.f("ck_spans_attempt_complete")),
        sa.CheckConstraint("end_time >= start_time", name=op.f("ck_spans_ends_after_start")),
    )
    op.create_index(op.f("ix_spans_run_id"), "spans", ["run_id"], unique=False)


def downgrade() -> None:
    """Drop the run tables, leaving the registry as it was at 0001."""
    op.drop_index(op.f("ix_spans_run_id"), table_name="spans")
    op.drop_table("spans")
    op.drop_table("run_decisions")
    op.drop_table("stage_attempt_context")
    op.drop_table("stage_attempts")
    op.drop_table("artifacts")
    op.drop_table("run_pins")
    op.drop_table("runs")
