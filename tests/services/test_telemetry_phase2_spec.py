"""Phase 2 service tests, one case per row of
docs/telemetry-visualisation-phase2-testspec.csv (fake data only).

Pending rows (TS-REC-12, TS-REC-13, TS-PRU-13, TS-PRU-14) are skipped because
the spec leaves the expected behaviour undecided (assumptions A5, A7b).
"""

import ast
import inspect
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from telemetry.models.database import (
    create_db_engine,
    create_session_factory,
    init_db,
)
from telemetry.models.orm import TelemetryReadingORM
from telemetry.models.schemas import TelemetryReading, TelemetryReadingCreate
from telemetry.services import telemetry as service
from tests.conftest import BASE_TIME as T0

VEH1 = "DEMO-VEH-001"
VEH2 = "DEMO-VEH-002"
SERVICE_FUNCTIONS = [
    service.add_reading,
    service.list_vehicles,
    service.get_latest,
    service.get_recent,
    service.prune_older_than,
]


def sec(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


def make_reading(
    vehicle_id: str = VEH1, ts: datetime = T0, **overrides: Any
) -> TelemetryReadingCreate:
    data: dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "timestamp": ts,
        "speed_kmh": 50.0,
        "engine_rpm": 2000,
        "fuel_level_pct": 75.0,
        "engine_temp_c": 90.0,
        "latitude": 10.0,
        "longitude": 20.0,
    }
    data.update(overrides)
    return TelemetryReadingCreate.model_validate(data)


def seed(session: Session, readings: list[TelemetryReadingCreate]) -> None:
    """Insert fixtures directly through the ORM (not via the unit under test)."""
    session.add_all(TelemetryReadingORM.from_schema(r) for r in readings)
    session.commit()


def seed_at(session: Session, offsets: list[timedelta], vehicle_id: str = VEH1) -> None:
    seed(session, [make_reading(vehicle_id, T0 + o) for o in offsets])


def count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(TelemetryReadingORM)) or 0


def timestamps(session: Session, vehicle_id: str = VEH1) -> list[datetime]:
    return [r.timestamp for r in service.get_recent(session, vehicle_id, 10_000)]


def raise_db_error(*_args: Any, **_kwargs: Any) -> Any:
    raise SQLAlchemyError("simulated database failure")


@pytest.fixture
def file_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'telemetry.db'}")
    init_db(engine)
    yield engine
    engine.dispose()


# --------------------------------------------------------------------------
# add_reading
# --------------------------------------------------------------------------


def test_add_reading_valid_reading_persists_single_row(session: Session) -> None:
    """TS-ADD-01: Persist a valid reading as exactly one row with equal fields."""
    reading = make_reading(VEH1, T0 + timedelta(microseconds=5))

    service.add_reading(session, reading)

    assert count(session) == 1
    row = session.scalars(select(TelemetryReadingORM)).one()
    assert row.vehicle_id == reading.vehicle_id
    assert row.timestamp.replace(tzinfo=UTC) == reading.timestamp
    assert row.speed_kmh == reading.speed_kmh
    assert row.engine_rpm == reading.engine_rpm
    assert row.fuel_level_pct == reading.fuel_level_pct
    assert row.engine_temp_c == reading.engine_temp_c
    assert row.latitude == reading.latitude
    assert row.longitude == reading.longitude


def test_add_reading_commit_visible_from_separate_session(file_engine: Engine) -> None:
    """TS-ADD-02: Make the stored row visible to a second session (committed)."""
    factory = create_session_factory(file_engine)
    with factory() as session_a, factory() as session_b:
        service.add_reading(session_a, make_reading())

        assert count(session_b) == 1


def test_add_reading_successive_inserts_assign_increasing_ids(session: Session) -> None:
    """TS-ADD-03: Assign distinct, increasing primary keys to successive inserts."""
    service.add_reading(session, make_reading(ts=T0))
    service.add_reading(session, make_reading(ts=T0 + sec(1)))

    ids = list(session.scalars(select(TelemetryReadingORM.id).order_by("id")))
    assert len(ids) == 2
    assert all(i is not None for i in ids)
    assert ids[1] > ids[0]


