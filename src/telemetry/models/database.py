"""Database engine, session factory and table creation."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from telemetry.config import get_settings
from telemetry.models.orm import Base


def create_db_engine(database_url: str) -> Engine:
    """Create an engine; SQLite gets thread-safe settings for the simulator."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return create_engine(url)
    if url.database in (None, "", ":memory:"):
        # A single shared connection keeps one in-memory DB across threads.
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, connect_args={"check_same_thread": False})


@lru_cache
def get_engine() -> Engine:
    """Return the cached engine built from application settings."""
    return create_db_engine(get_settings().database_url)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to `engine`."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine | None = None) -> None:
    """Create tables and enable WAL for file-based SQLite databases."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database not in (
        None,
        "",
        ":memory:",
    ):
        with engine.connect() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is closed after use."""
    with create_session_factory(get_engine())() as session:
        yield session
