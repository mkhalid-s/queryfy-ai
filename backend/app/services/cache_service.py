"""
QueryfyAI - Unified Cache Service

Provides caching with automatic fallback:
- Redis if available (distributed, persistent)
- In-memory with TTL (development/fallback)

Cache Types:
- LLM Response Cache: Same prompt+schema = same SQL (1 hour TTL)
- Query Result Cache: Same SQL+DB = same results (5 min TTL)
- Schema Cache: Database schema (1 hour TTL)
"""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BaseCacheBackend(ABC):
    """Abstract cache backend interface"""

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> int:
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    async def get_ttl(self, key: str) -> int:
        pass

    @abstractmethod
    async def ping(self) -> bool:
        pass


class MemoryCacheBackend(BaseCacheBackend):
    """
    In-memory cache with TTL support.
    Simple dict-based, thread-safe for async operations.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._stats = {"hits": 0, "misses": 0, "sets": 0}
        logger.info("Initialized in-memory cache backend")

    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """Check if cache entry has expired"""
        if entry.get("expires_at") is None:
            return False
        return time.time() > entry["expires_at"]

    def _cleanup_expired(self):
        """Remove expired entries (called periodically)"""
        now = time.time()
        expired = [
            k
            for k, v in self._cache.items()
            if v.get("expires_at") and now > v["expires_at"]
        ]
        for key in expired:
            del self._cache[key]
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired cache entries")

    async def get(self, key: str) -> Optional[str]:
        entry = self._cache.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        if self._is_expired(entry):
            del self._cache[key]
            self._stats["misses"] += 1
            return None

        self._stats["hits"] += 1
        return entry["value"]

    async def set(self, key: str, value: str, ttl: int) -> None:
        expires_at = time.time() + ttl if ttl > 0 else None
        self._cache[key] = {
            "value": value,
            "created_at": time.time(),
            "expires_at": expires_at,
        }
        self._stats["sets"] += 1

        # Cleanup every 100 sets
        if self._stats["sets"] % 100 == 0:
            self._cleanup_expired()

    async def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all keys matching prefix"""
        keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
        for key in keys_to_delete:
            del self._cache[key]
        return len(keys_to_delete)

    async def exists(self, key: str) -> bool:
        entry = self._cache.get(key)
        if entry is None:
            return False
        if self._is_expired(entry):
            del self._cache[key]
            return False
        return True

    async def get_ttl(self, key: str) -> int:
        """Get remaining TTL in seconds"""
        entry = self._cache.get(key)
        if entry is None or self._is_expired(entry):
            return -1
        if entry.get("expires_at") is None:
            return -1
        return max(0, int(entry["expires_at"] - time.time()))

    async def ping(self) -> bool:
        return True

    def get_stats(self) -> Dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0
        return {
            "backend": "memory",
            "entries": len(self._cache),
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": round(hit_rate, 3),
            "sets": self._stats["sets"],
        }


