"""Simulator-core tests, one case per row of
docs/telemetry-simulator-core-testspec.csv (fake data only).

Rows that are pending clarification, manual or out of scope (TS-VID-07/08,
TS-INI-05/06, TS-DRP-06/09, TS-GPS-09, TS-PUR-06, TS-INT-04) are skipped.

Tuning constants are unspecified (ASM-S1), so they are derived from observed
output or from the arguments passed to the injected RNG. Tests that script
`gauss()` assume the LLD section 5 order within a tick: speed, rpm, fuel, temp,
so gauss call 0 of each tick is the RPM noise and call 1 the temperature noise.
"""

import ast
import importlib
import inspect
import logging
import math
import random
import re
import statistics
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from telemetry.models.schemas import (
    VEHICLE_ID_PATTERN,
    TelemetryReading,
    TelemetryReadingCreate,
)
from telemetry.services import simulator as sim_mod
from telemetry.services.simulator import (
    ROUTE_LOOP,
    VehicleSimulator,
    make_vehicle_ids,
)
from tests.conftest import BASE_TIME as T0

VEH1 = "DEMO-VEH-001"
VEH2 = "DEMO-VEH-002"
ROUTE_LEN = len(ROUTE_LOOP)
SEEDS = [0, 1, 7, 42, 12345]
FORBIDDEN_IMPORTS = (
    "sqlalchemy",
    "fastapi",
    "threading",
    "asyncio",
    "telemetry.api",
    "telemetry.main",
    "telemetry.services.telemetry",
)
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "datetime.now",
    "datetime.utcnow",
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
    "time.time",
    "time.sleep",
}


class ScriptedRandom(random.Random):
    """Seeded Random whose uniform() / gauss() can be forced and recorded."""

    def __init__(
        self,
        uniform_mode: str = "real",
        gauss_fn: Callable[[int], float] | None = None,
        seed: int = 42,
    ) -> None:
        super().__init__(seed)
        self.uniform_mode = uniform_mode
        self.gauss_fn = gauss_fn
        self.uniform_calls: list[tuple[float, float]] = []
        self.gauss_calls = 0

    def uniform(self, a: float, b: float) -> float:
        self.uniform_calls.append((a, b))
        if self.uniform_mode == "low":
            return a
        if self.uniform_mode == "high":
            return b
        if self.uniform_mode == "mid":
            return (a + b) / 2
        return super().uniform(a, b)

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        index = self.gauss_calls
        self.gauss_calls += 1
        if self.gauss_fn is None:
            return super().gauss(mu, sigma)
        return self.gauss_fn(index)


def rpm_noise(value: float) -> Callable[[int], float]:
    """Noise on the RPM gauss call of every tick (even calls), 0 on temperature."""
    return lambda i: value if i % 2 == 0 else 0.0


def zero_noise(_index: int) -> float:
    return 0.0


def tick_time(n: int, t0: datetime = T0) -> datetime:
    return t0 + timedelta(seconds=n)


def make_sim(
    vehicle_id: str = VEH1,
    seed: int = 42,
    start_index: int = 0,
    rng: random.Random | None = None,
) -> VehicleSimulator:
    return VehicleSimulator(
        vehicle_id, rng if rng is not None else random.Random(seed), start_index
    )


def run(
    sim: VehicleSimulator, n: int, t0: datetime = T0
) -> list[TelemetryReadingCreate | None]:
    return [sim.next_reading(tick_time(i, t0)) for i in range(n)]


def run_valid(
    sim: VehicleSimulator, n: int, t0: datetime = T0
) -> list[TelemetryReadingCreate]:
    readings = [r for r in run(sim, n, t0) if r is not None]
    assert len(readings) == n, "unexpected dropped readings"
    return readings


@cache
def cached_run(seed: int, n: int) -> tuple[TelemetryReadingCreate, ...]:
    """Deterministic seeded run shared by read-only statistical tests."""
    return tuple(run_valid(make_sim(seed=seed), n))