def test_add_reading_multiple_vehicles_stores_one_row_each(session: Session) -> None:
    """TS-ADD-04: Store one row per vehicle for the same timestamp."""
    service.add_reading(session, make_reading(VEH1, T0))
    service.add_reading(session, make_reading(VEH2, T0))

    assert count(session) == 2
    stored = set(session.scalars(select(TelemetryReadingORM.vehicle_id)))
    assert stored == {VEH1, VEH2}


@pytest.mark.parametrize(
    "extremes",
    [
        pytest.param(
            {
                "speed_kmh": 0,
                "engine_rpm": 0,
                "fuel_level_pct": 0,
                "engine_temp_c": -40,
                "latitude": -90,
                "longitude": -180,
            },
            id="TS-ADD-05-lower-bounds",
        ),
        pytest.param(
            {
                "speed_kmh": 250,
                "engine_rpm": 8000,
                "fuel_level_pct": 100,
                "engine_temp_c": 150,
                "latitude": 90,
                "longitude": 180,
            },
            id="TS-ADD-05-upper-bounds",
        ),
    ],
)
def test_add_reading_boundary_values_stored_unchanged(
    session: Session, extremes: dict[str, Any]
) -> None:
    """TS-ADD-05: Store the lower and upper field bounds without loss."""
    service.add_reading(session, make_reading(**extremes))

    row = session.scalars(select(TelemetryReadingORM)).one()
    for field, value in extremes.items():
        assert getattr(row, field) == value


def test_add_reading_microsecond_timestamp_round_trips_as_utc(
    session: Session,
) -> None:
    """TS-ADD-06: Read back the same UTC instant, including microseconds."""
    ts = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)

    service.add_reading(session, make_reading(ts=ts))

    latest = service.get_latest(session, VEH1)
    assert latest is not None
    assert latest.timestamp == ts


def test_add_reading_duplicate_vehicle_and_timestamp_stores_both_rows(
    session: Session,
) -> None:
    """TS-ADD-07: Allow a duplicate (vehicle_id, timestamp) pair without raising."""
    service.add_reading(session, make_reading())

    service.add_reading(session, make_reading())

    assert count(session) == 2


def test_add_reading_injection_vehicle_id_rejected_and_table_intact(
    session: Session,
) -> None:
    """TS-ADD-08: Reject an injection-style vehicle_id and keep the stored data."""
    service.add_reading(session, make_reading(VEH1))

    with pytest.raises(ValueError):
        make_reading("x'; DROP TABLE telemetry_readings;--")

    assert count(session) == 1
    assert service.list_vehicles(session) == [VEH1]


