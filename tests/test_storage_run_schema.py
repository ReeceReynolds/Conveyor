"""The run tables (migration 0002) and the records that mirror them."""

import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

import pytest
from alembic import command
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from conveyor.storage import STATE_DIR, MigrationRequiredError, ObjectStore, Store
from conveyor.storage.database import connect
from conveyor.storage.migrate import alembic_config, upgrade
from conveyor.storage.records import (
    FINISHED_RUN_STATUSES,
    GATE_ATTEMPT_STATUSES,
    OUTPUT_ATTEMPT_STATUSES,
    UNFINISHED_ATTEMPT_STATUSES,
    WORK_ATTEMPT_STATUSES,
    ArtifactRecord,
    ArtifactRef,
    AttemptStatus,
    CostRecord,
    CostSource,
    Decision,
    DecisionKind,
    PinRecord,
    ReworkRecord,
    RunDecisionRecord,
    RunOptions,
    RunRecord,
    RunStatus,
    SpanEventRecord,
    SpanKind,
    SpanRecord,
    SpanStatusCode,
    StageAttemptRecord,
    StageKind,
)
from conveyor.storage.registry import RegistryRepository
from conveyor.storage.schema import Base

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
COMMIT = "c" * 40
RUN_ID = "01a1cee2edb8703792c077cdbdd34567"
TRACE_ID = "d" * 32
SPAN_ID = "e" * 16
CONTRACT = "contracts.TaskList"
WHEN = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
LATER = WHEN + timedelta(minutes=5)

type Row = dict[str, object]


def _migrated(path: Path) -> Engine:
    engine = connect(f"sqlite:///{path}")
    with engine.begin() as connection:
        upgrade(connection)
    return engine


def _insert(engine: Engine, table: str, row: Mapping[str, object]) -> None:
    """Insert a row with SQLAlchemy Core: no repository, no record, only the database."""
    with engine.begin() as connection:
        connection.execute(Base.metadata.tables[table].insert().values(dict(row)))


# --- Valid rows, which each case below breaks in one way ---------------------------------------


def _run(**changes: object) -> Row:
    return {
        "id": RUN_ID,
        "factory": "prd-to-pr",
        "factory_digest": DIGEST,
        "input_digest": DIGEST,
        "status": RunStatus.RUNNING,
        "application_version": "conveyor-run-1",
        "queue_name": f"run-{RUN_ID}",
        "created_at": WHEN,
        "updated_at": WHEN,
        "finished_at": None,
    } | changes


def _attempt(**changes: object) -> Row:
    return {
        "run_id": RUN_ID,
        "stage": "implement",
        "attempt": 2,
        "seq": 2,
        "iteration": 0,
        "kind": StageKind.AGENT,
        "status": AttemptStatus.SUCCEEDED,
        "input_digest": DIGEST,
        "input_contract": CONTRACT,
        "output_digest": DIGEST,
        "output_contract": CONTRACT,
        "requests": 2,
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_tokens": 5,
        "cache_write_tokens": 3,
        "cost_nanodollars": 1500,
        "cost_source": CostSource.PROVIDER,
        "started_at": WHEN,
        "finished_at": LATER,
    } | changes


def _gate(**changes: object) -> Row:
    """A waiting gate attempt: no input or output, no usage, no cost."""
    return (
        _attempt(
            stage="approve",
            attempt=1,
            seq=3,
            kind=StageKind.GATE,
            status=AttemptStatus.WAITING,
            input_digest=None,
            input_contract=None,
            output_digest=None,
            output_contract=None,
            requests=0,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_nanodollars=None,
            cost_source=None,
            finished_at=None,
        )
        | changes
    )


def _context(**changes: object) -> Row:
    return {
        "run_id": RUN_ID,
        "stage": "implement",
        "attempt": 1,
        "position": 1,
        "artifact_digest": DIGEST,
        "artifact_contract": CONTRACT,
    } | changes


def _artifact(**changes: object) -> Row:
    return {"digest": OTHER_DIGEST, "contract": CONTRACT, "size": 2, "created_at": WHEN} | changes


