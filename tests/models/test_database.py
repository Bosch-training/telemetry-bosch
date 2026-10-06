from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from telemetry.models import database
from telemetry.models.database import (
    create_db_engine,
    create_session_factory,
    get_session,
    init_db,
)


def test_init_db_creates_table_and_is_idempotent() -> None:
    engine = create_db_engine("sqlite://")

    init_db(engine)
    init_db(engine)

    assert "telemetry_readings" in inspect(engine).get_table_names()


def test_file_database_uses_wal(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")

    init_db(engine)

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    engine.dispose()


def test_session_factory_returns_usable_sessions() -> None:
    engine = create_db_engine("sqlite://")
    init_db(engine)

    with create_session_factory(engine)() as session:
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_get_session_yields_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    engine = create_db_engine(f"sqlite:///{tmp_path / 'dep.db'}")
    init_db(engine)
    monkeypatch.setattr(database, "get_engine", lambda: engine)

    generator = get_session()
    session = next(generator)
    assert session.execute(text("SELECT 1")).scalar() == 1
    generator.close()
    engine.dispose()
