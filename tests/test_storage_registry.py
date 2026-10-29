"""Registry repository semantics, run on SQLite and (with Docker) on Postgres."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from conveyor.storage import (
    AgentVersionRecord,
    AmbiguousVersionError,
    InvalidDigestError,
    InvalidPrefixError,
    ObjectNotFoundError,
    RegistryRepository,
    Store,
    VersionNotFoundError,
)

WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def content(seed: str) -> str:
    """A deterministic 64-hex content id."""
    return hashlib.sha256(seed.encode()).hexdigest()


def publish(
    store: Store, agent: str, content_id: str, *, message: str = "change", minutes: int = 0
) -> AgentVersionRecord:
    """Store a snapshot and record a version for it, as the registry service will."""
    snapshot = store.objects.put(f"{agent}:{content_id}".encode())
    return store.registry.add_version(
        agent=agent,
        content_id=content_id,
        author="Ada <ada@example.com>",
        message=message,
        snapshot_digest=snapshot,
        created_at=WHEN + timedelta(minutes=minutes),
    )


def test_first_version_starts_the_sequence(store: Store) -> None:
    record = publish(store, "implementer", content("a"), message="first")

    assert record == AgentVersionRecord(
        agent="implementer",
        sequence=1,
        content_id=content("a"),
        parent_sequence=None,
        author="Ada <ada@example.com>",
        message="first",
        created_at=WHEN,
        snapshot_digest=hashlib.sha256(f"implementer:{content('a')}".encode()).hexdigest(),
    )
    assert store.registry.latest("implementer") == record
    assert store.registry.get("implementer", 1) == record


def test_each_version_follows_the_latest(store: Store) -> None:
    records = [
        publish(store, "implementer", content(seed), minutes=i) for i, seed in enumerate("abc")
    ]

    assert [(r.sequence, r.parent_sequence) for r in records] == [(1, None), (2, 1), (3, 2)]
    assert store.registry.latest("implementer") == records[-1]
    assert store.registry.history("implementer") == tuple(reversed(records))
    assert [store.registry.get("implementer", n) for n in (1, 2, 3)] == records


def test_agents_have_independent_sequences(store: Store) -> None:
    publish(store, "planner", content("a"))
    publish(store, "planner", content("b"))
    other = publish(store, "reviewer", content("a"))

    assert (other.sequence, other.parent_sequence) == (1, None)
    assert store.registry.find("reviewer", content("a")[:8]) == other


def test_agents_are_sorted_the_same_on_every_database(store: Store) -> None:
    for name in ("task-planner", "Zed", "code-reviewer", "zed"):
        publish(store, name, content(name))

    assert store.registry.agents() == ("Zed", "code-reviewer", "task-planner", "zed")


def test_unknown_agents_and_versions(store: Store) -> None:
    publish(store, "implementer", content("a"))

    assert store.registry.latest("nobody") is None
    assert store.registry.history("nobody") == ()
    assert store.registry.agents() == ("implementer",)
    with pytest.raises(VersionNotFoundError, match=r"agent 'implementer' has no version v2"):
        store.registry.get("implementer", 2)
    with pytest.raises(VersionNotFoundError) as caught:
        store.registry.get("nobody", 1)
    assert (caught.value.agent, caught.value.reference) == ("nobody", "v1")


def test_created_at_is_normalised_to_utc(store: Store) -> None:
    plus_two = timezone(timedelta(hours=2))
    record = store.registry.add_version(
        agent="implementer",
        content_id=content("a"),
        author="ada",
        message="m",
        snapshot_digest=store.objects.put(b"snapshot"),
        created_at=datetime(2026, 10, 28, 14, 0, 0, 123456, tzinfo=plus_two),
    )

    expected = datetime(2026, 10, 28, 12, 0, 0, 123456, tzinfo=UTC)
    assert record.created_at == expected
    assert record.created_at.tzinfo is UTC
    stored = store.registry.get("implementer", 1).created_at
    assert stored == expected
    assert stored.tzinfo is UTC


def test_invalid_versions_are_rejected_without_writing_anything(store: Store) -> None:
    snapshot = store.objects.put(b"snapshot")

    def add(
        *, agent: str = "implementer", content_id: str = content("a"), created_at: datetime = WHEN
    ) -> AgentVersionRecord:
        return store.registry.add_version(
            agent=agent,
            content_id=content_id,
            author="ada",
            message="m",
            snapshot_digest=snapshot,
            created_at=created_at,
        )

    with pytest.raises(ValidationError, match="timezone"):
        add(created_at=datetime(2026, 10, 28))
    with pytest.raises(ValidationError, match="content_id"):
        add(content_id=content("a").upper())
    with pytest.raises(ValidationError, match="agent"):
        add(agent="")
    with pytest.raises(ValidationError, match="agent"):
        add(agent="a" * 256)

    assert store.registry.agents() == ()


def test_the_snapshot_must_be_stored_first(store: Store) -> None:
    def add(snapshot_digest: str) -> AgentVersionRecord:
        return store.registry.add_version(
            agent="implementer",
            content_id=content("a"),
            author="ada",
            message="m",
            snapshot_digest=snapshot_digest,
            created_at=WHEN,
        )

    with pytest.raises(ObjectNotFoundError):
        add(content("never stored"))
    with pytest.raises(InvalidDigestError):
        add("not-a-digest")

    assert store.registry.agents() == ()


def test_find_by_unique_prefix(store: Store) -> None:
    first = publish(store, "implementer", content("a"))
    second = publish(store, "implementer", content("b"))

    assert store.registry.find("implementer", content("a")[:4]) == first
    assert store.registry.find("implementer", content("b")) == second
    assert store.registry.find("implementer", content("b")[:12].upper()) == second


def test_find_returns_the_newest_version_of_reverted_content(store: Store) -> None:
    publish(store, "implementer", content("a"), message="original")
    publish(store, "implementer", content("b"), message="change")
    reverted = publish(store, "implementer", content("a"), message="revert")

    assert (reverted.sequence, reverted.parent_sequence) == (3, 2)
    assert store.registry.find("implementer", content("a")[:6]) == reverted
    assert [r.content_id for r in store.registry.history("implementer")] == [
        content("a"),
        content("b"),
        content("a"),
    ]


def test_find_reports_ambiguous_prefixes(store: Store) -> None:
    shared = "abcd" + "0" * 60
    near = "abcd" + "1" * 60
    publish(store, "implementer", near)
    publish(store, "implementer", shared)

    with pytest.raises(AmbiguousVersionError) as caught:
        store.registry.find("implementer", "abcd")

    assert caught.value.matches == (shared, near)
    assert str(caught.value) == (
        f"prefix 'abcd' matches several versions of 'implementer': {shared}, {near}"
    )
    assert store.registry.find("implementer", "abcd0").content_id == shared


def test_find_is_scoped_to_the_agent(store: Store) -> None:
    publish(store, "implementer", content("a"))

    with pytest.raises(VersionNotFoundError) as caught:
        store.registry.find("reviewer", content("a")[:8])
    assert str(caught.value) == (
        f"agent 'reviewer' has no version with id prefix {content('a')[:8]!r}"
    )


@pytest.mark.parametrize("prefix", ["", "abc", "abcz", "ab cd", "0" * 65, "../.."])
def test_find_rejects_malformed_prefixes(store: Store, prefix: str) -> None:
    with pytest.raises(InvalidPrefixError) as caught:
        store.registry.find("implementer", prefix)
    assert caught.value.prefix == prefix


def test_versions_are_immutable(store: Store) -> None:
    record = publish(store, "implementer", content("a"))

    with pytest.raises(ValidationError, match="frozen"):
        record.message = "rewritten"
    public = {name for name in vars(RegistryRepository) if not name.startswith("_")}
    assert public == {
        "add_version",
        "add_version_if_changed",
        "latest",
        "get",
        "find",
        "history",
        "agents",
    }


def test_records_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AgentVersionRecord.model_validate(
            {
                "agent": "a",
                "sequence": 1,
                "content_id": content("a"),
                "parent_sequence": None,
                "author": "ada",
                "message": "m",
                "created_at": WHEN,
                "snapshot_digest": content("s"),
                "deleted": True,
            }
        )


def test_concurrent_publishers_never_share_a_sequence(store: Store) -> None:
    publishers, each = 6, 5

    def publish_many(worker: int) -> list[int]:
        return [
            publish(store, "implementer", content(f"{worker}-{n}")).sequence for n in range(each)
        ]

    with ThreadPoolExecutor(max_workers=publishers) as pool:
        sequences = [s for batch in pool.map(publish_many, range(publishers)) for s in batch]

    total = publishers * each
    assert sorted(sequences) == list(range(1, total + 1))
    history = store.registry.history("implementer")
    assert [(r.sequence, r.parent_sequence) for r in history] == [
        (n, n - 1 if n > 1 else None) for n in range(total, 0, -1)
    ]


def publish_if_changed(
    store: Store, agent: str, content_id: str, *, message: str = "change"
) -> tuple[AgentVersionRecord, bool]:
    """Like `publish`, through `add_version_if_changed`."""
    snapshot = store.objects.put(f"{agent}:{content_id}".encode())
    return store.registry.add_version_if_changed(
        agent=agent,
        content_id=content_id,
        author="Ada <ada@example.com>",
        message=message,
        snapshot_digest=snapshot,
        created_at=WHEN,
    )


def test_adding_if_changed_records_new_content(store: Store) -> None:
    first, first_created = publish_if_changed(store, "implementer", content("a"))
    second, second_created = publish_if_changed(store, "implementer", content("b"))

    assert (first_created, second_created) == (True, True)
    assert [(r.sequence, r.parent_sequence) for r in (first, second)] == [(1, None), (2, 1)]
    assert store.registry.history("implementer") == (second, first)


def test_adding_if_changed_returns_the_latest_when_its_content_is_the_same(store: Store) -> None:
    latest = publish(store, "implementer", content("a"), message="original")

    again, created = publish_if_changed(store, "implementer", content("a"), message="again")

    assert (again, created) == (latest, False)
    assert store.registry.history("implementer") == (latest,)


def test_adding_if_changed_compares_only_with_the_latest_version(store: Store) -> None:
    publish(store, "implementer", content("a"))
    publish(store, "implementer", content("b"))
    publish(store, "reviewer", content("c"))

    reverted, reverted_created = publish_if_changed(store, "implementer", content("a"))
    other, other_created = publish_if_changed(store, "planner", content("c"))

    assert (reverted_created, reverted.sequence, reverted.parent_sequence) == (True, 3, 2)
    assert (other_created, other.sequence) == (True, 1)


def test_adding_if_changed_validates_like_add_version(store: Store) -> None:
    with pytest.raises(ObjectNotFoundError):
        store.registry.add_version_if_changed(
            agent="implementer",
            content_id=content("a"),
            author="ada",
            message="m",
            snapshot_digest=content("never stored"),
            created_at=WHEN,
        )
    assert store.registry.agents() == ()


def test_concurrent_publishers_of_the_same_content_record_it_once(store: Store) -> None:
    publish(store, "implementer", content("a"))
    publishers = 6

    def publish_same(_worker: int) -> tuple[AgentVersionRecord, bool]:
        return publish_if_changed(store, "implementer", content("b"))

    with ThreadPoolExecutor(max_workers=publishers) as pool:
        outcomes = list(pool.map(publish_same, range(publishers)))

    created = [record for record, was_created in outcomes if was_created]
    assert len(created) == 1
    assert (created[0].sequence, created[0].parent_sequence) == (2, 1)
    assert [record for record, _ in outcomes] == [created[0]] * publishers
    assert [r.sequence for r in store.registry.history("implementer")] == [2, 1]


def test_separate_stores_on_one_project_share_the_registry(tmp_path: Path) -> None:
    def publish_from_own_store(worker: int) -> None:
        with Store.open(tmp_path) as own:
            for n in range(5):
                publish(own, "implementer", content(f"{worker}-{n}"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(publish_from_own_store, range(4)))

    with Store.open(tmp_path) as reopened:
        assert [r.sequence for r in reopened.registry.history("implementer")] == list(
            range(20, 0, -1)
        )
