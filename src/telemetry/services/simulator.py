"""Deterministic, side-effect-free generator of simulated vehicle telemetry."""

import random
from datetime import datetime

from pydantic import ValidationError

from telemetry.models.schemas import TelemetryReadingCreate

# Fake, hardcoded loop in a generic location; not real vehicle GPS data.
ROUTE_LOOP = (
    (50.0000, 10.0000),
    (50.0000, 10.0100),
    (50.0000, 10.0200),
    (50.0100, 10.0200),
    (50.0200, 10.0200),
    (50.0200, 10.0100),
    (50.0200, 10.0000),
    (50.0100, 10.0000),
)

SPEED_STEP_KMH = 5.0
SPEED_START_KMH = 30.0
SPEED_MAX_KMH = 120.0
IDLE_RPM = 800.0
RPM_PER_KMH = 30.0
RPM_NOISE_SIGMA = 100.0
RPM_MAX = 8000
FUEL_START_PCT = 100.0
FUEL_STEP_PCT = 0.005
TEMP_AMBIENT_C = 20.0
TEMP_TARGET_C = 90.0
TEMP_APPROACH_RATE = 0.01
TEMP_NOISE_SIGMA = 0.5


def make_vehicle_ids(count: int) -> list[str]:
    """Return `count` demo vehicle IDs, e.g. `DEMO-VEH-001`, in order."""
    return [f"DEMO-VEH-{i:03d}" for i in range(1, count + 1)]


class VehicleSimulator:
    """Generates readings for one vehicle from an injected random source."""

    def __init__(
        self, vehicle_id: str, rng: random.Random, start_index: int = 0
    ) -> None:
        """Create a simulator whose route starts at `start_index` (wrapped)."""
        self._vehicle_id = vehicle_id
        self._rng = rng
        self._speed_kmh = SPEED_START_KMH
        self._fuel_level_pct = FUEL_START_PCT
        self._engine_temp_c = TEMP_AMBIENT_C
        self._route_index = start_index % len(ROUTE_LOOP)

    def next_reading(self, now: datetime) -> TelemetryReadingCreate | None:
        """Advance the state one tick; return `None` if the reading is invalid."""
        speed = self._step_speed()
        rpm = self._rpm_for(speed)
        fuel = self._step_fuel()
        temp = self._step_temp()
        latitude, longitude = self._step_position()
        try:
            return TelemetryReadingCreate.model_validate(
                {
                    "vehicle_id": self._vehicle_id,
                    "timestamp": now,
                    "speed_kmh": speed,
                    "engine_rpm": rpm,
                    "fuel_level_pct": fuel,
                    "engine_temp_c": temp,
                    "latitude": latitude,
                    "longitude": longitude,
                }
            )
        except ValidationError:
            return None

    def _step_speed(self) -> float:
        step = self._rng.uniform(-SPEED_STEP_KMH, SPEED_STEP_KMH)
        self._speed_kmh = min(SPEED_MAX_KMH, max(0.0, self._speed_kmh + step))
        return self._speed_kmh

    def _rpm_for(self, speed: float) -> int:
        noise = self._rng.gauss(0.0, RPM_NOISE_SIGMA)
        # Clamp before rounding so NaN/inf speeds cannot raise (speed is dropped).
        raw = IDLE_RPM + speed * RPM_PER_KMH + noise
        return round(min(float(RPM_MAX), max(0.0, raw)))

    def _step_fuel(self) -> float:
        self._fuel_level_pct = max(0.0, self._fuel_level_pct - FUEL_STEP_PCT)
        return self._fuel_level_pct

    def _step_temp(self) -> float:
        self._engine_temp_c += TEMP_APPROACH_RATE * (
            TEMP_TARGET_C - self._engine_temp_c
        )
        return self._engine_temp_c + self._rng.gauss(0.0, TEMP_NOISE_SIGMA)

    def _step_position(self) -> tuple[float, float]:
        position = ROUTE_LOOP[self._route_index]
        self._route_index = (self._route_index + 1) % len(ROUTE_LOOP)
        return position
