"""
QueryfyAI - Database Session Factory

SQLAlchemy async engine and session management for Data Dictionary persistence.
Uses the same DATABASE_URL as the agent state (PostgreSQL).
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

# SQLAlchemy Base for ORM models
Base = declarative_base()

# Global engine and session factory (initialized lazily)
_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_database_url() -> Optional[str]:
    """
    Get the database URL for data dictionary storage.
    Uses DATABASE_URL from settings (same as agent state).

    Converts postgresql:// to postgresql+asyncpg:// for async support.
    """
    db_url = settings.DATABASE_URL
    if not db_url:
        return None

    # Convert to async driver URL if needed
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    return db_url


def get_engine() -> Optional[AsyncEngine]:
    """
    Get or create the async SQLAlchemy engine.
    Returns None if DATABASE_URL is not configured.
    """
    global _engine

    if _engine is not None:
        return _engine

    db_url = get_database_url()
    if not db_url:
        logger.warning(
            "DATABASE_URL not configured - Data Dictionary will use in-memory storage"
        )
        return None

    try:
        _engine = create_async_engine(
            db_url,
            echo=settings.DEBUG,
            pool_pre_ping=True,  # Verify connections before use
            poolclass=NullPool if settings.DEBUG else None,  # No pooling in debug mode
        )
        logger.info("Database engine created successfully")
        return _engine
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        return None


def get_session_factory() -> Optional[async_sessionmaker[AsyncSession]]:
    """
    Get or create the async session factory.
    Returns None if database is not available.
    """
    global _async_session_factory

    if _async_session_factory is not None:
        return _async_session_factory

    engine = get_engine()
    if not engine:
        return None

    _async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    return _async_session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(query)

    Raises:
        RuntimeError: If database is not configured
    """
    session_factory = get_session_factory()
    if not session_factory:
        raise RuntimeError(
            "Database not configured. Set DATABASE_URL environment variable."
        )

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def run_alembic_upgrade() -> bool:
    """
    Run Alembic migrations synchronously.

    Returns:
        True if successful, False otherwise

    Raises:
        Exception if migration fails (to fail startup)
    """
    import subprocess
    import sys
    from pathlib import Path

    # Get the backend directory (where alembic.ini is)
    backend_dir = Path(__file__).parent.parent.parent

    logger.info("Running Alembic migrations...")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"Alembic migration failed: {result.stderr}")
        raise RuntimeError(f"Database migration failed: {result.stderr}")

    if result.stdout:
        for line in result.stdout.strip().splitlines():
            if line:
                logger.info(f"Alembic: {line}")

    return True


async def init_database() -> bool:
    """
    Initialize the database - run Alembic migrations.
    Should be called on application startup.

    IMPORTANT: Raises exception on failure to prevent startup with
    inconsistent database schema.

    Returns:
        True if successful, False if database not configured

    Raises:
        RuntimeError if migrations fail
    """
    if not is_database_configured():
        logger.info("Database not configured - skipping migrations")
        return False

    try:
        # Run Alembic migrations (synchronous operation)
        run_alembic_upgrade()
        logger.info("Database migrations completed successfully")
        return True
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise  # Re-raise to fail startup


async def close_database() -> None:
    """
    Close database connections.
    Should be called on application shutdown.
    """
    global _engine, _async_session_factory

    if _engine:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
        logger.info("Database connections closed")


def is_database_configured() -> bool:
    """Check if database is configured and available."""
    return get_database_url() is not None
