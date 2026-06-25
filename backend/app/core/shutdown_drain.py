"""
Graceful shutdown drain manager (Phase 2 Day 4).

Tracks in-flight HTTP requests so application shutdown can wait for them
to complete before closing connection pools / checkpointer / sessions.
Without this, active SSE streams and long-running data-lake queries get
"connection closed" errors at shutdown.

Used as:

    drain = ShutdownDrainManager()

    @app.middleware("http")
    async def track(request, call_next):
        async with drain.track_request():
            return await call_next(request)

    @asynccontextmanager
    async def lifespan(app):
        yield
        # on shutdown:
        await drain.drain(timeout=30)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class ShutdownDrainManager:
    """Track active HTTP requests and wait for them to finish at shutdown."""

    def __init__(self) -> None:
        self._active = 0
        self._cond = asyncio.Condition()
        self._draining = False

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def is_draining(self) -> bool:
        return self._draining

    async def _enter(self) -> None:
        async with self._cond:
            self._active += 1

    async def _exit(self) -> None:
        async with self._cond:
            self._active -= 1
            if self._active <= 0:
                self._cond.notify_all()

    @asynccontextmanager
    async def track_request(self) -> AsyncIterator[None]:
        """Async context manager that increments/decrements the active count."""
        await self._enter()
        try:
            yield
        finally:
            await self._exit()

    async def drain(self, timeout: float = 30.0) -> bool:
        """
        Mark the app as draining and wait up to ``timeout`` seconds for
        ``active_count`` to reach 0. Returns True if drained in time,
        False if the timeout fired with requests still in flight.
        """
        self._draining = True
        if self._active <= 0:
            logger.info("Shutdown drain: no active requests; draining immediate")
            return True

        logger.info(
            f"Shutdown drain: waiting for {self._active} active request(s) "
            f"to finish (timeout={timeout}s)"
        )

        async def _wait() -> None:
            async with self._cond:
                while self._active > 0:
                    await self._cond.wait()

        try:
            await asyncio.wait_for(_wait(), timeout=timeout)
            logger.info("Shutdown drain: all requests completed")
            return True
        except asyncio.TimeoutError:
            try:
                from app.api.metrics import record_fix_event
                record_fix_event("shutdown_drain_timeout")
            except Exception:
                pass
            logger.warning(
                f"Shutdown drain: timeout with {self._active} request(s) "
                f"still in flight; proceeding with shutdown anyway"
            )
            return False


# Module-level singleton — wired into main.app's middleware + lifespan.
drain_manager = ShutdownDrainManager()
