"""Create the agent registry tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""

# ruff: noqa: INP001 -- Alembic loads revision scripts by path; versions/ is not a package

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create `agents` and `agent_versions`."""
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("name", name=op.f("uq_agents_name")),
    )
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.String(length=64), nullable=False),
        sa.Column("parent_sequence", sa.Integer(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.UniqueConstraint(
            "agent_id", "sequence", name=op.f("uq_agent_versions_agent_id_sequence")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_agent_versions_agent_id_agents")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "parent_sequence"],
            ["agent_versions.agent_id", "agent_versions.sequence"],
            name=op.f("fk_agent_versions_parent"),
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_agent_versions_sequence_positive")),
        sa.CheckConstraint(
            "(parent_sequence IS NULL AND sequence = 1)"
            " OR (parent_sequence IS NOT NULL AND parent_sequence = sequence - 1)",
            name=op.f("ck_agent_versions_parent_is_previous"),
        ),
    )
    op.create_index(
        op.f("ix_agent_versions_content_id"), "agent_versions", ["content_id"], unique=False
    )


def downgrade() -> None:
    """Drop the registry tables."""
    op.drop_index(op.f("ix_agent_versions_content_id"), table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_table("agents")
