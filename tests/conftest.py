"""Shared fixtures (in-memory SQLite, fake data only)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from telemetry.models.database import (
    create_db_engine,
    create_session_factory,
    init_db,
)
from telemetry.models.schemas import TelemetryReadingCreate

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_db_engine("sqlite://")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


@pytest.fixture
def make_reading() -> Callable[..., TelemetryReadingCreate]:
    def _make(**overrides: object) -> TelemetryReadingCreate:
        data: dict[str, object] = {
            "vehicle_id": "DEMO-VEH-001",
            "timestamp": BASE_TIME,
            "speed_kmh": 50.0,
            "engine_rpm": 2000,
            "fuel_level_pct": 75.0,
            "engine_temp_c": 90.0,
            "latitude": 10.0,
            "longitude": 20.0,
        }
        data.update(overrides)
        return TelemetryReadingCreate.model_validate(data)

    return _make