def assert_in_ranges(readings: tuple[TelemetryReadingCreate, ...] | list[Any]) -> None:
    for r in readings:
        assert 0 <= r.speed_kmh <= 250
        assert 0 <= r.engine_rpm <= 8000
        assert 0 <= r.fuel_level_pct <= 100
        assert -40 <= r.engine_temp_c <= 150
        assert -90 <= r.latitude <= 90
        assert -180 <= r.longitude <= 180


def position(r: TelemetryReadingCreate) -> tuple[float, float]:
    return (r.latitude, r.longitude)


def route_offset(first: TelemetryReadingCreate, start: int) -> int:
    """Index shift of the first reading from start_index (assumption S3)."""
    return (ROUTE_LOOP.index(position(first)) - start) % ROUTE_LEN


def force(
    monkeypatch: pytest.MonkeyPatch, sim: VehicleSimulator, name: str, value: Any
) -> None:
    monkeypatch.setattr(sim, name, lambda *_a, **_k: value)


def idle_rpm() -> int:
    """RPM at zero speed with no noise."""
    rng = ScriptedRandom("low", zero_noise)
    return run_valid(make_sim(rng=rng), 300)[-1].engine_rpm


# --- make_vehicle_ids -------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        pytest.param(2, ["DEMO-VEH-001", "DEMO-VEH-002"], id="TS-VID-01-two"),
        pytest.param(1, ["DEMO-VEH-001"], id="TS-VID-02-min"),
        pytest.param(
            10, [f"DEMO-VEH-{i:03d}" for i in range(1, 11)], id="TS-VID-03-max"
        ),
    ],
)
def test_make_vehicle_ids_values(count: int, expected: list[str]) -> None:
    assert make_vehicle_ids(count) == expected


def test_vid_04_unique_list_of_str() -> None:
    ids = make_vehicle_ids(10)

    assert isinstance(ids, list)
    assert len(set(ids)) == 10
    assert all(isinstance(i, str) for i in ids)


def test_vid_05_ids_accepted_by_schema() -> None:
    for vehicle_id in make_vehicle_ids(10):
        reading = TelemetryReadingCreate(
            vehicle_id=vehicle_id,
            timestamp=T0,
            speed_kmh=10.0,
            engine_rpm=1000,
            fuel_level_pct=50.0,
            engine_temp_c=80.0,
            latitude=10.0,
            longitude=20.0,
        )
        assert re.match(VEHICLE_ID_PATTERN, reading.vehicle_id)
        assert 1 <= len(reading.vehicle_id) <= 32


def test_vid_06_deterministic() -> None:
    assert make_vehicle_ids(5) == make_vehicle_ids(5)


# --- constructor ------------------------------------------------------------


def test_ini_01_constructor_accepts_optional_start_index() -> None:
    assert VehicleSimulator(VEH1, random.Random(42)) is not None
    assert VehicleSimulator(VEH1, random.Random(42), start_index=3) is not None


def test_ini_02_constructor_does_not_consume_rng() -> None:
    rng1, rng2 = random.Random(42), random.Random(42)

    make_sim(rng=rng1)

    assert rng1.random() == rng2.random()


def test_ini_03_missing_rng_rejected() -> None:
    with pytest.raises(TypeError):
        VehicleSimulator(VEH1)  # type: ignore[call-arg]


def test_ini_04_start_index_wraps() -> None:
    wrapped = make_sim(start_index=ROUTE_LEN + 2).next_reading(T0)
    plain = make_sim(start_index=2).next_reading(T0)

    assert wrapped is not None and plain is not None
    assert position(wrapped) == position(plain)


# --- next_reading basics ----------------------------------------------------


def test_nxt_01_returns_create_schema() -> None:
    reading = make_sim().next_reading(T0)

    assert isinstance(reading, TelemetryReadingCreate)


def test_nxt_02_vehicle_id_matches() -> None:
    reading = make_sim(vehicle_id=VEH2).next_reading(T0)

    assert reading is not None
    assert reading.vehicle_id == VEH2


def test_nxt_03_timestamp_equals_now_utc() -> None:
    now = T0.replace(microsecond=123456)

    reading = make_sim().next_reading(now)

    assert reading is not None
    assert reading.timestamp == now
    assert reading.timestamp.utcoffset() == timedelta(0)


