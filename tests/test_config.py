from pathlib import Path

import pytest
from pydantic import ValidationError

from telemetry.config import Settings, get_settings, load_settings

ENV_NAMES = [
    "DATABASE_URL",
    "SIM_INTERVAL_SECONDS",
    "SIM_VEHICLE_COUNT",
    "RETENTION_MINUTES",
    "DASHBOARD_POLL_SECONDS",
    "SIM_ENABLED",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    # Ensure no developer .env file influences the tests.
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()


def test_defaults() -> None:
    settings = load_settings()

    assert settings.database_url == "sqlite:///./telemetry.db"
    assert settings.sim_interval_seconds == 1
    assert settings.sim_vehicle_count == 2
    assert settings.retention_minutes == 60
    assert settings.dashboard_poll_seconds == 2
    assert settings.sim_enabled is True


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SIM_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("SIM_VEHICLE_COUNT", "5")
    monkeypatch.setenv("RETENTION_MINUTES", "10")
    monkeypatch.setenv("DASHBOARD_POLL_SECONDS", "3")
    monkeypatch.setenv("SIM_ENABLED", "false")

    settings = load_settings()

    assert settings.database_url == "sqlite://"
    assert settings.sim_interval_seconds == 0.5
    assert settings.sim_vehicle_count == 5
    assert settings.retention_minutes == 10
    assert settings.dashboard_poll_seconds == 3
    assert settings.sim_enabled is False


@pytest.mark.parametrize("count", ["1", "10"])
def test_vehicle_count_boundaries_accepted(
    monkeypatch: pytest.MonkeyPatch, count: str
) -> None:
    monkeypatch.setenv("SIM_VEHICLE_COUNT", count)

    assert load_settings().sim_vehicle_count == int(count)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SIM_VEHICLE_COUNT", "0"),
        ("SIM_VEHICLE_COUNT", "11"),
        ("SIM_VEHICLE_COUNT", "abc"),
        ("SIM_INTERVAL_SECONDS", "0"),
        ("SIM_INTERVAL_SECONDS", "-1"),
        ("RETENTION_MINUTES", "0"),
        ("DASHBOARD_POLL_SECONDS", "0"),
        ("SIM_ENABLED", "maybe"),
        ("DATABASE_URL", ""),
    ],
)
def test_invalid_values_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        load_settings()


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_settings_are_immutable() -> None:
    with pytest.raises(ValidationError):
        Settings().sim_enabled = False  # type: ignore[misc]
