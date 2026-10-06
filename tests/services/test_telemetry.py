from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from telemetry.models.schemas import TelemetryReadingCreate
from telemetry.services import telemetry as service
from tests.conftest import BASE_TIME

Factory = Callable[..., TelemetryReadingCreate]


def _seed(session: Session, make_reading: Factory, vehicle_id: str, count: int) -> None:
    for i in range(count):
        service.add_reading(
            session,
            make_reading(
                vehicle_id=vehicle_id,
                timestamp=BASE_TIME + timedelta(seconds=i),
                speed_kmh=float(i),
            ),
        )


def test_add_reading_returns_stored_reading(
    session: Session, make_reading: Factory
) -> None:
    stored = service.add_reading(session, make_reading())

    assert stored.id == 1
    assert stored.vehicle_id == "DEMO-VEH-001"
    assert stored.timestamp == BASE_TIME


def test_empty_database(session: Session) -> None:
    assert service.list_vehicles(session) == []
    assert service.get_latest(session, "DEMO-VEH-001") is None
    assert service.get_recent(session, "DEMO-VEH-001", 10) == []


def test_list_vehicles_distinct_and_sorted(
    session: Session, make_reading: Factory
) -> None:
    _seed(session, make_reading, "DEMO-VEH-002", 2)
    _seed(session, make_reading, "DEMO-VEH-001", 3)

    assert service.list_vehicles(session) == ["DEMO-VEH-001", "DEMO-VEH-002"]


def test_get_latest_returns_newest(session: Session, make_reading: Factory) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 5)

    latest = service.get_latest(session, "DEMO-VEH-001")

    assert latest is not None
    assert latest.speed_kmh == 4.0


def test_get_latest_uses_timestamp_not_insert_order(
    session: Session, make_reading: Factory
) -> None:
    service.add_reading(
        session, make_reading(timestamp=BASE_TIME + timedelta(hours=1), speed_kmh=9)
    )
    service.add_reading(session, make_reading(timestamp=BASE_TIME, speed_kmh=1))

    latest = service.get_latest(session, "DEMO-VEH-001")

    assert latest is not None
    assert latest.speed_kmh == 9


@pytest.mark.parametrize(("limit", "expected"), [(1, 1), (5, 5), (50, 5)])
def test_get_recent_honours_limit(
    session: Session, make_reading: Factory, limit: int, expected: int
) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 5)

    assert len(service.get_recent(session, "DEMO-VEH-001", limit)) == expected


def test_get_recent_is_oldest_to_newest_and_keeps_newest_rows(
    session: Session, make_reading: Factory
) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 5)

    recent = service.get_recent(session, "DEMO-VEH-001", 3)

    assert [r.speed_kmh for r in recent] == [2.0, 3.0, 4.0]
    assert [r.timestamp for r in recent] == sorted(r.timestamp for r in recent)


def test_vehicles_are_isolated(session: Session, make_reading: Factory) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 3)
    _seed(session, make_reading, "DEMO-VEH-002", 1)

    assert len(service.get_recent(session, "DEMO-VEH-001", 10)) == 3
    assert len(service.get_recent(session, "DEMO-VEH-002", 10)) == 1
    assert service.get_recent(session, "DEMO-VEH-999", 10) == []
    assert service.get_latest(session, "DEMO-VEH-999") is None


def test_prune_removes_only_older_rows_and_keeps_boundary(
    session: Session, make_reading: Factory
) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 5)
    cutoff = BASE_TIME + timedelta(seconds=2)

    deleted = service.prune_older_than(session, cutoff)

    remaining = service.get_recent(session, "DEMO-VEH-001", 10)
    assert deleted == 2
    assert [r.timestamp for r in remaining][0] == cutoff
    assert len(remaining) == 3


def test_prune_nothing_to_delete(session: Session, make_reading: Factory) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 2)

    assert service.prune_older_than(session, BASE_TIME - timedelta(days=1)) == 0
    assert len(service.get_recent(session, "DEMO-VEH-001", 10)) == 2


def test_prune_accepts_naive_cutoff_as_utc(
    session: Session, make_reading: Factory
) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 3)

    deleted = service.prune_older_than(
        session, (BASE_TIME + timedelta(seconds=1)).replace(tzinfo=None)
    )

    assert deleted == 1


def test_sql_metacharacters_in_vehicle_id_are_inert(
    session: Session, make_reading: Factory
) -> None:
    _seed(session, make_reading, "DEMO-VEH-001", 1)

    assert service.get_latest(session, "' OR '1'='1") is None
    assert service.get_recent(session, "x'; DROP TABLE telemetry_readings;--", 5) == []
    assert service.list_vehicles(session) == ["DEMO-VEH-001"]
