"""
ResultCache — server-side row storage keyed by query_id (Phase 4.0).

Rationale
---------
The tool layer ``execute_and_analyze`` historically tried to return:
  - analysis outputs (insights, statistics, quality, chart) — small
  - the full row set — can be MB for 10k rows

The combined payload hits the 50KB ``max_tool_output`` guard, the tool
returns ``success: false``, and the agent retries with progressively
simplified SQL. The user sees analytics on a degraded query that's
different from what they asked.

Phase 4 splits these two concerns:
  - Analysis outputs ride in the tool response (always <50KB).
  - The full row set is stored server-side in this cache under a
    ``rows_ref`` handle. The frontend UI fetches it via a dedicated
    HTTP endpoint; the LLM fetches slices via new follow-up tools.

Backend: Redis-first (shared across workers, survives restarts within
TTL). Falls back to a thread-safe in-memory dict when Redis is
unavailable — safe for single-worker dev only, matches the existing
session-store degradation pattern.

Key format: ``result:{session_id}:{query_id}``.
TTL: ``settings.RESULT_CACHE_TTL_SECONDS`` (default: 1800s / 30 min —
matches session TTL, so a result outlives the conversation turn that
produced it but not the session).
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


# Default TTL — 30 min matches the default session TTL so a cached
# result outlives the turn that created it but not the session.
_DEFAULT_TTL = int(getattr(settings, "RESULT_CACHE_TTL_SECONDS", 1800))

# Phase 4 hotfix: bound the in-memory fallback so a prolonged Redis
# outage can't blow the heap. OrderedDict + popitem(last=False) gives
# LRU-ish eviction (move-to-end on access, evict from head on write).
# Default cap ~200 entries × est. ~1MB/entry = ~200MB ceiling, which
# is the right order of magnitude for a single-worker fallback.
_MEMORY_STORE_MAX_ENTRIES = int(
    getattr(settings, "RESULT_CACHE_MEMORY_MAX_ENTRIES", 200)
)


def _emit_cache_metric(operation: str, result: str) -> None:
    """
    Increment ``queryfyai_result_cache_operations_total{operation, result}``.

    Lazy import so this module stays independent of the metrics layer
    at import time (matches the session_store / metrics dependency
    direction). Best-effort: never raises into the cache hot path.
    """
    try:
        from app.api.metrics import record_cache_operation

        record_cache_operation(operation, result)
    except Exception:  # pragma: no cover — metrics is best-effort
        pass


def _scrub_non_finite_floats(value: Any) -> Any:
    """
    Recursively replace NaN / +Inf / -Inf with None.

    json.dumps emits these as bare ``NaN`` / ``Infinity`` tokens, which
    JavaScript's JSON.parse rejects with SyntaxError. The fix is to
    scrub at write time so anything pulled out of the cache is safe to
    JSON.parse() in the browser.
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _scrub_non_finite_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_non_finite_floats(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_scrub_non_finite_floats(v) for v in value)
    return value


@dataclass
class CachedResult:
    """In-memory representation of a cached query result."""

    rows_ref: str
    session_id: str
    query_id: str
    sql: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    db_type: Optional[str] = None
    created_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> bytes:
        """
        Serialize for Redis storage. JSON (not pickle) for safety.

        Phase 4 hardening: pass ``allow_nan=False`` so we never write
        bare NaN / Infinity tokens to Redis. Python's json.dumps writes
        them by default (producing JSON the browser's JSON.parse rejects
        with SyntaxError), so we scrub them to None first via
        ``_scrub_non_finite_floats``. Without this, a single NaN cell
        in a cached row makes the entire ResultsExpander fetch fail
        silently and the table renders as empty.
        """
        payload = {
            "rows_ref": self.rows_ref,
            "session_id": self.session_id,
            "query_id": self.query_id,
            "sql": self.sql,
            "columns": self.columns,
            "rows": _scrub_non_finite_floats(self.rows),
            "row_count": self.row_count,
            "db_type": self.db_type,
            "created_at": self.created_at,
            "metadata": _scrub_non_finite_floats(self.metadata),
        }
        return json.dumps(
            payload,
            default=str,
            allow_nan=False,  # belt + braces — _scrub already handles this
        ).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "CachedResult":
        data = json.loads(raw.decode("utf-8"))
        return cls(**data)