def test_nxt_04_non_utc_now_normalised() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))

    reading = make_sim().next_reading(T0.astimezone(ist))

    assert reading is not None
    assert reading.timestamp == T0
    assert reading.timestamp.utcoffset() == timedelta(0)


def test_nxt_05_naive_now_treated_as_utc() -> None:
    reading = make_sim().next_reading(datetime(2026, 1, 1, 12, 0, 0))

    assert reading is not None
    assert reading.timestamp == T0
    assert reading.timestamp.tzinfo is not None


def test_nxt_06_field_types() -> None:
    reading = make_sim().next_reading(T0)

    assert reading is not None
    for name in (
        "speed_kmh",
        "fuel_level_pct",
        "engine_temp_c",
        "latitude",
        "longitude",
    ):
        assert isinstance(getattr(reading, name), float)
    assert isinstance(reading.engine_rpm, int)
    assert not hasattr(reading, "id")


def test_nxt_07_same_now_repeated() -> None:
    sim = make_sim()

    readings = [sim.next_reading(T0) for _ in range(5)]

    assert all(r is not None for r in readings)
    assert {r.timestamp for r in readings if r is not None} == {T0}


def test_nxt_08_now_going_backwards() -> None:
    sim = make_sim()

    first = sim.next_reading(T0 + timedelta(seconds=10))
    second = sim.next_reading(T0)

    assert first is not None and second is not None


@pytest.mark.parametrize(
    "bad_now",
    [pytest.param(None, id="none"), pytest.param("2026-01-01", id="string")],
)
def test_nxt_09_non_datetime_now(bad_now: Any) -> None:
    try:
        result = make_sim().next_reading(bad_now)
    except (TypeError, ValueError):
        return

    assert result is None or isinstance(result.timestamp, datetime)


# --- ranges -----------------------------------------------------------------


def test_rng_01_ten_thousand_readings_in_range() -> None:
    assert_in_ranges(cached_run(42, 10_000))


@pytest.mark.parametrize("seed", SEEDS, ids=[f"seed-{s}" for s in SEEDS])
def test_rng_02_ranges_across_seeds(seed: int) -> None:
    assert_in_ranges(cached_run(seed, 10_000))


@pytest.mark.parametrize("start", range(ROUTE_LEN), ids=lambda i: f"start-{i}")
def test_rng_03_ranges_for_every_start_index(start: int) -> None:
    assert_in_ranges(run_valid(make_sim(start_index=start), 500))


def test_rng_04_long_run_stays_in_range() -> None:
    assert_in_ranges(run_valid(make_sim(), 200_000))


# --- speed ------------------------------------------------------------------


def test_spd_01_typical_band() -> None:
    speeds = [r.speed_kmh for r in cached_run(42, 10_000)]

    assert min(speeds) >= 0
    assert max(speeds) <= 120


def test_spd_02_lower_clamp() -> None:
    rng = ScriptedRandom("low")

    speeds = [r.speed_kmh for r in run_valid(make_sim(rng=rng), 200)]

    assert min(speeds) == 0
    assert all(s == 0 for s in speeds[speeds.index(0) :])


def test_spd_03_upper_clamp() -> None:
    rng = ScriptedRandom("high")

    speeds = [r.speed_kmh for r in run_valid(make_sim(rng=rng), 200)]

    assert max(speeds) == 120.0
    assert speeds[-1] == 120.0


def test_spd_04_step_bounded_by_delta() -> None:
    rng = ScriptedRandom("real")
    speeds = [r.speed_kmh for r in run_valid(make_sim(rng=rng), 10_000)]
    delta = max(max(abs(a), abs(b)) for a, b in rng.uniform_calls)

    steps = [abs(b - a) for a, b in zip(speeds, speeds[1:], strict=False)]

    assert max(steps) <= delta + 1e-9


def test_spd_05_speed_varies() -> None:
    speeds = [r.speed_kmh for r in cached_run(42, 1_000)]

    assert len(set(speeds)) > 100
    assert max(speeds) - min(speeds) > 10


def test_spd_06_one_uniform_call_per_tick() -> None:
    rng = ScriptedRandom("real")

    run_valid(make_sim(rng=rng), 100)

    assert len(rng.uniform_calls) == 100