def _decision(**changes: object) -> Row:
    return {
        "run_id": RUN_ID,
        "stage": "implement",
        "attempt": 1,
        "kind": DecisionKind.ESCALATION,
        "decision": Decision.APPROVE,
        "author": "ada",
        "decided_at": WHEN,
    } | changes


def _span(**changes: object) -> Row:
    return {
        "trace_id": TRACE_ID,
        "span_id": "f" * 16,
        "run_id": RUN_ID,
        "stage": "implement",
        "attempt": 1,
        "name": "invoke_agent implementer",
        "kind": SpanKind.INTERNAL,
        "start_time": WHEN,
        "end_time": LATER,
        "status_code": SpanStatusCode.OK,
        "attributes": "{}",
        "events": "[]",
    } | changes


def _pin(**changes: object) -> Row:
    return {"run_id": RUN_ID, "agent_id": 1, "sequence": 1} | changes


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Engine]:
    """A migrated SQLite database with a published agent, a run, an artifact and an attempt."""
    engine = _migrated(tmp_path / "runs.db")
    _insert(engine, "agents", {"id": 1, "name": "implementer"})
    _insert(
        engine,
        "agent_versions",
        {
            "agent_id": 1,
            "sequence": 1,
            "content_id": DIGEST,
            "parent_sequence": None,
            "author": "ada",
            "message": "m",
            "created_at": WHEN,
            "snapshot_digest": DIGEST,
        },
    )
    _insert(engine, "runs", _run())
    _insert(engine, "artifacts", _artifact(digest=DIGEST))
    _insert(engine, "stage_attempts", _attempt(attempt=1, seq=1))
    yield engine
    engine.dispose()


def test_valid_rows_are_stored(seeded: Engine) -> None:
    _insert(seeded, "run_pins", _pin())
    _insert(seeded, "artifacts", _artifact())
    _insert(seeded, "stage_attempts", _attempt())
    _insert(seeded, "stage_attempts", _gate())
    _insert(
        seeded,
        "stage_attempts",
        _attempt(
            attempt=3,
            seq=4,
            iteration=1,
            cost_source=CostSource.MIXED,
            rework_stage="review",
            rework_digest=DIGEST,
            rework_contract=CONTRACT,
        ),
    )
    _insert(seeded, "stage_attempt_context", _context())
    _insert(seeded, "run_decisions", _decision(note="looks good"))
    _insert(seeded, "run_decisions", _decision(stage="approve", kind=DecisionKind.GATE))
    _insert(seeded, "spans", _span())
    _insert(seeded, "spans", _span(span_id=SPAN_ID, stage=None, attempt=None))
    _insert(
        seeded,
        "runs",
        _run(id=RUN_ID[:-1] + "8", status=RunStatus.COMPLETED, finished_at=LATER),
    )

    with seeded.connect() as connection:
        counts = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608 -- fixed table names
            for table in ("runs", "run_pins", "stage_attempts", "stage_attempt_context", "spans")
        }
    assert counts == {
        "runs": 2,
        "run_pins": 1,
        "stage_attempts": 4,
        "stage_attempt_context": 1,
        "spans": 2,
    }


