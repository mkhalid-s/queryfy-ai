"""
QueryfyAI - Distributed Locking Service

Redis-based distributed locking for horizontal scaling with:
- Automatic expiry to prevent deadlocks
- Lock extension for long-running operations
- Graceful fallback when Redis unavailable
- Context manager and decorator support

Use Cases:
- Prevent concurrent agent runs for same session
- Protect checkpoint writes from race conditions
- Serialize schema refresh operations
"""

import asyncio
import functools
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class LockConfig:
    """Configuration for distributed locks."""

    # Default lock TTL (auto-release after this time to prevent deadlocks)
    default_ttl_seconds: int = 120

    # Lock acquisition timeout (how long to wait for lock)
    default_acquire_timeout: float = 30.0

    # Retry interval when waiting for lock
    retry_interval: float = 0.1

    # Key prefix for Redis
    key_prefix: str = "lock:"


class DistributedLock:
    """
    Redis-based distributed lock.

    Features:
    - Automatic expiry (prevents deadlocks if holder crashes)
    - Lock extension for long-running operations
    - Unique owner ID per lock acquisition
    - Graceful degradation when Redis unavailable

    Usage:
        lock = DistributedLock("session:123:agent")

        # Context manager
        async with lock:
            # Critical section
            pass

        # Manual acquire/release
        if await lock.acquire():
            try:
                # Critical section
                pass
            finally:
                await lock.release()

        # With custom TTL
        async with lock.with_ttl(300):
            # Long-running operation
            pass
    """

    _redis_client = None
    _redis_initialized = False
    _local_locks: Dict[str, asyncio.Lock] = {}  # Fallback locks when Redis unavailable

    def __init__(
        self,
        name: str,
        ttl_seconds: Optional[int] = None,
        acquire_timeout: Optional[float] = None,
    ):
        """
        Initialize a distributed lock.

        Args:
            name: Unique name for the lock (e.g., "session:123:agent")
            ttl_seconds: Lock TTL in seconds (auto-release after this time)
            acquire_timeout: Max time to wait for lock acquisition
        """
        self.config = LockConfig()
        self.name = name
        self.key = f"{self.config.key_prefix}{name}"
        self.ttl_seconds = ttl_seconds or self.config.default_ttl_seconds
        self.acquire_timeout = acquire_timeout or self.config.default_acquire_timeout

        # Unique owner ID for this lock acquisition
        self._owner_id: Optional[str] = None
        self._acquired = False
        self._using_local_lock = False  # Track if using local asyncio lock

    @classmethod
    def _init_redis(cls):
        """Initialize Redis client for distributed locking."""
        if cls._redis_initialized:
            return

        try:
            import redis.asyncio as redis

            cls._redis_client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            cls._redis_initialized = True
            logger.info("Distributed locking: Redis connected")
        except Exception as e:
            logger.warning(
                f"Distributed locking: Redis not available ({e}) - "
                "using local asyncio locks (no cross-instance protection)"
            )
            cls._redis_client = None
            cls._redis_initialized = True

    @classmethod
    async def _ensure_redis(cls) -> bool:
        """Ensure Redis is initialized and available."""
        if not cls._redis_initialized:
            cls._init_redis()

        if cls._redis_client:
            try:
                await cls._redis_client.ping()
                return True
            except Exception as e:
                logger.warning(f"Redis ping failed: {e}")
                return False
        return False

    async def _acquire_local_lock(self) -> bool:
        """
        Acquire a local asyncio lock as fallback when Redis unavailable.

        This provides protection within the same process only.
        For multi-worker deployments without Redis, there's no cross-worker protection.

        Phase 2 Day 3: in production (``FIX_DISTRIBUTED_LOCK_FAIL_LOUD`` on
        AND ``DEVELOPMENT_MODE=False``) this path is considered unsafe and
        raises ``RuntimeError`` instead of silently accepting a process-
        local lock. Multi-worker deployments without Redis cannot
        serialise concurrent agent runs for the same session and will
        corrupt checkpoint state. The escape hatch ``DEVELOPMENT_MODE=True``
        re-enables the fallback for dev/test only.
        """
        if settings.FIX_DISTRIBUTED_LOCK_FAIL_LOUD and not settings.DEVELOPMENT_MODE:
            try:
                from app.api.metrics import record_fix_event
                record_fix_event("distributed_lock_fail_loud")
            except Exception:
                pass
            logger.critical(
                f"Lock {self.name}: Redis unavailable in production; "
                f"refusing to fall back to process-local asyncio.Lock. "
                f"Multi-worker safety requires Redis. Set DEVELOPMENT_MODE=true "
                f"to permit the fallback for dev/test only."
            )
            raise RuntimeError(
                "Distributed lock requires Redis in production. "
                "Redis is unavailable and DEVELOPMENT_MODE=False. "
                "Configure REDIS_URL or set DEVELOPMENT_MODE=true "
                "(NOT for production use)."
            )

        # Get or create local lock for this name
        if self.name not in self._local_locks:
            self._local_locks[self.name] = asyncio.Lock()

        local_lock = self._local_locks[self.name]

        try:
            # Try to acquire with timeout
            acquired = await asyncio.wait_for(
                local_lock.acquire(),
                timeout=self.acquire_timeout,
            )
            if acquired:
                self._acquired = True
                self._using_local_lock = True
                logger.debug(f"Lock {self.name}: acquired (local asyncio, no Redis)")
                return True
            return False
        except asyncio.TimeoutError:
            logger.warning(
                f"Lock {self.name}: local lock timeout after {self.acquire_timeout}s"
            )
            return False

    async def _release_local_lock(self) -> bool:
        """Release the local asyncio lock."""
        if self.name in self._local_locks:
            local_lock = self._local_locks[self.name]
            try:
                local_lock.release()
                logger.debug(f"Lock {self.name}: released (local)")
                return True
            except RuntimeError:
                # Lock was not held
                logger.warning(f"Lock {self.name}: local release failed (not held)")
                return False
        return False

    async def acquire(self) -> bool:
        """
        Acquire the lock.

        Returns:
            True if lock was acquired, False if timeout

        Uses Redis SET with NX (only if not exists) and EX (expiry).
        Falls back to local asyncio lock when Redis unavailable.
        """
        self._owner_id = str(uuid.uuid4())
        start_time = time.time()

        # Check Redis availability
        redis_available = await self._ensure_redis()

        if not redis_available:
            # Fallback: use local asyncio lock (protects within same process)
            return await self._acquire_local_lock()

        assert self._redis_client is not None, "Redis client must be available after ensure_redis succeeds"

        # Try to acquire Redis lock with exponential backoff
        retry_count = 0
        while True:
            elapsed = time.time() - start_time
            if elapsed >= self.acquire_timeout:
                logger.warning(
                    f"Lock {self.name}: acquisition timeout after {elapsed:.1f}s"
                )
                return False

            try:
                # SET key value NX EX ttl
                # NX = only set if not exists
                # EX = expire after ttl seconds
                acquired = await self._redis_client.set(
                    self.key,
                    self._owner_id,
                    nx=True,
                    ex=self.ttl_seconds,
                )

                if acquired:
                    self._acquired = True
                    logger.debug(
                        f"Lock {self.name}: acquired (owner={self._owner_id[:8]})"
                    )
                    return True

                # Lock held by another, wait and retry
                retry_count += 1
                wait_time = min(
                    self.config.retry_interval * (1.5 ** min(retry_count, 10)),
                    1.0,  # Max 1 second between retries
                )
                await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error(f"Lock {self.name}: Redis error during acquire: {e}")
                # On Redis error, fall back to local lock
                logger.info(f"Lock {self.name}: falling back to local lock after Redis error")
                return await self._acquire_local_lock()

    async def release(self) -> bool:
        """
        Release the lock.

        Only releases if we are the current owner (prevents releasing
        a lock that was acquired by another instance after our TTL expired).

        Returns:
            True if lock was released, False otherwise
        """
        if not self._acquired:
            return False

        self._acquired = False

        # If we used local lock, release it
        if self._using_local_lock:
            self._using_local_lock = False
            return await self._release_local_lock()

        redis_available = await self._ensure_redis()
        if not redis_available:
            # This shouldn't happen (we had Redis when acquiring but not now)
            logger.warning(f"Lock {self.name}: Redis unavailable during release")
            return True

        assert self._redis_client is not None, "Redis client must be available after ensure_redis succeeds"

        try:
            # Lua script for atomic check-and-delete
            # Only delete if we're the owner
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """

            result = await self._redis_client.eval(
                lua_script, 1, self.key, self._owner_id
            )

            if result == 1:
                logger.debug(f"Lock {self.name}: released")
                return True
            else:
                logger.warning(
                    f"Lock {self.name}: not released (owner changed or expired)"
                )
                return False

        except Exception as e:
            logger.error(f"Lock {self.name}: Redis error during release: {e}")
            return False

    async def extend(self, additional_seconds: int) -> bool:
        """
        Extend the lock TTL.

        Useful for long-running operations that need more time.

        Args:
            additional_seconds: Additional time to add to lock TTL

        Returns:
            True if lock was extended, False if we're not the owner
        """
        if not self._acquired:
            return False

        # Local locks don't have TTL, no extension needed
        if self._using_local_lock:
            logger.debug(f"Lock {self.name}: extend skipped (local lock has no TTL)")
            return True

        redis_available = await self._ensure_redis()
        if not redis_available:
            # Shouldn't happen - we had Redis when acquiring
            logger.warning(f"Lock {self.name}: Redis unavailable during extend")
            return True

        assert self._redis_client is not None, "Redis client must be available after ensure_redis succeeds"

        try:
            # Lua script for atomic check-and-extend
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("expire", KEYS[1], ARGV[2])
            else
                return 0
            end
            """

            new_ttl = self.ttl_seconds + additional_seconds
            result = await self._redis_client.eval(
                lua_script, 1, self.key, self._owner_id, new_ttl
            )

            if result == 1:
                logger.debug(f"Lock {self.name}: extended by {additional_seconds}s")
                return True
            else:
                logger.warning(f"Lock {self.name}: extension failed (not owner)")
                return False

        except Exception as e:
            logger.error(f"Lock {self.name}: Redis error during extend: {e}")
            return False

    async def is_locked(self) -> bool:
        """Check if the lock is currently held by anyone."""
        redis_available = await self._ensure_redis()
        if not redis_available:
            # Check local lock
            if self.name in self._local_locks:
                return self._local_locks[self.name].locked()
            return False

        assert self._redis_client is not None, "Redis client must be available after ensure_redis succeeds"

        try:
            value = await self._redis_client.get(self.key)
            return value is not None
        except Exception:
            return False

    def with_ttl(self, ttl_seconds: int) -> "DistributedLock":
        """Return a new lock instance with custom TTL."""
        return DistributedLock(
            self.name,
            ttl_seconds=ttl_seconds,
            acquire_timeout=self.acquire_timeout,
        )

    async def __aenter__(self):
        """Async context manager entry."""
        acquired = await self.acquire()
        if not acquired:
            raise TimeoutError(f"Failed to acquire lock: {self.name}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.release()
        return False  # Don't suppress exceptions


# ==============================================================================
# CONVENIENCE FUNCTIONS
# ==============================================================================


def with_distributed_lock(
    lock_name_func: Callable[..., str],
    ttl_seconds: Optional[int] = None,
    acquire_timeout: Optional[float] = None,
):
    """
    Decorator for functions that need distributed locking.

    Args:
        lock_name_func: Function that takes the same args as decorated function
                       and returns the lock name
        ttl_seconds: Lock TTL
        acquire_timeout: Lock acquisition timeout

    Usage:
        @with_distributed_lock(lambda session_id, **kw: f"session:{session_id}:agent")
        async def run_agent(session_id: str, question: str):
            # Only one instance can run this for the same session_id
            pass
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            lock_name = lock_name_func(*args, **kwargs)
            lock = DistributedLock(
                lock_name,
                ttl_seconds=ttl_seconds,
                acquire_timeout=acquire_timeout,
            )
            async with lock:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


@asynccontextmanager
async def distributed_lock(
    name: str,
    ttl_seconds: Optional[int] = None,
    acquire_timeout: Optional[float] = None,
):
    """
    Context manager for distributed locking.

    Usage:
        async with distributed_lock(f"session:{session_id}:agent"):
            # Critical section
            pass
    """
    lock = DistributedLock(name, ttl_seconds, acquire_timeout)
    async with lock:
        yield lock


async def session_agent_lock(session_id: str):
    """
    Convenience function for session agent locking.

    Prevents concurrent agent runs for the same session.

    Usage:
        async with session_agent_lock(session_id):
            result = await agent.run(question)
    """
    return distributed_lock(
        f"session:{session_id}:agent",
        ttl_seconds=600,  # 10 minute max for agent runs
        acquire_timeout=5.0,  # Don't wait long, reject if busy
    )


async def checkpoint_lock(thread_id: str):
    """
    Convenience function for checkpoint write locking.

    Prevents race conditions when writing checkpoints.

    Usage:
        async with checkpoint_lock(thread_id):
            await checkpointer.put(...)
    """
    return distributed_lock(
        f"checkpoint:{thread_id}",
        ttl_seconds=30,
        acquire_timeout=10.0,
    )


async def schema_refresh_lock(connection_hash: str):
    """
    Convenience function for schema refresh locking.

    Prevents multiple instances from refreshing schema simultaneously.

    Usage:
        async with schema_refresh_lock(connection_hash):
            await refresh_schema(...)
    """
    return distributed_lock(
        f"schema:{connection_hash}",
        ttl_seconds=120,  # Schema refresh can take a while
        acquire_timeout=5.0,  # Don't queue up, skip if another is running
    )


async def refresh_table_lock(
    connection_hash: str,
    schema_name: Optional[str],
    table_name: str,
):
    """
    Per-table schema refresh lock — finer-grained companion to
    ``schema_refresh_lock``.

    The connection-scoped lock serialises every per-table refresh,
    which is annoying when 3 different "column not found" errors
    fire on 3 different tables in parallel. Per-table locks keep
    each refresh independent.

    Lock key: ``schema:{conn_hash}:{schema}.{table}``

    TTL is shorter (60 s) because a single-table refresh is fast
    relative to a full re-extraction. Acquire timeout stays at 5 s
    so concurrent refresh attempts skip rather than queue.

    Usage:
        async with refresh_table_lock(conn_hash, schema, table):
            ok = await refresh_table_schema(...)
    """
    qualified = (
        f"{schema_name}.{table_name}" if schema_name else table_name
    )
    return distributed_lock(
        f"schema:{connection_hash}:{qualified}",
        ttl_seconds=60,
        acquire_timeout=5.0,
    )


# ==============================================================================
# INITIALIZATION
# ==============================================================================


def init_distributed_locking():
    """
    Initialize distributed locking service.

    Call this at application startup to eagerly connect to Redis.
    """
    DistributedLock._init_redis()
    return DistributedLock._redis_client is not None


async def get_lock_stats() -> dict:
    """Get statistics about distributed locking."""
    redis_available = await DistributedLock._ensure_redis()

    if not redis_available:
        local_lock_count = len(DistributedLock._local_locks)
        return {
            "backend": "local",
            "distributed": False,
            "local_locks": local_lock_count,
            "local_lock_names": list(DistributedLock._local_locks.keys())[:10],
            "message": "Redis not available, using local asyncio locks (single-process protection only)",
        }

    redis_client = DistributedLock._redis_client
    assert redis_client is not None

    try:
        # Count active locks
        cursor = 0
        lock_count = 0
        lock_keys = []

        while True:
            cursor, keys = await redis_client.scan(
                cursor, match="lock:*", count=100
            )
            lock_count += len(keys)
            lock_keys.extend(keys[:10])  # Sample first 10

            if cursor == 0:
                break

        return {
            "backend": "redis",
            "distributed": True,
            "active_locks": lock_count,
            "sample_locks": lock_keys,
        }

    except Exception as e:
        return {
            "backend": "redis",
            "distributed": True,
            "error": str(e),
        }
