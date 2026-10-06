"""Pydantic schemas for telemetry readings."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

VEHICLE_ID_PATTERN = r"^[A-Za-z0-9_-]+$"


def ensure_utc(value: datetime) -> datetime:
    """Return `value` as a UTC-aware datetime (naive values are assumed UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class TelemetryReadingCreate(BaseModel):
    """A telemetry reading before it has been stored (no `id`)."""

    vehicle_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=VEHICLE_ID_PATTERN,
        examples=["DEMO-VEH-001"],
    )
    timestamp: datetime
    speed_kmh: float = Field(ge=0, le=250)
    engine_rpm: int = Field(ge=0, le=8000)
    fuel_level_pct: float = Field(ge=0, le=100)
    engine_temp_c: float = Field(ge=-40, le=150)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("timestamp")
    @classmethod
    def _normalise_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class TelemetryReading(TelemetryReadingCreate):
    """A stored telemetry reading."""

    model_config = ConfigDict(from_attributes=True)

    id: int