# --- engine rpm -------------------------------------------------------------


def test_rpm_01_rpm_is_int() -> None:
    assert all(isinstance(r.engine_rpm, int) for r in cached_run(42, 1_000))


def test_rpm_02_correlates_with_speed() -> None:
    readings = cached_run(42, 10_000)

    corr = statistics.correlation(
        [r.speed_kmh for r in readings], [float(r.engine_rpm) for r in readings]
    )

    assert corr > 0.5


def test_rpm_03_idle_at_zero_speed() -> None:
    rng = ScriptedRandom("low", zero_noise)

    readings = run_valid(make_sim(rng=rng), 300)

    assert readings[-1].speed_kmh == 0
    assert 300 <= readings[-1].engine_rpm <= 1500
    assert readings[-2].engine_rpm == readings[-1].engine_rpm


def test_rpm_04_linear_in_speed_without_noise() -> None:
    idle = idle_rpm()
    rng = ScriptedRandom("high", zero_noise)

    readings = run_valid(make_sim(rng=rng), 300)

    top = readings[-1]
    assert top.speed_kmh == 120.0
    k = (top.engine_rpm - idle) / 120
    assert k > 0
    assert top.engine_rpm <= 8000
    assert all(abs(r.engine_rpm - (idle + k * r.speed_kmh)) <= 1 for r in readings)


def test_rpm_05_lower_clamp() -> None:
    rng = ScriptedRandom("mid", rpm_noise(-1e6))

    reading = make_sim(rng=rng).next_reading(T0)

    assert reading is not None
    assert reading.engine_rpm == 0


def test_rpm_06_upper_clamp() -> None:
    rng = ScriptedRandom("mid", rpm_noise(1e6))

    reading = make_sim(rng=rng).next_reading(T0)

    assert reading is not None
    assert reading.engine_rpm == 8000


def test_rpm_07_noise_changes_rpm_at_same_speed() -> None:
    rng = ScriptedRandom(
        "mid", lambda i: 5.0 if i % 4 == 0 else -5.0 if i % 4 == 2 else 0.0
    )

    readings = run_valid(make_sim(rng=rng), 2)

    assert readings[0].speed_kmh == readings[1].speed_kmh
    assert readings[0].engine_rpm != readings[1].engine_rpm


# --- fuel -------------------------------------------------------------------


def test_ful_01_starts_near_full() -> None:
    first = make_sim().next_reading(T0)

    assert first is not None
    assert 99 <= first.fuel_level_pct <= 100


def test_ful_02_monotonic_non_increasing() -> None:
    fuel = [r.fuel_level_pct for r in cached_run(42, 10_000)]

    assert all(b <= a for a, b in zip(fuel, fuel[1:], strict=False))


def test_ful_03_floors_at_zero_and_stays() -> None:
    first, second = run_valid(make_sim(), 2)
    epsilon = first.fuel_level_pct - second.fuel_level_pct
    assert epsilon > 0

    fuel = [
        r.fuel_level_pct for r in run_valid(make_sim(), math.ceil(100 / epsilon) + 10)
    ]

    assert min(fuel) == 0
    assert all(f == 0 for f in fuel[fuel.index(0) :])


def test_ful_04_strictly_decreasing_while_not_empty() -> None:
    fuel = [r.fuel_level_pct for r in cached_run(42, 100)]

    assert all(b < a for a, b in zip(fuel, fuel[1:], strict=False))


def test_ful_05_decreases_slowly() -> None:
    assert cached_run(42, 3_600)[-1].fuel_level_pct > 0


def test_ful_06_independent_of_rng() -> None:
    fuel_1 = [r.fuel_level_pct for r in cached_run(1, 1_000)]
    fuel_2 = [r.fuel_level_pct for r in cached_run(2, 1_000)]

    assert fuel_1 == fuel_2


# --- temperature ------------------------------------------------------------


def test_tmp_01_starts_near_ambient() -> None:
    first = make_sim().next_reading(T0)

    assert first is not None
    assert 15 <= first.engine_temp_c <= 30