# Each case breaks one constraint of an otherwise valid row; the database names the constraint.
_CHECK_CASES: list[tuple[str, Row, str]] = [
    ("runs", _run(id="r1"), "ck_runs_id_length"),
    ("runs", _run(id=RUN_ID.upper()), "ck_runs_id_lowercase_hex"),
    ("runs", _run(id=RUN_ID[:-1] + "g"), "ck_runs_id_lowercase_hex"),
    (
        "runs",
        _run(id=RUN_ID[:-1] + "9", max_stage_requests=0),
        "ck_runs_max_stage_requests_positive",
    ),
    ("runs", _run(id=RUN_ID[:-1] + "9", max_run_tokens=0), "ck_runs_max_run_tokens_positive"),
    ("runs", _run(id=RUN_ID[:-1] + "9", status="paused"), "ck_runs_status_valid"),
    ("runs", _run(id=RUN_ID[:-1] + "9", status="completed"), "ck_runs_finished_when_done"),
    ("runs", _run(id=RUN_ID[:-1] + "9", finished_at=LATER), "ck_runs_finished_when_done"),
    ("artifacts", _artifact(size=0), "ck_artifacts_size_positive"),
    ("stage_attempts", _attempt(seq=0), "ck_stage_attempts_seq_positive"),
    ("stage_attempts", _attempt(attempt=0), "ck_stage_attempts_attempt_positive"),
    ("stage_attempts", _attempt(iteration=-1), "ck_stage_attempts_iteration_not_negative"),
    ("stage_attempts", _attempt(kind="robot"), "ck_stage_attempts_kind_valid"),
    ("stage_attempts", _attempt(status="paused"), "ck_stage_attempts_status_valid"),
    ("stage_attempts", _attempt(status="approved"), "ck_stage_attempts_status_valid"),
    ("stage_attempts", _gate(status="succeeded"), "ck_stage_attempts_status_valid"),
    ("stage_attempts", _gate(requests=1), "ck_stage_attempts_gate_has_no_usage"),
    ("stage_attempts", _gate(cache_read_tokens=1), "ck_stage_attempts_gate_has_no_usage"),
    (
        "stage_attempts",
        _gate(cost_nanodollars=1, cost_source="provider"),
        "ck_stage_attempts_gate_has_no_usage",
    ),
    (
        "stage_attempts",
        _gate(iteration=1, rework_stage="review", rework_digest=DIGEST, rework_contract=CONTRACT),
        "ck_stage_attempts_gate_is_not_rework",
    ),
    ("stage_attempts", _attempt(finished_at=None), "ck_stage_attempts_finished_when_done"),
    (
        "stage_attempts",
        _attempt(status="running", output_digest=None, output_contract=None),
        "ck_stage_attempts_finished_when_done",
    ),
    (
        "stage_attempts",
        _attempt(finished_at=WHEN - timedelta(seconds=1)),
        "ck_stage_attempts_finished_after_start",
    ),
    ("stage_attempts", _attempt(input_contract=None), "ck_stage_attempts_input_complete"),
    ("stage_attempts", _attempt(output_digest=None), "ck_stage_attempts_output_complete"),
    ("stage_attempts", _attempt(rework_stage="review"), "ck_stage_attempts_rework_complete"),
    (
        "stage_attempts",
        _attempt(rework_stage="review", rework_digest=DIGEST, rework_contract=CONTRACT),
        "ck_stage_attempts_rework_after_first",
    ),
    (
        "stage_attempts",
        _attempt(status="rejected", output_digest=None, output_contract=None),
        "ck_stage_attempts_output_when_done",
    ),
    ("stage_attempts", _attempt(output_tokens=-1), "ck_stage_attempts_usage_not_negative"),
    ("stage_attempts", _attempt(requests=-1), "ck_stage_attempts_usage_not_negative"),
    ("stage_attempts", _attempt(cache_write_tokens=-1), "ck_stage_attempts_usage_not_negative"),
    ("stage_attempts", _attempt(cost_source=None), "ck_stage_attempts_cost_complete"),
    ("stage_attempts", _attempt(cost_nanodollars=-1), "ck_stage_attempts_cost_not_negative"),
    ("stage_attempts", _attempt(cost_source="guessed"), "ck_stage_attempts_cost_source_valid"),
    (
        "stage_attempt_context",
        _context(position=-1),
        "ck_stage_attempt_context_position_not_negative",
    ),
    ("run_decisions", _decision(kind="vote"), "ck_run_decisions_kind_valid"),
    ("run_decisions", _decision(decision="maybe"), "ck_run_decisions_decision_valid"),
    ("spans", _span(kind="sideways"), "ck_spans_kind_valid"),
    ("spans", _span(status_code="fine"), "ck_spans_status_code_valid"),
    ("spans", _span(attempt=None), "ck_spans_attempt_complete"),
    ("spans", _span(end_time=WHEN - timedelta(seconds=1)), "ck_spans_ends_after_start"),
]


@pytest.mark.parametrize(
    ("table", "row", "constraint"),
    _CHECK_CASES,
    ids=[f"{constraint}-{index}" for index, (_, _, constraint) in enumerate(_CHECK_CASES)],
)
def test_check_constraints_reject_bad_values(
    seeded: Engine, table: str, row: Row, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=rf"CHECK constraint failed: {constraint}\n"):
        _insert(seeded, table, row)


