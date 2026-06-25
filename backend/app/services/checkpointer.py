"""
QueryfyAI - LangGraph Checkpointer Factory

Provides persistent state management for the ReAct agent with automatic
backend selection based on available infrastructure:

1. PostgreSQL (recommended for production) - via AsyncPostgresSaver
2. Redis (alternative for production) - via AsyncRedisSaver
3. In-Memory (development/testing only) - via MemorySaver

Enables:
- Horizontal scaling (multiple instances share state)
- Resume on failure (continue from last checkpoint)
- Conversation persistence across restarts

References:
- https://pypi.org/project/langgraph-checkpoint-postgres/
- https://pypi.org/project/langgraph-checkpoint-redis/
"""

import logging
from enum import Enum
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class CheckpointerBackend(Enum):
    """Available checkpointer backends."""
    POSTGRES = "postgres"
    REDIS = "redis"
    MEMORY = "memory"


class CheckpointerFactory:
    """
    Factory for creating LangGraph checkpointers.

    Automatically selects the best available backend based on configuration.
    Provides singleton management and proper lifecycle handling.
    """

    _instance: Optional["CheckpointerFactory"] = None
    _checkpointer: Optional[Any] = None
    _context_manager: Optional[Any] = None  # Keep reference to context manager
    _pool: Optional[Any] = None  # Connection pool for PostgreSQL backend
    _backend: Optional[CheckpointerBackend] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "CheckpointerFactory":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get_backend(cls) -> Optional[CheckpointerBackend]:
        """Get the current backend type."""
        return cls._backend

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if checkpointer is initialized."""
        return cls._initialized and cls._checkpointer is not None

    @classmethod
    async def initialize(cls) -> Optional[Any]:
        """
        Initialize the checkpointer based on available configuration.

        Priority order:
        1. PostgreSQL if DATABASE_URL is set and AGENT_USE_POSTGRES_STATE is True
        2. Redis if REDIS_URL is set
        3. In-Memory as fallback

        Returns:
            The initialized checkpointer or None if initialization fails
        """
        if cls._initialized and cls._checkpointer is not None:
            return cls._checkpointer

        # Try PostgreSQL first (recommended for production)
        if settings.DATABASE_URL and settings.AGENT_USE_POSTGRES_STATE:
            checkpointer = await cls._init_postgres()
            if checkpointer:
                cls._checkpointer = checkpointer
                cls._backend = CheckpointerBackend.POSTGRES
                cls._initialized = True
                logger.info("✓ Checkpointer initialized: PostgreSQL (horizontal scaling enabled)")
                return checkpointer

        # Try Redis as alternative
        if settings.REDIS_URL:
            checkpointer = await cls._init_redis()
            if checkpointer:
                cls._checkpointer = checkpointer
                cls._backend = CheckpointerBackend.REDIS
                cls._initialized = True
                logger.info("✓ Checkpointer initialized: Redis (horizontal scaling enabled)")
                return checkpointer

        # Fall back to in-memory
        checkpointer = cls._init_memory()
        if checkpointer:
            cls._checkpointer = checkpointer
            cls._backend = CheckpointerBackend.MEMORY
            cls._initialized = True
            logger.warning(
                "⚠️  Checkpointer initialized: In-Memory (NOT suitable for production, "
                "state will be lost on restart, no horizontal scaling)"
            )
            return checkpointer

        logger.error("✗ Failed to initialize any checkpointer")
        return None

    @classmethod
    async def _init_postgres(cls) -> Optional[Any]:
        """Initialize PostgreSQL checkpointer."""
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # Convert URL format if needed
            db_url = settings.DATABASE_URL
            if not db_url:
                raise ValueError("DATABASE_URL is required for PostgreSQL checkpointer")

            if db_url.startswith("postgresql+asyncpg://"):
                db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

            # Use a connection pool instead of a single connection for resilience.
            # A single AsyncConnection (from from_conn_string) dies permanently when
            # the server closes it. A pool detects broken connections and reconnects.
            pool = AsyncConnectionPool(
                conninfo=db_url,
                open=False,
                min_size=1,
                max_size=5,
                # Validate connections before handing them out
                check=AsyncConnectionPool.check_connection,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            await pool.open()
            cls._pool = pool

            checkpointer = AsyncPostgresSaver(conn=pool)  # type: ignore[arg-type]

            # Setup tables (idempotent - safe to call multiple times)
            await checkpointer.setup()

            logger.info("PostgreSQL checkpointer tables created/verified")
            return checkpointer

        except ImportError:
            logger.warning(
                "langgraph-checkpoint-postgres not installed. "
                "Install with: pip install langgraph-checkpoint-postgres"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL checkpointer: {e}")
            return None

    @classmethod
    async def _init_redis(cls) -> Optional[Any]:
        """Initialize Redis checkpointer."""
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver

            # Create context manager and enter it
            # We keep the context manager reference to properly exit during shutdown
            context_manager = AsyncRedisSaver.from_conn_string(settings.REDIS_URL)
            checkpointer = await context_manager.__aenter__()
            cls._context_manager = context_manager

            # Setup indices (idempotent - safe to call multiple times)
            await checkpointer.setup()

            logger.info("Redis checkpointer indices created/verified")
            return checkpointer

        except ImportError:
            logger.warning(
                "langgraph-checkpoint-redis not installed. "
                "Install with: pip install langgraph-checkpoint-redis"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Redis checkpointer: {e}")
            return None

    @classmethod
    def _init_memory(cls) -> Optional[Any]:
        """Initialize in-memory checkpointer."""
        try:
            from langgraph.checkpoint.memory import MemorySaver
            return MemorySaver()
        except ImportError:
            logger.error("langgraph not installed")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize memory checkpointer: {e}")
            return None

    @classmethod
    def get_checkpointer(cls) -> Optional[Any]:
        """
        Get the initialized checkpointer.

        Returns:
            The checkpointer instance or None if not initialized
        """
        return cls._checkpointer

    @classmethod
    async def shutdown(cls) -> None:
        """
        Shutdown the checkpointer and release resources.

        Should be called during application shutdown.
        """
        if cls._checkpointer is None:
            return

        try:
            # Close the connection pool if we have one (PostgreSQL)
            if cls._pool is not None:
                await cls._pool.close()
                logger.info("Checkpointer connection pool closed")
            # Exit the context manager properly if we have one
            elif cls._context_manager is not None:
                await cls._context_manager.__aexit__(None, None, None)
                backend_name = cls._backend.value if cls._backend else "unknown"
                logger.info(f"Checkpointer context manager closed ({backend_name})")
            else:
                # Fallback for memory checkpointer or older API
                if cls._backend == CheckpointerBackend.REDIS:
                    if hasattr(cls._checkpointer, 'conn') and cls._checkpointer.conn:
                        await cls._checkpointer.conn.close()

            backend_name = cls._backend.value if cls._backend else "unknown"
            logger.info(f"Checkpointer shutdown complete ({backend_name})")
        except Exception as e:
            logger.warning(f"Error during checkpointer shutdown: {e}")
        finally:
            cls._checkpointer = None
            cls._context_manager = None
            cls._pool = None
            cls._backend = None
            cls._initialized = False


def generate_thread_id(session_id: str, run_id: Optional[str] = None) -> str:
    """
    Generate a thread ID for checkpointing.

    The thread_id uniquely identifies a conversation thread for state persistence.

    Args:
        session_id: The session identifier
        run_id: Optional run identifier for multiple runs within a session

    Returns:
        A unique thread ID string
    """
    if run_id:
        return f"{session_id}:{run_id}"
    return session_id


def get_checkpoint_config(thread_id: str) -> dict:
    """
    Create a checkpoint configuration dict for LangGraph.

    Args:
        thread_id: The thread identifier

    Returns:
        Configuration dict with thread_id in the expected format
    """
    return {
        "configurable": {
            "thread_id": thread_id
        }
    }


# Module-level convenience functions

async def init_checkpointer() -> Optional[Any]:
    """Initialize the global checkpointer. Call during app startup."""
    return await CheckpointerFactory.initialize()


def get_checkpointer() -> Optional[Any]:
    """Get the global checkpointer instance."""
    return CheckpointerFactory.get_checkpointer()


async def shutdown_checkpointer() -> None:
    """Shutdown the global checkpointer. Call during app shutdown."""
    await CheckpointerFactory.shutdown()


def is_checkpointer_available() -> bool:
    """Check if a checkpointer is available and initialized."""
    return CheckpointerFactory.is_initialized()


def get_checkpointer_backend() -> Optional[str]:
    """Get the name of the current checkpointer backend."""
    backend = CheckpointerFactory.get_backend()
    return backend.value if backend else None