def test_tmp_02_warms_up() -> None:
    temp = [r.engine_temp_c for r in cached_run(42, 600)]

    assert statistics.mean(temp[500:600]) - statistics.mean(temp[0:100]) > 30
    assert temp[100] > temp[1]


def test_tmp_03_converges_near_90() -> None:
    temp = [r.engine_temp_c for r in cached_run(42, 5_000)]

    assert 85 <= statistics.mean(temp[-500:]) <= 95


def test_tmp_04_stabilises_with_noise() -> None:
    temp = [r.engine_temp_c for r in cached_run(42, 5_000)]

    assert 0 < statistics.pstdev(temp[-500:]) < 3


def test_tmp_05_below_red_threshold() -> None:
    assert max(r.engine_temp_c for r in cached_run(42, 10_000)) <= 110


def test_tmp_06_deterministic_part_without_noise() -> None:
    rng = ScriptedRandom("mid", zero_noise)

    temp = [r.engine_temp_c for r in run_valid(make_sim(rng=rng), 5_000)]

    assert all(b >= a for a, b in zip(temp, temp[1:], strict=False))
    assert abs(temp[-1] - 90) <= 1


def test_tmp_07_extreme_noise_clamped_or_dropped() -> None:
    rng = ScriptedRandom("mid", lambda i: 1e6 if i % 2 == 0 else -1e6)

    readings = run(make_sim(rng=rng), 100)

    assert_in_ranges([r for r in readings if r is not None])


# --- GPS / route ------------------------------------------------------------


def test_gps_01_positions_are_route_points() -> None:
    readings = run_valid(make_sim(), 3 * ROUTE_LEN)

    assert all(position(r) in ROUTE_LOOP for r in readings)


def test_gps_02_advances_one_point_per_reading() -> None:
    readings = run_valid(make_sim(start_index=0), ROUTE_LEN)

    offset = route_offset(readings[0], 0)

    assert offset in (0, 1)
    assert [position(r) for r in readings] == [
        ROUTE_LOOP[(offset + i) % ROUTE_LEN] for i in range(ROUTE_LEN)
    ]


def test_gps_03_wraps_at_end_of_loop() -> None:
    readings = run_valid(make_sim(), 2 * ROUTE_LEN + 1)

    for i in range(ROUTE_LEN + 1):
        assert position(readings[i + ROUTE_LEN]) == position(readings[i])


def test_gps_04_wraps_repeatedly() -> None:
    readings = cached_run(42, 10_000)
    offset = route_offset(readings[0], 0)

    assert all(
        position(r) == ROUTE_LOOP[(offset + i) % ROUTE_LEN]
        for i, r in enumerate(readings)
    )


def test_gps_05_different_start_index_different_position() -> None:
    assert ROUTE_LEN > 1
    first_a = make_sim(start_index=0).next_reading(T0)
    first_b = make_sim(start_index=1).next_reading(T0)

    assert first_a is not None and first_b is not None
    assert position(first_a) != position(first_b)


def test_gps_06_start_index_shifts_path() -> None:
    k = 2
    path_a = run_valid(make_sim(seed=1, start_index=0), k + 1)
    path_b = run_valid(make_sim(seed=2, start_index=k), 1)

    assert position(path_b[0]) == position(path_a[k])


def test_gps_07_route_constant_is_valid() -> None:
    assert isinstance(ROUTE_LOOP, tuple)
    assert ROUTE_LEN >= 3
    for point in ROUTE_LOOP:
        assert isinstance(point, tuple)
        lat, lon = point
        assert isinstance(lat, float) and isinstance(lon, float)
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180
    assert len(set(ROUTE_LOOP)) > 1


def test_gps_08_route_constant_is_immutable() -> None:
    with pytest.raises(TypeError):
        ROUTE_LOOP[0] = (0.0, 0.0)  # type: ignore[index]
    with pytest.raises(AttributeError):
        ROUTE_LOOP.append((0.0, 0.0))  # type: ignore[attr-defined]


# --- determinism ------------------------------------------------------------


def test_det_01_same_seed_same_sequence() -> None:
    first = run(make_sim(seed=42), 1_000)
    second = run(make_sim(seed=42), 1_000)

    assert first == second