def test_add_reading_commit_failure_propagates_and_persists_nothing(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TS-ADD-09: Propagate a commit error and persist no row."""
    monkeypatch.setattr(session, "commit", raise_db_error)

    with pytest.raises(SQLAlchemyError):
        service.add_reading(session, make_reading())

    monkeypatch.undo()
    session.rollback()
    assert count(session) == 0
    service.add_reading(session, make_reading())
    assert count(session) == 1


def test_service_source_uses_orm_only_without_raw_sql_or_eval() -> None:
    """TS-ADD-10: Contain no raw SQL, text(), eval or exec in the service source."""
    source_path = Path(inspect.getsourcefile(service) or "")
    tree = ast.parse(source_path.read_text())
    sql_words = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "DROP ")
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_node = node.func
            name = (
                func_node.id
                if isinstance(func_node, ast.Name)
                else getattr(func_node, "attr", "")
            )
            if name in {"eval", "exec", "text"}:
                offenders.append(f"call to {name}()")
            if name == "execute" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant | ast.JoinedStr):
                    offenders.append("execute() with a string argument")
        if isinstance(node, ast.JoinedStr):
            literal = "".join(
                v.value
                for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            if any(word in literal.upper() for word in sql_words):
                offenders.append("f-string SQL")

    assert offenders == []


# --------------------------------------------------------------------------
# list_vehicles
# --------------------------------------------------------------------------


def test_list_vehicles_empty_db_returns_empty_list(session: Session) -> None:
    """TS-VEH-01: Return an empty list when no readings exist."""
    result = service.list_vehicles(session)

    assert result == []
    assert isinstance(result, list)


def test_list_vehicles_single_reading_returns_that_vehicle(session: Session) -> None:
    """TS-VEH-02: Return the single vehicle that has one reading."""
    seed_at(session, [timedelta(0)], VEH1)

    assert service.list_vehicles(session) == [VEH1]


def test_list_vehicles_many_readings_returns_each_id_once(session: Session) -> None:
    """TS-VEH-03: Return each vehicle ID exactly once despite many readings."""
    seed_at(session, [sec(i) for i in range(5)], VEH1)
    seed_at(session, [sec(i) for i in range(3)], VEH2)

    assert service.list_vehicles(session) == [VEH1, VEH2]


def test_list_vehicles_unordered_inserts_returns_sorted_ids(session: Session) -> None:
    """TS-VEH-04: Return IDs in ascending order regardless of insert order."""
    for vid in ("DEMO-VEH-003", VEH1, VEH2):
        seed_at(session, [timedelta(0)], vid)

    assert service.list_vehicles(session) == ["DEMO-VEH-001", VEH2, "DEMO-VEH-003"]


def test_list_vehicles_numeric_suffixes_sorted_lexicographically(
    session: Session,
) -> None:
    """TS-VEH-05: Sort IDs lexicographically, not by insertion order."""
    seed_at(session, [timedelta(0)], "DEMO-VEH-010")
    seed_at(session, [timedelta(0)], "DEMO-VEH-002")

    assert service.list_vehicles(session) == ["DEMO-VEH-002", "DEMO-VEH-010"]


def test_list_vehicles_case_differing_ids_returned_as_distinct(
    session: Session,
) -> None:
    """TS-VEH-06: Treat IDs that differ only by case as distinct, in binary order."""
    seed_at(session, [timedelta(0)], "demo-veh-001")
    seed_at(session, [timedelta(0)], "DEMO-VEH-001")

    assert service.list_vehicles(session) == ["DEMO-VEH-001", "demo-veh-001"]


@pytest.mark.parametrize(
    "vehicle_id",
    [pytest.param("V" * 32, id="TS-VEH-07-32-chars"), pytest.param("V", id="1-char")],
)
def test_list_vehicles_boundary_length_id_returned_intact(
    session: Session, vehicle_id: str
) -> None:
    """TS-VEH-07: Return 1-character and 32-character IDs unchanged."""
    seed_at(session, [timedelta(0)], vehicle_id)

    assert service.list_vehicles(session) == [vehicle_id]


def test_list_vehicles_after_prune_omits_vehicle_without_readings(
    session: Session,
) -> None:
    """TS-VEH-08: Drop a vehicle from the list once all its readings are pruned."""
    seed_at(session, [timedelta(0)], VEH1)
    seed_at(session, [sec(100)], VEH2)

    service.prune_older_than(session, T0 + sec(50))

    assert service.list_vehicles(session) == [VEH2]


def test_list_vehicles_repeated_calls_return_same_result_without_changes(
    session: Session,
) -> None:
    """TS-VEH-09: Return identical results twice and leave the row count unchanged."""
    seed_at(session, [sec(i) for i in range(3)], VEH1)

    first = service.list_vehicles(session)
    second = service.list_vehicles(session)

    assert first == second
    assert count(session) == 3


# --------------------------------------------------------------------------
# get_latest
# --------------------------------------------------------------------------


def test_get_latest_multiple_readings_returns_newest_with_all_fields(
    session: Session,
) -> None:
    """TS-LAT-01: Return the newest reading with all fields matching the input."""
    for i in range(3):
        service.add_reading(session, make_reading(ts=T0 + sec(i), speed_kmh=i * 10))

    latest = service.get_latest(session, VEH1)

    assert latest is not None
    assert latest.timestamp == T0 + sec(2)
    assert latest.speed_kmh == 20
    assert latest.vehicle_id == VEH1
    assert latest.engine_rpm == 2000
    assert latest.fuel_level_pct == 75.0
    assert latest.engine_temp_c == 90.0
    assert latest.latitude == 10.0
    assert latest.longitude == 20.0


def test_get_latest_out_of_order_inserts_returns_newest_timestamp(
    session: Session,
) -> None:
    """TS-LAT-02: Choose the newest reading by timestamp, not insertion order."""
    for offset in (2, 0, 1):
        service.add_reading(session, make_reading(ts=T0 + sec(offset)))

    latest = service.get_latest(session, VEH1)

    assert latest is not None
    assert latest.timestamp == T0 + sec(2)


def test_get_latest_empty_db_returns_none(session: Session) -> None:
    """TS-LAT-03: Return None when the database is empty."""
    assert service.get_latest(session, VEH1) is None


def test_get_latest_unknown_vehicle_returns_none(session: Session) -> None:
    """TS-LAT-04: Return None, without raising, for a vehicle with no readings."""
    seed_at(session, [timedelta(0)], VEH1)

    assert service.get_latest(session, "DEMO-VEH-999") is None


def test_get_latest_multiple_vehicles_returns_each_vehicles_own_newest(
    session: Session,
) -> None:
    """TS-LAT-05: Return each vehicle's own newest reading, unaffected by others."""
    seed_at(session, [timedelta(0), sec(1)], VEH1)
    seed_at(session, [timedelta(0), sec(5)], VEH2)

    latest1 = service.get_latest(session, VEH1)
    latest2 = service.get_latest(session, VEH2)

    assert latest1 is not None and latest1.timestamp == T0 + sec(1)
    assert latest2 is not None and latest2.timestamp == T0 + sec(5)


def test_get_latest_single_reading_returns_that_reading(session: Session) -> None:
    """TS-LAT-06: Return the only stored reading."""
    service.add_reading(session, make_reading(speed_kmh=33))

    latest = service.get_latest(session, VEH1)

    assert latest is not None
    assert latest.speed_kmh == 33


@pytest.mark.parametrize(
    "vehicle_id",
    [
        pytest.param("' OR '1'='1", id="TS-LAT-07-or-true"),
        pytest.param("x'; DROP TABLE telemetry_readings;--", id="drop-table"),
    ],
)
def test_get_latest_sql_injection_vehicle_id_returns_none_and_keeps_data(
    session: Session, vehicle_id: str
) -> None:
    """TS-LAT-07: Treat an injection-style vehicle_id as a literal and keep all rows."""
    seed_at(session, [timedelta(0), sec(1)], VEH1)

    assert service.get_latest(session, vehicle_id) is None
    assert count(session) == 2


def test_get_latest_stored_timestamp_returned_as_timezone_aware_utc(
    session: Session,
) -> None:
    """TS-LAT-08: Return a timezone-aware UTC timestamp equal to the stored instant."""
    seed_at(session, [timedelta(0)])

    latest = service.get_latest(session, VEH1)

    assert latest is not None
    assert latest.timestamp.tzinfo is not None
    assert latest.timestamp.utcoffset() == timedelta(0)
    assert latest.timestamp == T0


def test_get_latest_equal_timestamps_returns_highest_id_deterministically(
    session: Session,
) -> None:
    """TS-LAT-09: Break a timestamp tie by returning the row with the higher id."""
    seed(
        session,
        [make_reading(speed_kmh=10), make_reading(speed_kmh=20)],
    )

    results = [service.get_latest(session, VEH1) for _ in range(3)]

    assert all(r is not None and r.speed_kmh == 20 for r in results)
    assert results[0] == results[1] == results[2]


def test_get_latest_database_error_propagates(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TS-LAT-10: Propagate a SQLAlchemyError instead of returning None."""
    monkeypatch.setattr(session, "execute", raise_db_error)
    monkeypatch.setattr(session, "scalars", raise_db_error)

    with pytest.raises(SQLAlchemyError):
        service.get_latest(session, VEH1)


# --------------------------------------------------------------------------
# get_recent
# --------------------------------------------------------------------------


def test_get_recent_inserted_in_order_returns_oldest_to_newest(
    session: Session,
) -> None:
    """TS-REC-01: Return readings ordered by ascending timestamp."""
    seed_at(session, [sec(i) for i in range(5)])

    recent = service.get_recent(session, VEH1, 5)

    assert [r.timestamp for r in recent] == [T0 + sec(i) for i in range(5)]


def test_get_recent_shuffled_inserts_returns_ascending_timestamps(
    session: Session,
) -> None:
    """TS-REC-02: Order by timestamp even when rows were inserted out of order."""
    for i in (3, 0, 4, 1, 2):
        service.add_reading(session, make_reading(ts=T0 + sec(i)))

    recent = service.get_recent(session, VEH1, 5)

    assert [r.timestamp for r in recent] == [T0 + sec(i) for i in range(5)]


@pytest.mark.parametrize(
    ("rows", "limit", "expected_offsets"),
    [
        pytest.param(10, 3, [7, 8, 9], id="TS-REC-03-limit-below-count"),
        pytest.param(10, 1, [9], id="TS-REC-04-limit-one"),
        pytest.param(10, 10, list(range(10)), id="TS-REC-05-limit-equals-count"),
        pytest.param(10, 300, list(range(10)), id="TS-REC-06-limit-above-count"),
        pytest.param(100, 60, list(range(40, 100)), id="TS-REC-07-window-of-60"),
    ],
)
def test_get_recent_limit_returns_newest_rows_in_ascending_order(
    session: Session, rows: int, limit: int, expected_offsets: list[int]
) -> None:
    """TS-REC-03 to 07: Return the newest `limit` rows, oldest to newest."""
    seed_at(session, [sec(i) for i in range(rows)])

    recent = service.get_recent(session, VEH1, limit)

    assert [r.timestamp for r in recent] == [T0 + sec(i) for i in expected_offsets]


def test_get_recent_empty_db_returns_empty_list(session: Session) -> None:
    """TS-REC-08: Return an empty list when the database is empty."""
    result = service.get_recent(session, VEH1, 60)

    assert result == []
    assert isinstance(result, list)


def test_get_recent_vehicle_without_readings_returns_empty_list(
    session: Session,
) -> None:
    """TS-REC-09: Return an empty list for a vehicle when only others have data."""
    seed_at(session, [timedelta(0)], VEH2)

    assert service.get_recent(session, VEH1, 60) == []


def test_get_recent_interleaved_vehicles_returns_only_own_rows(
    session: Session,
) -> None:
    """TS-REC-10: Return only the requested vehicle's rows."""
    seed(
        session,
        [
            make_reading(vid, T0 + sec(i * 2 + j))
            for i in range(3)
            for j, vid in enumerate((VEH1, VEH2))
        ],
    )

    for vid in (VEH1, VEH2):
        recent = service.get_recent(session, vid, 10)
        assert len(recent) == 3
        assert {r.vehicle_id for r in recent} == {vid}


def test_get_recent_sql_injection_vehicle_id_returns_empty_and_keeps_data(
    session: Session,
) -> None:
    """TS-REC-11: Treat an injection-style vehicle_id as a literal and keep all rows."""
    seed_at(session, [timedelta(0), sec(1)], VEH1)

    assert service.get_recent(session, "' OR '1'='1", 10) == []
    assert count(session) == 2


@pytest.mark.skip(reason="TS-REC-12 pending clarification: [] or ValueError (A5)")
def test_get_recent_zero_limit_behavior_pending_clarification() -> None:
    """TS-REC-12: Placeholder until the limit=0 behaviour is decided."""
    raise NotImplementedError


@pytest.mark.skip(reason="TS-REC-13 pending clarification: [] or ValueError (A5)")
def test_get_recent_negative_limit_behavior_pending_clarification() -> None:
    """TS-REC-13: Placeholder until the negative-limit behaviour is decided."""
    raise NotImplementedError


def test_get_recent_readings_returns_schema_objects_with_all_fields(
    session: Session,
) -> None:
    """TS-REC-14: Return TelemetryReading objects with all stored field values."""
    inputs = [
        make_reading(
            ts=T0 + sec(i),
            speed_kmh=10.0 + i,
            engine_rpm=1000 + i,
            fuel_level_pct=50.0 - i,
            engine_temp_c=80.0 + i,
            latitude=1.5 + i,
            longitude=2.5 + i,
        )
        for i in range(3)
    ]
    seed(session, inputs)

    recent = service.get_recent(session, VEH1, 3)

    assert len(recent) == 3
    for item, expected in zip(recent, inputs, strict=True):
        assert isinstance(item, TelemetryReading)
        assert item.id is not None
        assert item.model_dump(exclude={"id"}) == expected.model_dump()


def test_get_recent_readings_returns_timezone_aware_utc_timestamps(
    session: Session,
) -> None:
    """TS-REC-15: Return only timezone-aware UTC timestamps."""
    seed_at(session, [sec(i) for i in range(3)])

    for item in service.get_recent(session, VEH1, 3):
        assert item.timestamp.tzinfo is not None
        assert item.timestamp.utcoffset() == timedelta(0)


def test_get_recent_equal_timestamps_orders_by_ascending_id(session: Session) -> None:
    """TS-REC-16: Order rows with equal timestamps by ascending id on every run."""
    seed(session, [make_reading(speed_kmh=s) for s in (1, 2, 3)])

    runs = [
        [r.speed_kmh for r in service.get_recent(session, VEH1, 3)] for _ in range(3)
    ]

    assert runs == [[1, 2, 3]] * 3


def test_get_recent_large_history_returns_newest_300_ascending(
    session: Session,
) -> None:
    """TS-REC-17: Limit a 1000-row history to the newest 300 rows, ascending."""
    seed_at(session, [sec(i) for i in range(1000)])

    recent = service.get_recent(session, VEH1, 300)

    assert [r.timestamp for r in recent] == [T0 + sec(i) for i in range(700, 1000)]


def test_get_recent_repeated_calls_return_same_result_without_changes(
    session: Session,
) -> None:
    """TS-REC-18: Return identical results twice and leave the row count unchanged."""
    seed_at(session, [sec(i) for i in range(5)])

    first = service.get_recent(session, VEH1, 5)
    second = service.get_recent(session, VEH1, 5)

    assert first == second
    assert count(session) == 5


def test_get_recent_database_error_propagates(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TS-REC-19: Propagate a SQLAlchemyError raised by the query."""
    monkeypatch.setattr(session, "execute", raise_db_error)
    monkeypatch.setattr(session, "scalars", raise_db_error)

    with pytest.raises(SQLAlchemyError):
        service.get_recent(session, VEH1, 10)


# --------------------------------------------------------------------------
# prune_older_than
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offsets", "cutoff", "deleted", "remaining"),
    [
        pytest.param(
            [sec(0), sec(60), sec(120), sec(180), sec(240)],
            sec(120),
            2,
            [sec(120), sec(180), sec(240)],
            id="TS-PRU-01-removes-only-older",
        ),
        pytest.param(
            [-sec(1), sec(0), sec(1)],
            sec(0),
            1,
            [sec(0), sec(1)],
            id="TS-PRU-02-cutoff-row-kept",
        ),
        pytest.param(
            [-timedelta(microseconds=1), sec(0)],
            sec(0),
            1,
            [sec(0)],
            id="TS-PRU-03-one-microsecond-older-removed",
        ),
        pytest.param(
            [sec(0), sec(1), sec(2)],
            -timedelta(hours=1),
            0,
            [sec(0), sec(1), sec(2)],
            id="TS-PRU-04-nothing-older",
        ),
        pytest.param(
            [sec(0), sec(1), sec(2)],
            timedelta(hours=1),
            3,
            [],
            id="TS-PRU-05-all-older",
        ),
        pytest.param([], sec(0), 0, [], id="TS-PRU-06-empty-table"),
        pytest.param(
            [sec(0), sec(60)],
            sec(30),
            1,
            [sec(60)],
            id="TS-PRU-12-tz-aware-cutoff",
        ),
    ],
)
def test_prune_older_than_cutoff_deletes_only_strictly_older_rows(
    session: Session,
    offsets: list[timedelta],
    cutoff: timedelta,
    deleted: int,
    remaining: list[timedelta],
) -> None:
    """TS-PRU-01 to 06, 12: Delete only rows older than the cutoff; return the count."""
    seed_at(session, offsets)

    result = service.prune_older_than(session, T0 + cutoff)

    assert result == deleted
    assert isinstance(result, int)
    assert timestamps(session) == [T0 + o for o in remaining]


def test_prune_older_than_all_rows_older_leaves_no_latest_or_vehicles(
    session: Session,
) -> None:
    """TS-PRU-05: Leave an empty table with no latest reading and no vehicles."""
    seed_at(session, [sec(0), sec(1), sec(2)])

    service.prune_older_than(session, T0 + timedelta(hours=1))

    assert count(session) == 0
    assert service.get_latest(session, VEH1) is None
    assert service.list_vehicles(session) == []


def test_prune_older_than_multiple_vehicles_prunes_all_old_rows(
    session: Session,
) -> None:
    """TS-PRU-07: Remove old rows of every vehicle and keep the new ones."""
    for vid in (VEH1, VEH2):
        seed_at(session, [sec(0), sec(30), sec(120), sec(150)], vid)

    deleted = service.prune_older_than(session, T0 + sec(60))

    assert deleted == 4
    for vid in (VEH1, VEH2):
        assert timestamps(session, vid) == [T0 + sec(120), T0 + sec(150)]


def test_prune_older_than_large_batch_returns_exact_deleted_count(
    session: Session,
) -> None:
    """TS-PRU-08: Return 500 for a 500-row delete and keep the 20 newer rows."""
    seed_at(session, [sec(i) for i in range(500)])
    seed_at(session, [sec(10_000 + i) for i in range(20)])

    deleted = service.prune_older_than(session, T0 + sec(5_000))

    assert deleted == 500
    assert count(session) == 20


def test_prune_older_than_commit_visible_from_separate_session(
    file_engine: Engine,
) -> None:
    """TS-PRU-09: Make the deletion visible to a second session (committed)."""
    factory = create_session_factory(file_engine)
    with factory() as session_a, factory() as session_b:
        seed_at(session_a, [sec(0), sec(1), sec(100)])
        assert count(session_b) == 3

        service.prune_older_than(session_a, T0 + sec(50))

        assert count(session_b) == 1


def test_prune_older_than_repeated_call_returns_zero_and_keeps_rows(
    session: Session,
) -> None:
    """TS-PRU-10: Delete nothing on a repeated call with the same cutoff."""
    seed_at(session, [sec(0), sec(1), sec(100), sec(101)])
    cutoff = T0 + sec(50)

    first = service.prune_older_than(session, cutoff)
    remaining_after_first = timestamps(session)
    second = service.prune_older_than(session, cutoff)

    assert first == 2
    assert second == 0
    assert timestamps(session) == remaining_after_first


def test_prune_older_than_retention_cutoff_from_fixed_clock_keeps_cutoff_row(
    session: Session,
) -> None:
    """TS-PRU-11: Delete only rows older than a fixed-clock retention cutoff."""
    now = T0 + timedelta(hours=2)
    retention_minutes = 60
    seed_at(session, [sec(0), timedelta(hours=1), timedelta(minutes=90)])
    cutoff = now - timedelta(minutes=retention_minutes)

    deleted = service.prune_older_than(session, cutoff)

    assert deleted == 1
    assert timestamps(session) == [T0 + timedelta(hours=1), T0 + timedelta(minutes=90)]


@pytest.mark.skip(reason="TS-PRU-13 pending clarification: naive cutoff (A7b)")
def test_prune_older_than_naive_cutoff_behavior_pending_clarification() -> None:
    """TS-PRU-13: Placeholder until naive-cutoff handling is decided."""
    raise NotImplementedError


@pytest.mark.skip(reason="TS-PRU-14 exception type for non-datetime cutoff (A5)")
def test_prune_older_than_non_datetime_cutoff_pending_clarification() -> None:
    """TS-PRU-14: Placeholder until the exception type for bad cutoffs is decided."""
    raise NotImplementedError


def test_prune_older_than_delete_failure_propagates_and_keeps_rows(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TS-PRU-15: Propagate a delete error and keep all rows after rollback."""
    seed_at(session, [sec(0), sec(1), sec(2)])
    monkeypatch.setattr(session, "execute", raise_db_error)

    with pytest.raises(SQLAlchemyError):
        service.prune_older_than(session, T0)

    monkeypatch.undo()
    session.rollback()
    assert count(session) == 3


def test_prune_older_than_mixed_history_keeps_other_vehicles_newer_rows(
    session: Session,
) -> None:
    """TS-PRU-16: Leave another vehicle's newer rows untouched."""
    seed_at(session, [sec(0), sec(100)], VEH1)
    seed_at(session, [sec(70), sec(80), sec(90)], VEH2)
    before = service.get_recent(session, VEH2, 10)

    service.prune_older_than(session, T0 + sec(50))

    assert service.get_recent(session, VEH2, 10) == before
    assert timestamps(session, VEH1) == [T0 + sec(100)]


# --------------------------------------------------------------------------
# Service integration (no HTTP)
# --------------------------------------------------------------------------


def test_service_lifecycle_add_query_prune_returns_expected_results(
    session: Session,
) -> None:
    """TS-INT-01: Return expected results at each add, query and prune step."""
    for offset in (0, 60):
        service.add_reading(session, make_reading(VEH1, T0 + sec(offset)))
    for offset in (600, 660, 720):
        service.add_reading(session, make_reading(VEH2, T0 + sec(offset)))

    assert service.list_vehicles(session) == [VEH1, VEH2]
    latest1 = service.get_latest(session, VEH1)
    latest2 = service.get_latest(session, VEH2)
    assert latest1 is not None and latest1.timestamp == T0 + sec(60)
    assert latest2 is not None and latest2.timestamp == T0 + sec(720)
    assert len(service.get_recent(session, VEH1, 10)) == 2
    assert len(service.get_recent(session, VEH2, 2)) == 2

    assert service.prune_older_than(session, T0 + sec(300)) == 2

    assert service.list_vehicles(session) == [VEH2]
    assert service.get_latest(session, VEH1) is None
    assert service.get_recent(session, VEH1, 10) == []
    latest2_after = service.get_latest(session, VEH2)
    assert latest2_after == latest2
    assert len(service.get_recent(session, VEH2, 10)) == 3


def test_service_module_imports_no_api_simulator_or_fastapi() -> None:
    """TS-INT-02: Import no API, main, simulator or FastAPI module."""
    tree = ast.parse(Path(inspect.getsourcefile(service) or "").read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = (
        "fastapi",
        "telemetry.api",
        "telemetry.main",
        "telemetry.services.simulator",
    )
    assert [m for m in imported if m.startswith(forbidden)] == []


@pytest.mark.parametrize("func", SERVICE_FUNCTIONS, ids=lambda f: f.__name__)
def test_service_function_signature_is_session_first_annotated_and_documented(
    func: Callable[..., Any],
) -> None:
    """TS-INT-03: Take session first, be fully type-annotated and have a docstring."""
    signature = inspect.signature(func)
    params = list(signature.parameters.values())

    assert params[0].name == "session"
    assert all(p.annotation is not inspect.Parameter.empty for p in params)
    assert signature.return_annotation is not inspect.Signature.empty
    assert inspect.getdoc(func)


def test_service_module_type_checks_clean_under_mypy() -> None:
    """TS-INT-03: Pass mypy in strict mode with no reported issues."""
    mypy_api = pytest.importorskip("mypy.api")
    root = Path(__file__).resolve().parents[2]

    stdout, _stderr, status = mypy_api.run(
        [
            "--config-file",
            str(root / "pyproject.toml"),
            "--no-incremental",
            str(root / "src" / "telemetry" / "services" / "telemetry.py"),
        ]
    )

    assert status == 0, stdout
