"""The agent registry's tables, behind a typed, append-only repository.

A version is identified two ways: by its sequence number within the agent (`v1`, `v2`, ...),
which is unique, and by its content id (the hash of its snapshot), which is not, because
reverting to earlier content publishes a new sequence with an old content id. Versions are
never updated or deleted.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Final

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Engine, Select, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from conveyor.storage.database import writer
from conveyor.storage.errors import (
    AmbiguousVersionError,
    InvalidPrefixError,
    ObjectNotFoundError,
    VersionNotFoundError,
)
from conveyor.storage.objects import DIGEST_PATTERN, ObjectStore
from conveyor.storage.schema import NAME_LENGTH, AgentRow, AgentVersionRow

MIN_PREFIX_LENGTH: Final = 4
"""The shortest content id prefix `RegistryRepository.find` accepts."""

_PREFIX_PATTERN = rf"[0-9a-f]{{{MIN_PREFIX_LENGTH},64}}"

type Digest = Annotated[str, StringConstraints(pattern=rf"^{DIGEST_PATTERN}$")]
"""A sha256 digest: 64 lowercase hexadecimal characters."""


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


type UTCTimestamp = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""A timezone-aware datetime, normalised to UTC."""


class AgentVersionRecord(BaseModel):
    """One published, immutable version of an agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str = Field(min_length=1, max_length=NAME_LENGTH, description="The agent's name.")
    sequence: int = Field(ge=1, description="Position in the agent's history, from 1.")
    content_id: Digest = Field(description="The version id: the hash of the agent snapshot.")
    parent_sequence: int | None = Field(
        ge=1, description="The sequence this version follows; `None` for the first."
    )
    author: str = Field(description="Who published the version.")
    message: str = Field(description="Why the version was published.")
    created_at: UTCTimestamp = Field(description="When the version was published, in UTC.")
    snapshot_digest: Digest = Field(description="Object store digest of the snapshot bytes.")


class RegistryRepository:
    """Append-only access to agents and their versions."""

    def __init__(self, engine: Engine, objects: ObjectStore) -> None:
        """Create the repository.

        Args:
            engine: An engine from `conveyor.storage.database.connect`, already migrated.
            objects: The store snapshots are saved in, used to check that a version's
                snapshot exists before recording it.
        """
        self._engine = engine
        self._writer = writer(engine)
        self._objects = objects

    # Keyword-only, and each argument is one column of the version row; grouping them into a
    # parameter object would only move the same six fields elsewhere.
    def add_version(  # noqa: PLR0913
        self,
        *,
        agent: str,
        content_id: str,
        author: str,
        message: str,
        snapshot_digest: str,
        created_at: datetime,
    ) -> AgentVersionRecord:
        """Record the next version of an agent, creating the agent on its first version.

        The sequence is the latest one plus one (starting at 1) and the parent is the latest
        version. Both are computed and written in one transaction that holds the agent's write
        lock, so concurrent publishers queue rather than duplicate a sequence.

        Args:
            agent: The agent's name.
            content_id: The new version's id (its snapshot hash).
            author: Who is publishing.
            message: Why.
            snapshot_digest: Where the snapshot is in the object store; it must be stored.
            created_at: When, as a timezone-aware datetime.

        Returns:
            The recorded version.

        Raises:
            ObjectNotFoundError: If no object with `snapshot_digest` is stored.
            InvalidDigestError: If `snapshot_digest` is malformed.
            pydantic.ValidationError: If any other argument is invalid.
        """
        if not self._objects.exists(snapshot_digest):
            raise ObjectNotFoundError(snapshot_digest)
        # Validate everything before touching the database, so bad input is always a
        # ValidationError rather than whichever constraint a given backend trips first.
        draft = AgentVersionRecord(
            agent=agent,
            sequence=1,
            content_id=content_id,
            parent_sequence=None,
            author=author,
            message=message,
            created_at=created_at,
            snapshot_digest=snapshot_digest,
        )
        with Session(self._writer) as session, session.begin():
            agent_id = _lock_agent(session, agent)
            latest = session.scalar(
                select(func.max(AgentVersionRow.sequence)).where(
                    AgentVersionRow.agent_id == agent_id
                )
            )
            # The numbers come from the database and satisfy the record's constraints.
            record = draft.model_copy(
                update={
                    "sequence": 1 if latest is None else latest + 1,
                    "parent_sequence": latest,
                }
            )
            session.add(
                AgentVersionRow(
                    agent_id=agent_id,
                    sequence=record.sequence,
                    content_id=record.content_id,
                    parent_sequence=record.parent_sequence,
                    author=record.author,
                    message=record.message,
                    created_at=record.created_at,
                    snapshot_digest=record.snapshot_digest,
                )
            )
        return record

    def latest(self, agent: str) -> AgentVersionRecord | None:
        """Find an agent's newest version.

        Args:
            agent: The agent's name.

        Returns:
            The newest version, or `None` if the agent has never been published.
        """
        with Session(self._engine) as session:
            row = session.scalars(
                _versions_of(agent).order_by(AgentVersionRow.sequence.desc()).limit(1)
            ).first()
            return None if row is None else _record(agent, row)

    def get(self, agent: str, sequence: int) -> AgentVersionRecord:
        """Look up a version by its sequence number.

        Args:
            agent: The agent's name.
            sequence: The version's sequence number, from 1.

        Returns:
            The version.

        Raises:
            VersionNotFoundError: If the agent has no such version.
        """
        with Session(self._engine) as session:
            row = session.scalars(
                _versions_of(agent).where(AgentVersionRow.sequence == sequence)
            ).one_or_none()
            if row is None:
                raise VersionNotFoundError(agent, f"v{sequence}")
            return _record(agent, row)

    def find(self, agent: str, content_prefix: str) -> AgentVersionRecord:
        """Look up a version by a unique prefix of its content id.

        When one content id belongs to several versions (the agent was reverted to it), the
        newest of them is returned. Prefixes are matched case-insensitively.

        Args:
            agent: The agent's name.
            content_prefix: At least 4 hex characters of the content id.

        Returns:
            The newest version whose content id starts with the prefix.

        Raises:
            InvalidPrefixError: If the prefix is shorter than 4 or not hexadecimal.
            VersionNotFoundError: If no version's content id starts with it.
            AmbiguousVersionError: If it matches more than one distinct content id.
        """
        prefix = content_prefix.lower()
        if re.fullmatch(_PREFIX_PATTERN, prefix) is None:
            raise InvalidPrefixError(content_prefix)
        matching = AgentVersionRow.content_id.startswith(prefix, autoescape=True)
        with Session(self._engine) as session:
            content_ids = set(
                session.scalars(
                    _versions_of(agent)
                    .with_only_columns(AgentVersionRow.content_id)
                    .where(matching)
                )
            )
            if not content_ids:
                raise VersionNotFoundError(agent, f"with id prefix {content_prefix!r}")
            if len(content_ids) > 1:
                raise AmbiguousVersionError(agent, content_prefix, content_ids)
            row = session.scalars(
                _versions_of(agent)
                .where(AgentVersionRow.content_id == content_ids.pop())
                .order_by(AgentVersionRow.sequence.desc())
                .limit(1)
            ).one()
            return _record(agent, row)

    def history(self, agent: str) -> tuple[AgentVersionRecord, ...]:
        """List every version of an agent.

        Args:
            agent: The agent's name.

        Returns:
            The versions, newest first; empty if the agent has never been published.
        """
        with Session(self._engine) as session:
            rows = session.scalars(_versions_of(agent).order_by(AgentVersionRow.sequence.desc()))
            return tuple(_record(agent, row) for row in rows)

    def agents(self) -> tuple[str, ...]:
        """List every agent with at least one version.

        Returns:
            The agent names, sorted by code point (the same on every database).
        """
        with Session(self._engine) as session:
            return tuple(sorted(session.scalars(select(AgentRow.name))))


def _versions_of(agent: str) -> Select[AgentVersionRow]:
    return (
        select(AgentVersionRow)
        .join(AgentRow, AgentRow.id == AgentVersionRow.agent_id)
        .where(AgentRow.name == agent)
    )


def _lock_agent(session: Session, agent: str) -> int:
    """Create the agent if needed and hold its row lock until the transaction ends.

    On SQLite the writer transaction already holds the database write lock; on Postgres the
    `FOR UPDATE` lock serialises publishers of the same agent.
    """
    if session.get_bind().dialect.name == "postgresql":
        insert = postgresql.insert(AgentRow).on_conflict_do_nothing(index_elements=["name"])
    else:
        insert = sqlite.insert(AgentRow).on_conflict_do_nothing(index_elements=["name"])
    session.execute(insert.values(name=agent))
    return session.scalars(
        select(AgentRow.id).where(AgentRow.name == agent).with_for_update()
    ).one()


def _record(agent: str, row: AgentVersionRow) -> AgentVersionRecord:
    return AgentVersionRecord(
        agent=agent,
        sequence=row.sequence,
        content_id=row.content_id,
        parent_sequence=row.parent_sequence,
        author=row.author,
        message=row.message,
        created_at=row.created_at,
        snapshot_digest=row.snapshot_digest,
    )