class ResultCache:
    """Redis-first query result cache with in-memory fallback."""

    _instance: Optional["ResultCache"] = None

    def __new__(cls) -> "ResultCache":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.redis_client: Optional[Any] = None
        # OrderedDict so we can evict oldest-first when over cap.
        self._memory_store: "OrderedDict[str, bytes]" = OrderedDict()
        self._memory_lock = threading.Lock()
        self._init_redis()
        self._initialized = True

    def _init_redis(self) -> None:
        try:
            import redis

            self.redis_client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=False,
                socket_connect_timeout=2,
                # Phase 4 hotfix: read/write timeout. Without this a
                # Redis that hangs on SETEX (memory-pressure, failover
                # mid-write) ties up a thread-pool worker for the OS
                # default (often >60s). 5s is well under any reasonable
                # analyst-timeout budget.
                socket_timeout=5,
            )
            self.redis_client.ping()
            logger.info(
                "✓ ResultCache: Redis connected (results persist for %ds TTL)",
                _DEFAULT_TTL,
            )
        except Exception as e:
            logger.warning(
                f"⚠ ResultCache: Redis not available ({e}) — using in-memory "
                f"(single-worker only; results lost on restart)"
            )
            self.redis_client = None

    # ------------------------------------------------------------------
    # Key scheme
    # ------------------------------------------------------------------

    @staticmethod
    def make_rows_ref(session_id: str, query_id: str) -> str:
        """Build the ``rows_ref`` handle exposed to the frontend / LLM."""
        return f"result:{session_id}:{query_id}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        session_id: str,
        query_id: str,
        sql: str,
        columns: List[str],
        rows: List[Dict[str, Any]],
        row_count: Optional[int] = None,
        db_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """
        Persist a query result and return the ``rows_ref`` handle.

        ``row_count`` defaults to ``len(rows)`` if omitted; supply
        explicitly when ``rows`` is a truncated subset and you want to
        record the full DB row count in metadata.
        """
        rows_ref = self.make_rows_ref(session_id, query_id)
        result = CachedResult(
            rows_ref=rows_ref,
            session_id=session_id,
            query_id=query_id,
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=row_count if row_count is not None else len(rows),
            db_type=db_type,
            created_at=datetime.now().isoformat(),
            metadata=metadata or {},
        )

        payload = result.to_json()
        ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL

        if self.redis_client is not None:
            try:
                self.redis_client.setex(rows_ref, ttl, payload)
                logger.debug(
                    "ResultCache[redis]: stored %s (%d rows, %d bytes, ttl=%ds)",
                    rows_ref,
                    result.row_count,
                    len(payload),
                    ttl,
                )
                _emit_cache_metric("store", "hit")
                return rows_ref
            except Exception as e:
                logger.warning(
                    f"ResultCache[redis]: store failed for {rows_ref}: {e} — "
                    f"falling back to memory"
                )
                _emit_cache_metric("store", "error")

        with self._memory_lock:
            # LRU eviction: pop the oldest entry if we're at the cap
            # AND this key isn't already present (an overwrite doesn't
            # grow the dict). Without this an extended Redis outage
            # piles fallback writes into an unbounded heap.
            if (
                rows_ref not in self._memory_store
                and len(self._memory_store) >= _MEMORY_STORE_MAX_ENTRIES
            ):
                evicted_key, _ = self._memory_store.popitem(last=False)
                logger.warning(
                    "ResultCache[memory]: evicted oldest entry %s "
                    "(cap=%d reached — Redis outage?)",
                    evicted_key,
                    _MEMORY_STORE_MAX_ENTRIES,
                )
            self._memory_store[rows_ref] = payload
            # Move-to-end so recent writes/reads stay fresh.
            self._memory_store.move_to_end(rows_ref)
            logger.debug(
                "ResultCache[memory]: stored %s (%d rows, %d bytes)",
                rows_ref,
                result.row_count,
                len(payload),
            )
        _emit_cache_metric("store", "hit")
        return rows_ref

    # Hotfix: hard ceiling on any single cache I/O via asyncio.wait_for.
    # Protects against a hung Redis tying up a worker thread forever.
    # Falls through to the store's in-memory fallback on timeout (the
    # sync ``store`` already does that branch on a raised exception).
    _IO_TIMEOUT_SECONDS = 10.0

    async def astore(self, *args, **kwargs) -> str:
        """
        Phase 4 Batch E: async wrapper around ``store`` that runs the
        sync redis-py SETEX in a worker thread via asyncio.to_thread.
        For 9000-row payloads (~200ms write) this prevents stalling the
        event loop driving the SSE heartbeat / query_progress merger.
        Use from any async caller (``execute_and_analyze`` already does).
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self.store, *args, **kwargs),
                timeout=self._IO_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # Structured log so ops can alert on a spike of astore
            # timeouts (symptom of Redis degradation).
            logger.error(
                "cache.store.timeout",
                extra={
                    "operation": "astore",
                    "timeout_seconds": self._IO_TIMEOUT_SECONDS,
                    "fallback": "memory",
                },
            )
            # Disable the redis client so subsequent calls skip it
            # directly rather than piling up more timeouts.
            self.redis_client = None
            return self.store(*args, **kwargs)

    async def aget(self, rows_ref: str) -> Optional[CachedResult]:
        """Async wrapper around ``get`` for the same reasons as ``astore``."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self.get, rows_ref),
                timeout=self._IO_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "ResultCache.aget: I/O timeout for %s — returning None", rows_ref
            )
            # Surface the timeout as a cache error so a Redis-degraded
            # environment shows up in the metric, not just in logs.
            _emit_cache_metric("get", "error")
            return None

    async def aget_rows_slice(
        self,
        rows_ref: str,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Async wrapper around ``get_rows_slice``."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self.get_rows_slice, rows_ref, offset, limit
                ),
                timeout=self._IO_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "ResultCache.aget_rows_slice: I/O timeout for %s", rows_ref
            )
            return None

    def get(self, rows_ref: str) -> Optional[CachedResult]:
        """Return the full cached result, or ``None`` if missing / expired."""
        if self.redis_client is not None:
            try:
                raw = self.redis_client.get(rows_ref)
                if raw is not None:
                    _emit_cache_metric("get", "hit")
                    return CachedResult.from_json(raw)
            except Exception as e:
                logger.warning(
                    f"ResultCache[redis]: get failed for {rows_ref}: {e} — "
                    f"checking memory"
                )
                _emit_cache_metric("get", "error")

        with self._memory_lock:
            raw = self._memory_store.get(rows_ref)
        if raw is None:
            _emit_cache_metric("get", "miss")
            return None
        _emit_cache_metric("get", "hit")
        return CachedResult.from_json(raw)

    def get_rows_slice(
        self,
        rows_ref: str,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Return a paginated slice. ``limit=None`` means all rows from
        offset (bounded by total length).

        Return shape:
            {
                "rows": [...],
                "columns": [...],
                "offset": N,
                "limit": M,
                "total_row_count": K,
                "rows_ref": str,
                "has_more": bool,
            }
        None when the key is missing.
        """
        # Structured log at the slice boundary so cache hit rate is
        # observable from log aggregation alone, with no new metrics
        # pipeline required. Timer surrounds only the network/store
        # call — cheap.
        import time as _time
        t0 = _time.monotonic()
        cached = self.get(rows_ref)
        latency_ms = int((_time.monotonic() - t0) * 1000)
        if cached is None:
            logger.info(
                "cache.slice",
                extra={
                    "rows_ref": rows_ref,
                    "offset": offset,
                    "limit": limit,
                    "hit": False,
                    "latency_ms": latency_ms,
                },
            )
            return None
        total = cached.row_count
        if offset < 0:
            offset = 0
        if limit is None:
            sliced = cached.rows[offset:]
        else:
            sliced = cached.rows[offset : offset + limit]
        logger.info(
            "cache.slice",
            extra={
                "rows_ref": rows_ref,
                "offset": offset,
                "limit": limit if limit is not None else len(sliced),
                "hit": True,
                "latency_ms": latency_ms,
                "total_rows": total,
            },
        )
        return {
            "rows": sliced,
            "columns": cached.columns,
            "offset": offset,
            "limit": limit if limit is not None else len(sliced),
            "total_row_count": total,
            "rows_ref": rows_ref,
            "sql": cached.sql,
            "has_more": (offset + len(sliced)) < total,
        }

    def delete(self, rows_ref: str) -> bool:
        """Remove an entry. Returns True if something was deleted."""
        removed = False
        if self.redis_client is not None:
            try:
                removed = bool(self.redis_client.delete(rows_ref))
            except Exception as e:
                logger.warning(
                    f"ResultCache[redis]: delete failed for {rows_ref}: {e}"
                )
        with self._memory_lock:
            if self._memory_store.pop(rows_ref, None) is not None:
                removed = True
        return removed

    def delete_session(self, session_id: str) -> int:
        """Remove every entry belonging to a session. Returns the count."""
        prefix = f"result:{session_id}:"
        removed = 0
        if self.redis_client is not None:
            try:
                keys = self.redis_client.keys(f"{prefix}*")
                if keys:
                    removed += int(self.redis_client.delete(*keys))
            except Exception as e:
                logger.warning(
                    f"ResultCache[redis]: session purge failed for {session_id}: {e}"
                )
        with self._memory_lock:
            to_drop = [k for k in self._memory_store if k.startswith(prefix)]
            for k in to_drop:
                self._memory_store.pop(k, None)
                removed += 1
        return removed

    def size(self) -> int:
        """Count of entries in the active backend (diagnostic)."""
        if self.redis_client is not None:
            try:
                return len(self.redis_client.keys("result:*"))
            except Exception:
                pass
        with self._memory_lock:
            return len(self._memory_store)


# Module-level singleton — callers import this.
result_cache = ResultCache()