def test_det_02_different_seeds_differ() -> None:
    speeds_1 = [r.speed_kmh for r in run_valid(make_sim(seed=1), 100)]
    speeds_2 = [r.speed_kmh for r in run_valid(make_sim(seed=2), 100)]

    assert speeds_1 != speeds_2


def test_det_03_vehicles_have_independent_state() -> None:
    sim_a = make_sim(VEH1, seed=1)
    sim_b = make_sim(VEH2, seed=2)
    run(sim_a, 50)

    after_a = sim_b.next_reading(T0)
    fresh = make_sim(VEH2, seed=2).next_reading(T0)

    assert after_a == fresh


def test_det_04_interleaved_equals_isolated() -> None:
    sim_a, sim_b = make_sim(VEH1, seed=1), make_sim(VEH2, seed=2, start_index=1)
    seq_a: list[TelemetryReadingCreate | None] = []
    seq_b: list[TelemetryReadingCreate | None] = []
    for i in range(200):
        seq_a.append(sim_a.next_reading(tick_time(i)))
        seq_b.append(sim_b.next_reading(tick_time(i)))

    assert seq_a == run(make_sim(VEH1, seed=1), 200)
    assert seq_b == run(make_sim(VEH2, seed=2, start_index=1), 200)


def test_det_05_output_independent_of_now() -> None:
    early = run_valid(make_sim(), 200)
    late = run_valid(make_sim(), 200, T0 + timedelta(days=7))

    assert [r.model_dump(exclude={"timestamp"}) for r in early] == [
        r.model_dump(exclude={"timestamp"}) for r in late
    ]


def test_det_06_global_random_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("global random module used")

    random.seed(1)
    first = run(make_sim(seed=42), 500)
    random.seed(2)
    for name in ("random", "uniform", "gauss"):
        monkeypatch.setattr(random, name, boom)
    second = run(make_sim(seed=42), 500)

    assert first == second


def test_det_07_shared_rng_is_reproducible() -> None:
    def combined() -> list[TelemetryReadingCreate | None]:
        rng = random.Random(42)
        sim_a, sim_b = make_sim(VEH1, rng=rng), make_sim(VEH2, rng=rng)
        out: list[TelemetryReadingCreate | None] = []
        for i in range(100):
            out.append(sim_a.next_reading(tick_time(i)))
            out.append(sim_b.next_reading(tick_time(i)))
        return out

    assert combined() == combined()


# --- validation drop --------------------------------------------------------


@pytest.mark.parametrize(
    ("attr", "value"),
    [
        pytest.param("_step_speed", 300.0, id="TS-DRP-01-speed-300"),
        pytest.param("_rpm_for", 9000, id="rpm-9000"),
        pytest.param("_step_fuel", 101.0, id="fuel-101"),
        pytest.param("_step_fuel", -0.1, id="fuel-minus-0.1"),
        pytest.param("_step_temp", 151.0, id="temp-151"),
        pytest.param("_step_temp", -41.0, id="temp-minus-41"),
        pytest.param("_step_position", (90.1, 20.0), id="latitude-90.1"),
        pytest.param("_step_position", (10.0, 180.1), id="longitude-180.1"),
        pytest.param("_step_speed", float("nan"), id="TS-DRP-04-nan"),
        pytest.param("_step_speed", float("inf"), id="inf"),
        pytest.param("_step_speed", float("-inf"), id="minus-inf"),
    ],
)
def test_drp_01_02_04_invalid_value_dropped(
    monkeypatch: pytest.MonkeyPatch, attr: str, value: Any
) -> None:
    sim = make_sim()
    force(monkeypatch, sim, attr, value)

    assert sim.next_reading(T0) is None