class RedisCacheBackend(BaseCacheBackend):
    """
    Redis cache backend for distributed caching.
    Used in production for multi-worker/multi-node deployments.
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._client = None
        self._stats = {"hits": 0, "misses": 0, "sets": 0}

    async def _get_client(self):
        """Lazy initialization of Redis client"""
        if self._client is None:
            try:
                import redis.asyncio as redis

                self._client = redis.from_url(
                    self.redis_url, encoding="utf-8", decode_responses=True
                )
                logger.info(f"Connected to Redis at {self.redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        return self._client

    async def get(self, key: str) -> Optional[str]:
        try:
            client = await self._get_client()
            value = await client.get(key)
            if value is None:
                self._stats["misses"] += 1
            else:
                self._stats["hits"] += 1
            return value
        except Exception as e:
            logger.warning(f"Redis GET failed: {e}")
            self._stats["misses"] += 1
            return None

    async def set(self, key: str, value: str, ttl: int) -> None:
        try:
            client = await self._get_client()
            if ttl > 0:
                await client.setex(key, ttl, value)
            else:
                await client.set(key, value)
            self._stats["sets"] += 1
        except Exception as e:
            logger.warning(f"Redis SET failed: {e}")

    async def delete(self, key: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(key)
        except Exception as e:
            logger.warning(f"Redis DELETE failed: {e}")

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all keys matching prefix pattern"""
        try:
            client = await self._get_client()
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await client.scan(cursor, match=f"{prefix}*", count=100)
                if keys:
                    await client.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as e:
            logger.warning(f"Redis DELETE PREFIX failed: {e}")
            return 0

    async def exists(self, key: str) -> bool:
        try:
            client = await self._get_client()
            return await client.exists(key) > 0
        except Exception as e:
            logger.warning(f"Redis EXISTS failed: {e}")
            return False

    async def get_ttl(self, key: str) -> int:
        try:
            client = await self._get_client()
            ttl = await client.ttl(key)
            return ttl if ttl > 0 else -1
        except Exception as e:
            logger.warning(f"Redis TTL failed: {e}")
            return -1

    async def ping(self) -> bool:
        try:
            client = await self._get_client()
            return await client.ping()
        except Exception as e:
            logger.warning(f"Redis PING failed: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0
        return {
            "backend": "redis",
            "redis_url": (
                self.redis_url.split("@")[-1]
                if "@" in self.redis_url
                else self.redis_url
            ),
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": round(hit_rate, 3),
            "sets": self._stats["sets"],
        }


class CacheService:
    """
    Unified caching layer with automatic fallback.

    Usage:
        cache = CacheService(redis_url=settings.REDIS_URL)
        await cache.initialize()

        # LLM responses
        sql = await cache.get_llm_response(prompt_hash)
        await cache.set_llm_response(prompt_hash, sql)

        # Query results
        result = await cache.get_query_result(cache_key)
        await cache.set_query_result(cache_key, result)
    """

    # Cache key prefixes
    PREFIX_LLM = "llm:"
    PREFIX_QUERY = "query:"
    PREFIX_SCHEMA = "schema:"

    # Default TTLs (can be overridden via settings)
    DEFAULT_TTL_LLM = 3600  # 1 hour
    DEFAULT_TTL_QUERY = 300  # 5 minutes
    DEFAULT_TTL_SCHEMA = 3600  # 1 hour

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self._backend: Optional[BaseCacheBackend] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize cache backend (Redis or memory fallback)"""
        if self._initialized:
            return

        if self.redis_url and self.redis_url != "":
            try:
                backend = RedisCacheBackend(self.redis_url)
                if await backend.ping():
                    self._backend = backend
                    logger.info("Cache initialized with Redis backend")
                else:
                    raise Exception("Redis ping failed")
            except Exception as e:
                logger.warning(f"Redis unavailable ({e}), falling back to memory cache")
                self._backend = MemoryCacheBackend()
        else:
            logger.info("No Redis URL configured, using memory cache")
            self._backend = MemoryCacheBackend()

        self._initialized = True

    def _ensure_initialized(self):
        """Ensure backend is initialized"""
        if not self._initialized or self._backend is None:
            # Sync fallback for when async init wasn't called
            self._backend = MemoryCacheBackend()
            self._initialized = True

    # ============ LLM Response Cache ============

    @staticmethod
    def hash_prompt(prompt: str, schema: str, db_type: str) -> str:
        """Generate hash for LLM cache key"""
        content = f"{prompt}|{schema}|{db_type}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def get_llm_response(self, prompt_hash: str) -> Optional[str]:
        """Get cached LLM response"""
        self._ensure_initialized()
        if self._backend is None:
            return None
        key = f"{self.PREFIX_LLM}{prompt_hash}"
        return await self._backend.get(key)

    async def set_llm_response(
        self, prompt_hash: str, response: str, ttl: Optional[int] = None
    ) -> None:
        """Cache LLM response"""
        self._ensure_initialized()
        if self._backend is None:
            return
        key = f"{self.PREFIX_LLM}{prompt_hash}"
        await self._backend.set(key, response, ttl or self.DEFAULT_TTL_LLM)

    # ============ Query Result Cache ============

    async def get_query_result(self, cache_key: str) -> Optional[Dict]:
        """Get cached query result"""
        self._ensure_initialized()
        if self._backend is None:
            return None
        key = f"{self.PREFIX_QUERY}{cache_key}"
        value = await self._backend.get(key)
        if value:
            return json.loads(value)
        return None

    async def set_query_result(
        self, cache_key: str, result: Dict, ttl: Optional[int] = None
    ) -> None:
        """Cache query result"""
        self._ensure_initialized()
        if self._backend is None:
            return
        key = f"{self.PREFIX_QUERY}{cache_key}"
        await self._backend.set(key, json.dumps(result), ttl or self.DEFAULT_TTL_QUERY)

    async def get_cache_age(self, cache_key: str) -> int:
        """Get age of cache entry in seconds (based on remaining TTL)"""
        self._ensure_initialized()
        if self._backend is None:
            return -1
        key = f"{self.PREFIX_QUERY}{cache_key}"
        remaining_ttl = await self._backend.get_ttl(key)
        if remaining_ttl < 0:
            return -1
        # Estimate age based on default TTL
        return max(0, self.DEFAULT_TTL_QUERY - remaining_ttl)

    # ============ Schema Cache ============

    async def get_schema(self, db_hash: str) -> Optional[Dict]:
        """Get cached schema"""
        self._ensure_initialized()
        if self._backend is None:
            return None
        key = f"{self.PREFIX_SCHEMA}{db_hash}"
        value = await self._backend.get(key)
        if value:
            return json.loads(value)
        return None

    async def set_schema(self, db_hash: str, schema: Dict, ttl: Optional[int] = None) -> None:
        """Cache schema"""
        self._ensure_initialized()
        if self._backend is None:
            return
        key = f"{self.PREFIX_SCHEMA}{db_hash}"
        await self._backend.set(key, json.dumps(schema), ttl or self.DEFAULT_TTL_SCHEMA)

    # ============ Invalidation ============

    async def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all cache entries with prefix"""
        self._ensure_initialized()
        if self._backend is None:
            return 0
        return await self._backend.delete_prefix(prefix)

    async def invalidate_db_cache(self, db_hash: str) -> int:
        """Invalidate all cache entries for a database"""
        self._ensure_initialized()
        if self._backend is None:
            return 0
        deleted = 0
        deleted += await self._backend.delete_prefix(f"{self.PREFIX_QUERY}{db_hash}")
        deleted += await self._backend.delete_prefix(f"{self.PREFIX_SCHEMA}{db_hash}")
        logger.info(f"Invalidated {deleted} cache entries for db:{db_hash[:8]}")
        return deleted

    async def clear_all(self) -> None:
        """Clear all cache entries"""
        self._ensure_initialized()
        if self._backend is None:
            return
        await self._backend.delete_prefix(self.PREFIX_LLM)
        await self._backend.delete_prefix(self.PREFIX_QUERY)
        await self._backend.delete_prefix(self.PREFIX_SCHEMA)
        logger.info("Cleared all cache entries")

    # ============ Health & Stats ============

    async def ping(self) -> bool:
        """Check cache backend health"""
        self._ensure_initialized()
        if self._backend is None:
            return False
        return await self._backend.ping()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        self._ensure_initialized()
        if self._backend is None or not hasattr(self._backend, 'get_stats'):
            return {}
        return self._backend.get_stats()  # type: ignore[attr-defined]

    def get_llm_hit_rate(self) -> float:
        """Get LLM cache hit rate"""
        stats = self.get_stats()
        return stats.get("hit_rate", 0.0)

    def get_query_hit_rate(self) -> float:
        """Get query cache hit rate"""
        stats = self.get_stats()
        return stats.get("hit_rate", 0.0)


# Global instance - will be initialized in main.py
cache_service = CacheService()


async def initialize_cache(redis_url: Optional[str] = None) -> CacheService:
    """Initialize global cache service (modifies existing instance)"""
    global cache_service
    # Update the existing instance instead of creating new one
    # This preserves import bindings in other modules
    cache_service.redis_url = redis_url
    cache_service._initialized = False  # Reset to allow re-initialization
    cache_service._backend = None
    await cache_service.initialize()
    return cache_service
