"""Data-access service for telemetry readings."""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.orm import Session

from telemetry.models.orm import TelemetryReadingORM
from telemetry.models.schemas import (
    TelemetryReading,
    TelemetryReadingCreate,
    ensure_utc,
)


def add_reading(session: Session, reading: TelemetryReadingCreate) -> TelemetryReading:
    """Store a validated reading and return it with its generated `id`."""
    row = TelemetryReadingORM.from_schema(reading)
    session.add(row)
    session.commit()
    return TelemetryReading.model_validate(row)


def list_vehicles(session: Session) -> list[str]:
    """Return the distinct vehicle IDs, sorted."""
    stmt = (
        select(TelemetryReadingORM.vehicle_id)
        .distinct()
        .order_by(TelemetryReadingORM.vehicle_id)
    )
    return list(session.scalars(stmt))


def get_latest(session: Session, vehicle_id: str) -> TelemetryReading | None:
    """Return the newest reading for a vehicle, or `None` if there is none."""
    stmt = (
        select(TelemetryReadingORM)
        .where(TelemetryReadingORM.vehicle_id == vehicle_id)
        .order_by(TelemetryReadingORM.timestamp.desc(), TelemetryReadingORM.id.desc())
        .limit(1)
    )
    row = session.scalars(stmt).first()
    return TelemetryReading.model_validate(row) if row else None


def get_recent(session: Session, vehicle_id: str, limit: int) -> list[TelemetryReading]:
    """Return the newest `limit` readings for a vehicle, oldest to newest."""
    stmt = (
        select(TelemetryReadingORM)
        .where(TelemetryReadingORM.vehicle_id == vehicle_id)
        .order_by(TelemetryReadingORM.timestamp.desc(), TelemetryReadingORM.id.desc())
        .limit(limit)
    )
    rows = session.scalars(stmt).all()
    return [TelemetryReading.model_validate(row) for row in reversed(rows)]


def prune_older_than(session: Session, cutoff: datetime) -> int:
    """Delete readings strictly older than `cutoff`; return the deleted count."""
    stmt = delete(TelemetryReadingORM).where(
        TelemetryReadingORM.timestamp < ensure_utc(cutoff)
    )
    result = cast("CursorResult[Any]", session.execute(stmt))
    session.commit()
    return result.rowcount
