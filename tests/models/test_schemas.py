from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from telemetry.models.schemas import TelemetryReading, TelemetryReadingCreate

Factory = Callable[..., TelemetryReadingCreate]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("speed_kmh", 0),
        ("speed_kmh", 250),
        ("engine_rpm", 0),
        ("engine_rpm", 8000),
        ("fuel_level_pct", 0),
        ("fuel_level_pct", 100),
        ("engine_temp_c", -40),
        ("engine_temp_c", 150),
        ("latitude", -90),
        ("latitude", 90),
        ("longitude", -180),
        ("longitude", 180),
    ],
)
def test_boundary_values_accepted(
    make_reading: Factory, field: str, value: float
) -> None:
    assert getattr(make_reading(**{field: value}), field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("speed_kmh", -0.1),
        ("speed_kmh", 250.1),
        ("engine_rpm", -1),
        ("engine_rpm", 8001),
        ("fuel_level_pct", -0.1),
        ("fuel_level_pct", 100.1),
        ("engine_temp_c", -40.1),
        ("engine_temp_c", 150.1),
        ("latitude", -90.1),
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("longitude", 180.1),
        ("speed_kmh", float("nan")),
        ("speed_kmh", "fast"),
    ],
)
def test_out_of_range_rejected(
    make_reading: Factory, field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        make_reading(**{field: value})


@pytest.mark.parametrize("vehicle_id", ["A", "DEMO-VEH-001", "a_b-9", "x" * 32])
def test_valid_vehicle_ids(make_reading: Factory, vehicle_id: str) -> None:
    assert make_reading(vehicle_id=vehicle_id).vehicle_id == vehicle_id


@pytest.mark.parametrize(
    "vehicle_id", ["", "x" * 33, "bad id", "a;b", "<script>", "../etc", "ü"]
)
def test_invalid_vehicle_ids(make_reading: Factory, vehicle_id: str) -> None:
    with pytest.raises(ValidationError):
        make_reading(vehicle_id=vehicle_id)


def test_naive_timestamp_assumed_utc(make_reading: Factory) -> None:
    reading = make_reading(timestamp=datetime(2026, 1, 1, 12, 0, 0))

    assert reading.timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert reading.timestamp.utcoffset() == timedelta(0)


def test_aware_timestamp_converted_to_utc(make_reading: Factory) -> None:
    local = datetime(
        2026, 1, 1, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )

    reading = make_reading(timestamp=local)

    assert reading.timestamp == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert reading.timestamp.utcoffset() == timedelta(0)


def test_invalid_timestamp_rejected(make_reading: Factory) -> None:
    with pytest.raises(ValidationError):
        make_reading(timestamp="not-a-date")


def test_missing_field_rejected() -> None:
    with pytest.raises(ValidationError):
        TelemetryReadingCreate.model_validate({"vehicle_id": "DEMO-VEH-001"})


def test_create_variant_has_no_id_and_stored_variant_requires_it(
    make_reading: Factory,
) -> None:
    create = make_reading()

    assert "id" not in TelemetryReadingCreate.model_fields
    with pytest.raises(ValidationError):
        TelemetryReading.model_validate(create.model_dump())
    assert TelemetryReading.model_validate({**create.model_dump(), "id": 1}).id == 1
