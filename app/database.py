"""
Async database engine & session management (SQLAlchemy 2.0 style).

Robustness features:
    - SQLite: `PRAGMA foreign_keys=ON` (SQLite does NOT enforce FKs by default!),
      WAL journal for crash safety + concurrent reads, busy timeout.
    - Schema is always managed by Alembic. `run_migrations()` runs at startup
      for every dialect, upgrading to head; a legacy DB created by an older
      `create_all()` build is detected and stamped first, so upgrades are safe.
"""
import logging
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings
from app.paths import BUNDLE_DIR, DATA_DIR

logger = logging.getLogger("app.database")

PROJECT_ROOT = DATA_DIR  # backwards-compatible alias: where user data lives
INITIAL_REVISION = "319ece25826e"  # schema shipped before Alembic-at-startup existed
IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


def _engine_kwargs() -> dict:
    if IS_SQLITE:
        return {"poolclass": NullPool, "connect_args": {"check_same_thread": False}}
    return {
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": True,
    }


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    future=True,
    **_engine_kwargs(),
)

if IS_SQLITE:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")        # enforce ON DELETE CASCADE / SET NULL
        cursor.execute("PRAGMA journal_mode=WAL")       # durable + readers don't block the writer
        cursor.execute("PRAGMA synchronous=NORMAL")     # safe with WAL, much faster than FULL
        cursor.execute("PRAGMA busy_timeout=5000")      # wait instead of failing on a brief lock
        cursor.close()


async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: request-scoped session with commit/rollback/close."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def sqlite_file_path() -> Path | None:
    """Filesystem path of the SQLite database (None for other dialects)."""
    if not IS_SQLITE:
        return None
    raw = settings.DATABASE_URL.split("///", 1)[1]
    return (DATA_DIR / raw).resolve() if not Path(raw).is_absolute() else Path(raw)


def _alembic_config():
    from alembic.config import Config

    # Migration scripts ship with the code (inside the EXE bundle when frozen).
    cfg = Config(str(BUNDLE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BUNDLE_DIR / "alembic"))
    return cfg


def _upgrade_sync(stamp_first: bool) -> None:
    """Runs in a worker thread: alembic's env.py calls asyncio.run() itself."""
    from alembic import command

    cfg = _alembic_config()
    if stamp_first:
        logger.warning("Legacy database without alembic_version detected — stamping %s first.", INITIAL_REVISION)
        command.stamp(cfg, INITIAL_REVISION)
    command.upgrade(cfg, "head")


async def run_migrations() -> None:
    """Bring the schema to the latest Alembic revision (idempotent)."""
    import asyncio

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    legacy = "users" in tables and "alembic_version" not in tables
    await asyncio.to_thread(_upgrade_sync, legacy)
    logger.info("Database schema is at head (%s).", "sqlite" if IS_SQLITE else "postgresql")


async def dispose_engine() -> None:
    await engine.dispose()