def test_every_check_constraint_has_a_rejection_case() -> None:
    names = {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        if not table.name.startswith("agent")
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {constraint for _, _, constraint in _CHECK_CASES} == names


@pytest.mark.parametrize(
    ("table", "row"),
    [
        ("run_pins", _pin(sequence=2)),
        ("run_pins", _pin(run_id=RUN_ID[:-1] + "9")),
        ("stage_attempts", _attempt(output_digest=OTHER_DIGEST)),
        ("stage_attempts", _attempt(output_contract="contracts.Other")),
        ("stage_attempt_context", _context(attempt=5)),
        ("stage_attempt_context", _context(artifact_digest=OTHER_DIGEST)),
        ("run_decisions", _decision(run_id=RUN_ID[:-1] + "9")),
        ("run_decisions", _decision(stage="deploy")),
        ("run_decisions", _decision(attempt=2)),
        ("spans", _span(attempt=5)),
    ],
)
def test_foreign_keys_reject_missing_rows(seeded: Engine, table: str, row: Row) -> None:
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        _insert(seeded, table, row)


def test_an_attempt_has_one_decision(seeded: Engine) -> None:
    _insert(seeded, "run_decisions", _decision())

    with pytest.raises(IntegrityError, match="UNIQUE constraint failed: run_decisions"):
        _insert(seeded, "run_decisions", _decision())
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed: run_decisions"):
        _insert(seeded, "run_decisions", _decision(decision=Decision.REJECT, note="no"))


def test_attempts_have_a_total_order_per_run(seeded: Engine) -> None:
    with pytest.raises(IntegrityError, match=r"UNIQUE constraint failed: stage_attempts\.run_id"):
        _insert(seeded, "stage_attempts", _attempt(seq=1))
    _insert(seeded, "runs", _run(id=RUN_ID[:-1] + "8"))
    _insert(seeded, "stage_attempts", _attempt(run_id=RUN_ID[:-1] + "8", seq=1))


def test_an_attempt_is_written_once(seeded: Engine) -> None:
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed: stage_attempts"):
        _insert(seeded, "stage_attempts", _attempt(attempt=1))


# --- The migration agrees with the models and the record enums ---------------------------------


def _create_statements(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type = 'table'")
        ).all()
    return {str(name): str(sql) for name, sql in rows}


def _check_body(create: str, name: str) -> str:
    """The text inside `CONSTRAINT <name> CHECK (...)`, matching nested parentheses."""
    start = create.index(f"CONSTRAINT {name} CHECK (") + len(f"CONSTRAINT {name} CHECK (")
    depth = 1
    for index in range(start, len(create)):
        depth += {"(": 1, ")": -1}.get(create[index], 0)
        if depth == 0:
            return create[start:index]
    msg = f"unbalanced CHECK constraint {name}"
    raise AssertionError(msg)


def test_migrated_check_constraints_are_exactly_the_models(tmp_path: Path) -> None:
    """Alembic's drift check ignores CHECK constraints, so compare the stored DDL instead."""
    engine = _migrated(tmp_path / "ddl.db")
    creates = _create_statements(engine)
    engine.dispose()

    for table in Base.metadata.tables.values():
        checks = {
            str(constraint.name): str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        create = creates[table.name]
        assert create.count(" CHECK (") == len(checks), table.name
        for name, sql in checks.items():
            assert _check_body(create, name) == sql, name


def _listed(check: str, column: str) -> list[list[str]]:
    """Every `<column> IN (...)` list in a check, as its quoted values."""
    return [
        re.findall(r"'([^']*)'", values)
        for values in re.findall(rf"\b{column} IN \(([^)]*)\)", check)
    ]


def _in_order[E: StrEnum](kind: type[E], subset: frozenset[E]) -> list[str]:
    return [str(member) for member in kind if member in subset]


def test_record_enums_match_the_migrated_check_constraints(tmp_path: Path) -> None:
    engine = _migrated(tmp_path / "enums.db")
    creates = _create_statements(engine)
    engine.dispose()

    def check(table: str, name: str) -> str:
        return _check_body(creates[table], f"ck_{table}_{name}")

    assert _listed(check("runs", "status_valid"), "status") == [[str(s) for s in RunStatus]]
    assert _listed(check("runs", "finished_when_done"), "status") == 2 * [
        _in_order(RunStatus, FINISHED_RUN_STATUSES)
    ]
    assert _listed(check("stage_attempts", "kind_valid"), "kind") == [[str(k) for k in StageKind]]
    statuses = check("stage_attempts", "status_valid")
    assert _listed(statuses, "status") == [
        [str(s) for s in GATE_ATTEMPT_STATUSES],
        [str(s) for s in WORK_ATTEMPT_STATUSES],
    ]
    assert _listed(statuses, "kind") == [[str(StageKind.AGENT), str(StageKind.OPERATION)]]
    assert f"kind = '{StageKind.GATE}'" in statuses
    assert {*GATE_ATTEMPT_STATUSES, *WORK_ATTEMPT_STATUSES} == set(AttemptStatus)
    assert _listed(check("stage_attempts", "finished_when_done"), "status") == 2 * [
        _in_order(AttemptStatus, UNFINISHED_ATTEMPT_STATUSES)
    ]
    assert _listed(check("stage_attempts", "output_when_done"), "status") == [
        _in_order(AttemptStatus, OUTPUT_ATTEMPT_STATUSES)
    ]
    assert _listed(check("stage_attempts", "cost_source_valid"), "cost_source") == [
        [str(s) for s in CostSource]
    ]
    assert _listed(check("run_decisions", "kind_valid"), "kind") == [[str(k) for k in DecisionKind]]
    assert _listed(check("run_decisions", "decision_valid"), "decision") == [
        [str(d) for d in Decision]
    ]
    assert _listed(check("spans", "kind_valid"), "kind") == [[str(k) for k in SpanKind]]
    assert _listed(check("spans", "status_code_valid"), "status_code") == [
        [str(c) for c in SpanStatusCode]
    ]


# --- Upgrading a registry written before runs existed ------------------------------------------


def _publish_at_0001(database_url: str, objects: ObjectStore) -> None:
    """Migrate an empty database to 0001 only, then publish two versions through the registry."""
    engine = connect(database_url)
    try:
        with engine.begin() as connection:
            command.upgrade(alembic_config(connection), "0001")
        registry = RegistryRepository(engine, objects)
        for content, when in ((DIGEST, WHEN), (OTHER_DIGEST, LATER)):
            registry.add_version(
                agent="implementer",
                content_id=content,
                author="ada",
                message=f"publish {content[0]}",
                snapshot_digest=objects.put(content.encode()),
                created_at=when,
            )
        assert sorted(inspect(engine).get_table_names()) == [
            "agent_versions",
            "agents",
            "alembic_version",
        ]
    finally:
        engine.dispose()


def test_upgrade_from_0001_keeps_registry_data(database_url: str, tmp_path: Path) -> None:
    objects = ObjectStore(tmp_path / "objects")
    _publish_at_0001(database_url, objects)

    with Store.open_url(database_url, tmp_path / "objects") as store:
        history = store.registry.history("implementer")
        assert [(v.sequence, v.content_id, v.parent_sequence) for v in history] == [
            (2, OTHER_DIGEST, 1),
            (1, DIGEST, None),
        ]
        assert {v.created_at for v in history} == {WHEN, LATER}
        assert store.objects.get(history[0].snapshot_digest) == OTHER_DIGEST.encode()

    engine = connect(database_url)
    try:
        assert "stage_attempts" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_a_read_only_open_at_0001_needs_a_write_first(tmp_path: Path) -> None:
    """ADR 0015: after this migration, reads fail until something writes and migrates."""
    state = tmp_path / STATE_DIR
    state.mkdir()
    (state / ".gitignore").write_text("*\n")
    _publish_at_0001(f"sqlite:///{state / 'conveyor.db'}", ObjectStore(state / "objects"))

    with pytest.raises(MigrationRequiredError, match="written by an older version"):
        Store.open(tmp_path, read_only=True)
    with Store.open(tmp_path):
        pass
    with Store.open(tmp_path, read_only=True) as store:
        assert store.registry.agents() == ("implementer",)


def test_downgrade_to_0001_keeps_registry_data(store: Store, database_url: str) -> None:
    store.registry.add_version(
        agent="implementer",
        content_id=DIGEST,
        author="ada",
        message="m",
        snapshot_digest=store.objects.put(b"snapshot"),
        created_at=WHEN,
    )
    engine = connect(database_url)
    try:
        with engine.begin() as connection:
            command.downgrade(alembic_config(connection), "0001")
        assert sorted(inspect(engine).get_table_names()) == [
            "agent_versions",
            "agents",
            "alembic_version",
        ]
    finally:
        engine.dispose()
    assert store.registry.agents() == ("implementer",)


# --- Records --------------------------------------------------------------------------------


def _attempt_record(**changes: object) -> StageAttemptRecord:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "stage": "implement",
        "attempt": 1,
        "seq": 1,
        "iteration": 0,
        "kind": StageKind.AGENT,
        "status": AttemptStatus.SUCCEEDED,
        "output": ArtifactRef(digest=DIGEST, contract=CONTRACT),
        "started_at": WHEN,
        "finished_at": LATER,
    } | changes
    return StageAttemptRecord.model_validate(values)


def test_records_are_frozen_value_types() -> None:
    local = datetime(2026, 11, 12, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    run = RunRecord(
        id=RUN_ID,
        factory="prd-to-pr",
        factory_digest=DIGEST,
        input_digest=DIGEST,
        status=RunStatus.PENDING,
        application_version="conveyor-run-1",
        queue_name=f"run-{RUN_ID}",
        traceparent=f"00-{TRACE_ID}-{SPAN_ID}-01",
        created_at=local,
        updated_at=local,
    )
    assert run.created_at == WHEN
    assert run.created_at.tzinfo is UTC
    assert run == run.model_copy()
    with pytest.raises(ValidationError, match="frozen"):
        run.status = RunStatus.RUNNING
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PinRecord.model_validate(
            {"run_id": RUN_ID, "agent": "a", "sequence": 1, "content_id": DIGEST, "x": 1}
        )


@pytest.mark.parametrize("bad_id", ["0" * 32, RUN_ID.upper(), RUN_ID[:-1]])
def test_run_ids_are_uuid7_hex(bad_id: str) -> None:
    with pytest.raises(ValidationError, match="run_id"):
        PinRecord(run_id=bad_id, agent="implementer", sequence=1, content_id=DIGEST)


def test_a_run_has_finished_exactly_when_its_status_says_so() -> None:
    values: dict[str, object] = {
        "id": RUN_ID,
        "factory": "prd-to-pr",
        "factory_digest": DIGEST,
        "input_digest": DIGEST,
        "application_version": "conveyor-run-1",
        "queue_name": "q",
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    assert RunRecord.model_validate(
        values | {"status": "completed", "finished_at": LATER}
    ).finished_at == (LATER)
    for status, finished in (("completed", None), ("waiting", LATER)):
        with pytest.raises(ValidationError, match="finished_at must be set exactly"):
            RunRecord.model_validate(values | {"status": status, "finished_at": finished})


def test_attempt_records_hold_their_rework_context_and_cost() -> None:
    verdict = ArtifactRef(digest=OTHER_DIGEST, contract="contracts.ReviewVerdict")
    record = _attempt_record(
        iteration=1,
        input=ArtifactRef(digest=DIGEST, contract=CONTRACT),
        context=(verdict,),
        rework=ReworkRecord(stage="review", verdict=verdict),
        cost=CostRecord(nanodollars=1_234_567_890, source=CostSource.CALCULATED),
    )
    assert record.cost is not None
    assert record.cost.dollars == Decimal("1.23456789")
    assert record.has_usage
    assert not _attempt_record().has_usage
    assert (
        _attempt_record(
            kind=StageKind.GATE, status=AttemptStatus.WAITING, output=None, finished_at=None
        ).finished_at
        is None
    )


_GATE: dict[str, object] = {
    "kind": StageKind.GATE,
    "status": AttemptStatus.WAITING,
    "output": None,
    "finished_at": None,
}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"kind": StageKind.GATE}, "a gate attempt cannot be succeeded"),
        ({"status": AttemptStatus.APPROVED}, "a agent attempt cannot be approved"),
        ({"finished_at": None}, "finished_at must be set exactly"),
        ({"status": AttemptStatus.RUNNING}, "finished_at must be set exactly"),
        (
            {
                "rework": ReworkRecord(
                    stage="review", verdict=ArtifactRef(digest=DIGEST, contract=CONTRACT)
                )
            },
            "iteration of at least 1",
        ),
        ({"output": None}, "a succeeded agent attempt must have an output"),
        ({"finished_at": WHEN - timedelta(seconds=1)}, "cannot finish before it starts"),
        (_GATE | {"requests": 1}, "a gate attempt has no usage"),
        (_GATE | {"cache_write_tokens": 1}, "a gate attempt has no usage"),
        (
            _GATE | {"cost": CostRecord(nanodollars=0, source=CostSource.MIXED)},
            "a gate attempt has no usage",
        ),
        (
            _GATE
            | {
                "iteration": 1,
                "rework": ReworkRecord(
                    stage="review", verdict=ArtifactRef(digest=DIGEST, contract=CONTRACT)
                ),
            },
            "a gate attempt has no usage, cost or rework",
        ),
    ],
)
def test_attempt_records_refuse_inconsistent_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _attempt_record(**changes)


