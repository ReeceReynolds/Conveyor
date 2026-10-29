"""The relational schema, as typed SQLAlchemy 2.0 declarative models.

These models are the source of truth for the schema; the Alembic migrations in `migrations/`
must produce exactly the same tables, which a test checks. Rows are internal to the storage
package: callers receive Pydantic records instead.
"""

from datetime import UTC, datetime
from typing import override

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Deterministic constraint names, so migrations can refer to them on every backend."""

DIGEST_LENGTH = 64
NAME_LENGTH = 255


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