@pytest.mark.parametrize(
    ("attr", "value", "field", "expected"),
    [
        pytest.param("_step_speed", 250.0, "speed_kmh", 250.0, id="speed-250"),
        pytest.param("_step_speed", 0.0, "speed_kmh", 0.0, id="speed-0"),
        pytest.param("_rpm_for", 8000, "engine_rpm", 8000, id="rpm-8000"),
        pytest.param("_rpm_for", 0, "engine_rpm", 0, id="rpm-0"),
        pytest.param("_step_fuel", 100.0, "fuel_level_pct", 100.0, id="fuel-100"),
        pytest.param("_step_fuel", 0.0, "fuel_level_pct", 0.0, id="fuel-0"),
        pytest.param("_step_temp", 150.0, "engine_temp_c", 150.0, id="temp-150"),
        pytest.param("_step_temp", -40.0, "engine_temp_c", -40.0, id="temp-minus-40"),
        pytest.param("_step_position", (90.0, 20.0), "latitude", 90.0, id="lat-90"),
        pytest.param("_step_position", (-90.0, 20.0), "latitude", -90.0, id="lat--90"),
        pytest.param("_step_position", (10.0, 180.0), "longitude", 180.0, id="lon-180"),
        pytest.param(
            "_step_position", (10.0, -180.0), "longitude", -180.0, id="lon--180"
        ),
    ],
)
def test_drp_03_boundary_values_kept(
    monkeypatch: pytest.MonkeyPatch, attr: str, value: Any, field: str, expected: Any
) -> None:
    sim = make_sim()
    force(monkeypatch, sim, attr, value)

    reading = sim.next_reading(T0)

    assert reading is not None
    assert getattr(reading, field) == expected


def test_drp_05_recovers_after_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    sim = make_sim()
    original = sim._step_speed  # noqa: SLF001
    calls = {"n": 0}

    def flaky() -> float:
        calls["n"] += 1
        return 300.0 if calls["n"] == 1 else original()

    monkeypatch.setattr(sim, "_step_speed", flaky)

    results = run(sim, 3)

    assert results[0] is None
    assert results[1] is not None and results[2] is not None


def test_drp_07_only_validation_error_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim = make_sim()

    def broken() -> float:
        raise RuntimeError("programming error")

    monkeypatch.setattr(sim, "_step_speed", broken)

    with pytest.raises(RuntimeError):
        sim.next_reading(T0)