def test_artifact_and_decision_records() -> None:
    artifact = ArtifactRecord(digest=DIGEST, contract=CONTRACT, size=12, created_at=WHEN)
    assert ArtifactRef(digest=artifact.digest, contract=artifact.contract).contract == CONTRACT
    decision = RunDecisionRecord(
        run_id=RUN_ID,
        stage="implement",
        attempt=3,
        kind=DecisionKind.ESCALATION,
        decision=Decision.APPROVE,
        author="ada",
        decided_at=WHEN,
    )
    assert decision.note is None
    with pytest.raises(ValidationError, match="size"):
        ArtifactRecord(digest=DIGEST, contract=CONTRACT, size=0, created_at=WHEN)


def _span_record(**changes: object) -> SpanRecord:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "stage": "implement",
        "attempt": 1,
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "name": "execute_tool fs.read_file",
        "kind": SpanKind.INTERNAL,
        "start_time": WHEN,
        "end_time": LATER,
        "status_code": SpanStatusCode.ERROR,
    } | changes
    return SpanRecord.model_validate(values)


def test_span_records_carry_attributes_and_events() -> None:
    event = SpanEventRecord(name="exception", time=WHEN, attributes={"exception.type": "OSError"})
    span = _span_record(
        attributes={"gen_ai.usage.input_tokens": 12, "tags": ["a"]}, events=(event,)
    )
    assert span.events[0].attributes == {"exception.type": "OSError"}
    assert _span_record(stage=None, attempt=None).stage is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"attempt": None}, "stage and attempt must be given together"),
        ({"end_time": WHEN - timedelta(seconds=1)}, "cannot end before it starts"),
        ({"span_id": "E" * 16}, "span_id"),
    ],
)
def test_span_records_refuse_inconsistent_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _span_record(**changes)


def test_run_records_hold_how_the_run_was_started() -> None:
    values: dict[str, object] = {
        "id": RUN_ID,
        "factory": "prd-to-pr",
        "factory_digest": DIGEST,
        "input_digest": DIGEST,
        "status": RunStatus.PENDING,
        "application_version": "conveyor-run-1",
        "queue_name": "q",
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    assert RunRecord.model_validate(values).options == RunOptions()
    options = RunOptions(
        repo_path="/work/sample-app",
        sandbox_image="conveyor-sandbox:1",
        max_stage_requests=50,
        max_run_tokens=2_000_000,
    )
    assert RunRecord.model_validate(values | {"options": options}).options == options
    with pytest.raises(ValidationError, match="max_run_tokens"):
        RunOptions(max_run_tokens=0)
