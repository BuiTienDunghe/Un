from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_postgres_engine(database_url: str, connect_timeout_seconds: int | None = None) -> Engine:
    """Engine for the app. ``connect_timeout_seconds`` is for short-lived CLIs.

    The default (None) keeps the driver's own timeout, which is right for a
    server that should wait out a slow start. A scheduled check is the opposite
    case: with Docker off, the default made check_operational_alerts sit for
    over two minutes before giving up — and its console window is deliberately
    visible, so a two-minute hang is an invitation to close it by hand.
    """
    if not database_url.startswith("postgresql+"):
        raise ValueError("DATABASE_URL must use a PostgreSQL SQLAlchemy dialect, for example postgresql+psycopg://")
    connect_args = {"connect_timeout": connect_timeout_seconds} if connect_timeout_seconds else {}
    return create_engine(database_url, pool_pre_ping=True, future=True, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
