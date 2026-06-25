"""
Async executor protocol + registry (Phase 3b.1).

Native-async query execution for data-lake databases. The legacy
``connection_pool_manager`` wraps every sync DB driver in a
ThreadPoolExecutor; for async-capable cloud warehouses (BigQuery's
``QueryJob``, Snowflake's ``execute_async``) that's doubly wasteful — an
asyncio task waiting on a thread pool that's waiting on HTTP polls.

This module defines the protocol concrete drivers implement, plus a
registry so the pool manager can check ``is_async_native_db(db_type)``
and route accordingly. This commit ships the abstraction only; the
actual BigQuery / Snowflake implementations are Phase 3b.3/3b.4 and
require real credentials to validate — they register themselves via
``async_executor_registry.register(db_type, factory)`` on import.

Design choices:
  - ``QueryHandle`` is a dataclass (not just a string ID) so drivers
    can attach driver-specific state (e.g. the BigQuery ``QueryJob``
    object) without the caller needing to know the driver type.
  - ``AsyncExecutorProtocol`` is a ``typing.Protocol`` subclass AND an
    ABC — ``Protocol`` gives us structural typing for mypy / runtime
    checks, ABC forces explicit subclasses to implement every method
    (TypeError at instantiation if they don't), which we want for
    drivers we ship.
  - Registry is a singleton but exposes ``register``/``unregister``
    so tests can install fakes and clean up.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------
# Handle type
# --------------------------------------------------------------------------


@dataclass
class QueryHandle:
    """
    Minimal handle a driver returns when a query is started.

    ``query_id`` is the driver's identifier used for polling /
    cancellation. ``db_type`` lets middleware dispatch the right
    registered executor without carrying the handle's concrete class
    around. ``driver_state`` is an opaque slot drivers can use to stash
    the driver-specific object (e.g. a ``QueryJob``) so subsequent
    calls don't need to re-resolve it.
    """

    query_id: str
    db_type: str
    driver_state: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Protocol / ABC
# --------------------------------------------------------------------------


class AsyncExecutorProtocol(ABC):
    """
    Contract for a native-async query executor.

    Lifecycle:
        handle = await executor.start_query(sql, ...)
        while await executor.poll_status(handle) in {"pending", "running"}:
            progress = await executor.get_progress(handle)  # optional
            await asyncio.sleep(1.0)
        if status == "complete":
            result = await executor.fetch_results(handle, limit=...)
        else:
            # "cancelled" or "failed"
            ...

    Cancellation is explicit: a caller that times out should call
    ``executor.cancel(handle)`` to stop billing (BigQuery) or free
    the compute (Snowflake).
    """

    @abstractmethod
    async def start_query(self, sql: str, **kwargs: Any) -> QueryHandle:
        """Submit a query and return a handle; MUST NOT block on results."""

    @abstractmethod
    async def poll_status(self, handle: QueryHandle) -> str:
        """
        Return one of: "pending", "running", "complete", "cancelled",
        "failed". Must be cheap enough to call every ~1s.
        """

    @abstractmethod
    async def fetch_results(
        self, handle: QueryHandle, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Return ``{"rows": [...], "columns": [...], "row_count": N, ...}``.
        Only valid when poll_status() last returned "complete".
        """

    @abstractmethod
    async def cancel(self, handle: QueryHandle) -> bool:
        """
        Ask the DB to cancel the query. Returns True if cancellation was
        acknowledged (NOT necessarily that execution actually stopped;
        for BigQuery / Snowflake this is best-effort but typically
        stops billing).
        """

    @abstractmethod
    async def get_progress(
        self, handle: QueryHandle
    ) -> Optional[Dict[str, Any]]:
        """
        Return progress metrics if the driver exposes them, else None.
        Shape is driver-specific but the recommended keys are:
            bytes_scanned: int
            rows_read: int
            percent: float      # if the driver estimates progress
        ``None`` is a valid answer (Athena/Trino don't expose progress).
        """


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


ExecutorFactory = Callable[[Any], AsyncExecutorProtocol]


class AsyncExecutorRegistry:
    """
    Singleton-friendly registry mapping ``db_type`` → executor factory.

    Drivers register themselves at import time (once their dependencies
    are importable). Callers check ``is_async_native(db_type)`` before
    deciding whether to route through this registry or fall back to the
    legacy pool manager path.

    Thread-safe via a module-level lock: registration typically happens
    at import, but the helpers accept concurrent reads from the request
    path without a lock since dict reads are atomic under the GIL for
    string keys.
    """

    _lock = threading.Lock()

    def __init__(self) -> None:
        self._factories: Dict[str, ExecutorFactory] = {}

    def register(self, db_type: str, factory: ExecutorFactory) -> None:
        """Install a factory for ``db_type``. Overwrites if already present."""
        key = db_type.lower()
        with self._lock:
            if key in self._factories:
                logger.warning(
                    "AsyncExecutorRegistry: overwriting existing factory for %r",
                    key,
                )
            self._factories[key] = factory
            logger.info("AsyncExecutorRegistry: registered async executor for %r", key)

    def unregister(self, db_type: str) -> None:
        """Remove a factory. No-op if not registered."""
        key = db_type.lower()
        with self._lock:
            self._factories.pop(key, None)

    def is_async_native(self, db_type: Optional[str]) -> bool:
        """True if a native-async executor is registered for this db_type."""
        if not db_type:
            return False
        return db_type.lower() in self._factories

    def get_factory(self, db_type: str) -> Optional[ExecutorFactory]:
        """Return the factory for ``db_type`` (or None)."""
        if not db_type:
            return None
        return self._factories.get(db_type.lower())

    def create(
        self, db_type: str, config: Any
    ) -> Optional[AsyncExecutorProtocol]:
        """Instantiate an executor for ``db_type`` using its registered factory."""
        factory = self.get_factory(db_type)
        if factory is None:
            return None
        return factory(config)

    # Introspection helper for diagnostics.
    def registered_db_types(self) -> list:
        with self._lock:
            return sorted(self._factories.keys())


# Module-level singleton. Drivers register here at import; callers check
# ``is_async_native()`` to decide whether to route through this path.
async_executor_registry = AsyncExecutorRegistry()
