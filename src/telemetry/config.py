"""Application settings loaded from environment variables."""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    """Validated application settings (defaults mirror the spec)."""

    model_config = ConfigDict(frozen=True)

    database_url: str = Field(default="sqlite:///./telemetry.db", min_length=1)
    sim_interval_seconds: float = Field(default=1.0, gt=0)
    sim_vehicle_count: int = Field(default=2, ge=1, le=10)
    retention_minutes: int = Field(default=60, gt=0)
    dashboard_poll_seconds: float = Field(default=2.0, gt=0)
    sim_enabled: bool = True


def load_settings() -> Settings:
    """Build settings from the environment (and `.env`, if present).

    Raises:
        pydantic.ValidationError: if any value is missing bounds or malformed.
    """
    load_dotenv()
    values: dict[str, str] = {}
    for field in Settings.model_fields:
        raw = os.environ.get(field.upper())
        if raw is not None:
            values[field] = raw
    return Settings.model_validate(values)


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return load_settings()