def test_drp_08_dropped_reading_does_not_log_location(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sim = make_sim()
    force(monkeypatch, sim, "_step_position", (91.123456, 20.654321))

    with caplog.at_level(logging.DEBUG):
        assert sim.next_reading(T0) is None

    assert "91.123456" not in caplog.text
    assert "20.654321" not in caplog.text


# --- purity (static) --------------------------------------------------------


def _module_tree() -> ast.Module:
    source_file = inspect.getsourcefile(sim_mod)
    assert source_file is not None
    return ast.parse(Path(source_file).read_text(encoding="utf-8"))


def _generator_nodes(tree: ast.Module) -> list[ast.AST]:
    """Generator code only; the Phase 4 runner may share the module (S14)."""
    return [
        node
        for node in tree.body
        if (isinstance(node, ast.ClassDef) and node.name == "VehicleSimulator")
        or (isinstance(node, ast.FunctionDef) and node.name == "make_vehicle_ids")
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "ROUTE_LOOP" for t in node.targets
            )
        )
    ]


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[(alias.asname or alias.name).split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _is_forbidden(path: str, forbidden: tuple[str, ...]) -> bool:
    return any(path == f or path.startswith(f + ".") for f in forbidden)


def test_pur_01_generator_has_no_forbidden_dependencies() -> None:
    tree = _module_tree()
    aliases = _import_aliases(tree)
    nodes = _generator_nodes(tree)
    assert nodes, "generator code not found"

    for target in aliases.values():
        assert not _is_forbidden(target, ("fastapi", "telemetry.api", "telemetry.main"))
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in aliases:
                assert not _is_forbidden(aliases[child.id], FORBIDDEN_IMPORTS)
            assert not isinstance(child, ast.Import | ast.ImportFrom)


def test_pur_02_generator_has_no_clock_sleep_eval_exec() -> None:
    nodes = _generator_nodes(_module_tree())
    assert nodes, "generator code not found"

    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                assert ast.unparse(child.func) not in FORBIDDEN_CALLS


def test_pur_03_import_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("side effect at import time")

    for target in (
        "random.seed",
        "random.random",
        "random.uniform",
        "random.gauss",
        "socket.socket",
        "sqlite3.connect",
    ):
        monkeypatch.setattr(target, boom)
    monkeypatch.chdir(tmp_path)

    importlib.reload(sim_mod)

    assert list(tmp_path.iterdir()) == []


def test_pur_04_public_api_typed_and_documented() -> None:
    for obj in (VehicleSimulator, VehicleSimulator.next_reading, make_vehicle_ids):
        assert inspect.getdoc(obj)
    for func in (
        VehicleSimulator.__init__,
        VehicleSimulator.next_reading,
        make_vehicle_ids,
    ):
        for name, param in inspect.signature(func).parameters.items():
            if name != "self":
                assert param.annotation is not inspect.Parameter.empty
    for func in (VehicleSimulator.next_reading, make_vehicle_ids):
        assert inspect.signature(func).return_annotation is not inspect.Signature.empty


def test_pur_05_this_file_has_no_db_thread_sleep_or_clock() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(_is_forbidden(a.name, FORBIDDEN_IMPORTS) for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not _is_forbidden(node.module, FORBIDDEN_IMPORTS)
        elif isinstance(node, ast.Call):
            assert ast.unparse(node.func) not in FORBIDDEN_CALLS


# --- integration (no DB, no threads) ----------------------------------------


def test_int_01_reading_promotes_to_stored_schema() -> None:
    reading = make_sim().next_reading(T0)
    assert reading is not None

    stored = TelemetryReading(id=1, **reading.model_dump())

    assert stored.model_dump(exclude={"id"}) == reading.model_dump()


def _two_sims() -> list[VehicleSimulator]:
    return [
        make_sim(vid, seed=seed, start_index=idx)
        for idx, (vid, seed) in enumerate(zip(make_vehicle_ids(2), (1, 2), strict=True))
    ]


def test_int_02_one_simulator_per_vehicle() -> None:
    sim_a, sim_b = _two_sims()

    readings_a, readings_b = run_valid(sim_a, 10), run_valid(sim_b, 10)

    assert {r.vehicle_id for r in readings_a} == {VEH1}
    assert {r.vehicle_id for r in readings_b} == {VEH2}
    assert [r.speed_kmh for r in readings_a] != [r.speed_kmh for r in readings_b]
    assert all(
        position(a) != position(b) for a, b in zip(readings_a, readings_b, strict=True)
    )


def test_int_03_runner_style_tick_loop() -> None:
    sims = _two_sims()
    per_vehicle: dict[str, list[TelemetryReadingCreate]] = {
        s_id: [] for s_id in (VEH1, VEH2)
    }

    for tick in range(100):
        for sim in sims:
            reading = sim.next_reading(tick_time(tick))
            assert reading is not None
            per_vehicle[reading.vehicle_id].append(reading)

    assert sum(len(v) for v in per_vehicle.values()) == 200
    for readings in per_vehicle.values():
        assert all(
            b.timestamp - a.timestamp == timedelta(seconds=1)
            for a, b in zip(readings, readings[1:], strict=False)
        )


# --- pending / manual / out of scope ----------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("TS-VID-07: count 0 behaviour pending (S7)", id="TS-VID-07"),
        pytest.param(
            "TS-VID-08: negative count behaviour pending (S7)", id="TS-VID-08"
        ),
        pytest.param("TS-INI-05: negative start_index pending (S8)", id="TS-INI-05"),
        pytest.param("TS-INI-06: invalid vehicle_id pending (S9)", id="TS-INI-06"),
        pytest.param(
            "TS-DRP-06: state advance after drop pending (S11)", id="TS-DRP-06"
        ),
        pytest.param("TS-DRP-09: depends on TS-INI-06 (S9)", id="TS-DRP-09"),
        pytest.param("TS-GPS-09: manual compliance review", id="TS-GPS-09"),
        pytest.param("TS-PUR-06: coverage gate, run pytest --cov=src", id="TS-PUR-06"),
        pytest.param("TS-INT-04: scope note, covered in Phase 4", id="TS-INT-04"),
    ],
)
def test_pending_or_non_automatable(reason: str) -> None:
    pytest.skip(reason)
