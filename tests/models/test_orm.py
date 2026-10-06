from collections.abc import Callable

from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from telemetry.models.orm import TelemetryReadingORM
from telemetry.models.schemas import TelemetryReading, TelemetryReadingCreate

Factory = Callable[..., TelemetryReadingCreate]


def test_insert_and_read_round_trip(session: Session, make_reading: Factory) -> None:
    reading = make_reading()

    session.add(TelemetryReadingORM.from_schema(reading))
    session.commit()
    session.expire_all()
    row = session.scalars(select(TelemetryReadingORM)).one()
    stored = TelemetryReading.model_validate(row)

    assert stored.id == 1
    assert stored.model_dump(exclude={"id"}) == reading.model_dump()
    assert stored.timestamp.tzinfo is not None


def test_from_schema_copies_all_fields(make_reading: Factory) -> None:
    reading = make_reading(vehicle_id="DEMO-VEH-007", engine_rpm=8000)

    row = TelemetryReadingORM.from_schema(reading)

    assert row.id is None
    assert row.vehicle_id == "DEMO-VEH-007"
    assert row.engine_rpm == 8000
    assert row.timestamp == reading.timestamp


def test_vehicle_timestamp_index_exists(engine: Engine) -> None:
    indexes = inspect(engine).get_indexes("telemetry_readings")

    assert any(i["column_names"] == ["vehicle_id", "timestamp"] for i in indexes)
