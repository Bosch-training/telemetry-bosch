"""SQLAlchemy models."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from telemetry.models.schemas import TelemetryReadingCreate


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TelemetryReadingORM(Base):
    """Persisted telemetry reading."""

    __tablename__ = "telemetry_readings"
    __table_args__ = (
        Index("ix_telemetry_vehicle_timestamp", "vehicle_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(String(32))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    speed_kmh: Mapped[float]
    engine_rpm: Mapped[int]
    fuel_level_pct: Mapped[float]
    engine_temp_c: Mapped[float]
    latitude: Mapped[float]
    longitude: Mapped[float]

    @classmethod
    def from_schema(cls, reading: TelemetryReadingCreate) -> "TelemetryReadingORM":
        """Build an ORM row from a validated schema object."""
        return cls(**reading.model_dump())
