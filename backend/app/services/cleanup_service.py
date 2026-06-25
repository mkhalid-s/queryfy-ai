"""
QueryfyAI - Cleanup Service

Background service for cleaning up stale data:
- Expired in-memory sessions
- SQL integrity registry entries
- LangGraph PostgreSQL checkpoints
- Cache entries
- Rate limiter data

Runs as a background asyncio task with configurable intervals.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CleanupStats:
    """Track cleanup statistics"""

    last_run: Optional[datetime] = None
    total_runs: int = 0
    sessions_cleaned: int = 0
    sql_entries_cleaned: int = 0
    checkpoints_cleaned: int = 0
    cache_entries_cleaned: int = 0
    errors: int = 0
    last_error: Optional[str] = None


class CleanupService:
    """
    Background cleanup service for stale application data.

    Usage:
        cleanup_service = CleanupService()
        await cleanup_service.start()
        # ... application runs ...
        await cleanup_service.stop()
    """

    def __init__(
        self,
        cleanup_interval_seconds: int = 300,  # 5 minutes
        session_max_age_hours: int = 24,
        sql_registry_max_age_hours: int = 2,
        checkpoint_max_age_hours: int = 48,
    ):
        self.cleanup_interval = cleanup_interval_seconds
        self.session_max_age = timedelta(hours=session_max_age_hours)
        self.sql_registry_max_age = timedelta(hours=sql_registry_max_age_hours)
        self.checkpoint_max_age = timedelta(hours=checkpoint_max_age_hours)

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.stats = CleanupStats()

    async def start(self) -> None:
        """Start the background cleanup task"""
        if self._running:
            logger.warning("Cleanup service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            f"Cleanup service started (interval: {self.cleanup_interval}s, "
            f"session_age: {self.session_max_age}, "
            f"sql_age: {self.sql_registry_max_age})"
        )

    async def stop(self) -> None:
        """Stop the background cleanup task gracefully"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Cleanup service stopped")

    async def _cleanup_loop(self) -> None:
        """Main cleanup loop - runs periodically"""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self.run_cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats.errors += 1
                self.stats.last_error = str(e)
                logger.error(f"Cleanup loop error: {e}")
                # Continue running despite errors
                await asyncio.sleep(60)  # Wait before retry

    async def run_cleanup(self) -> Dict[str, Any]:
        """
        Run all cleanup tasks.
        Can be called manually or by the background loop.

        Returns:
            Dict with cleanup results
        """
        start_time = datetime.now()
        errors: List[str] = []
        results: Dict[str, Any] = {
            "sessions": 0,
            "sql_entries": 0,
            "checkpoints": 0,
            "cache_entries": 0,
            "errors": errors,
        }

        logger.info("Starting cleanup cycle...")

        # 1. Clean up expired in-memory sessions
        try:
            results["sessions"] = await self._cleanup_sessions()
        except Exception as e:
            errors.append(f"sessions: {e}")
            logger.error(f"Session cleanup error: {e}")

        # 2. Clean up SQL integrity registry
        try:
            results["sql_entries"] = await self._cleanup_sql_registry()
        except Exception as e:
            errors.append(f"sql_registry: {e}")
            logger.error(f"SQL registry cleanup error: {e}")

        # 3. Clean up LangGraph checkpoints (PostgreSQL)
        try:
            results["checkpoints"] = await self._cleanup_checkpoints()
        except Exception as e:
            errors.append(f"checkpoints: {e}")
            logger.error(f"Checkpoint cleanup error: {e}")

        # 4. Clean up memory cache expired entries
        try:
            results["cache_entries"] = await self._cleanup_cache()
        except Exception as e:
            errors.append(f"cache: {e}")
            logger.error(f"Cache cleanup error: {e}")

        # Update stats
        duration = (datetime.now() - start_time).total_seconds()
        self.stats.last_run = datetime.now()
        self.stats.total_runs += 1
        self.stats.sessions_cleaned += cast(int, results["sessions"])
        self.stats.sql_entries_cleaned += cast(int, results["sql_entries"])
        self.stats.checkpoints_cleaned += cast(int, results["checkpoints"])
        self.stats.cache_entries_cleaned += cast(int, results["cache_entries"])

        logger.info(
            f"Cleanup complete in {duration:.2f}s: "
            f"sessions={results['sessions']}, "
            f"sql_entries={results['sql_entries']}, "
            f"checkpoints={results['checkpoints']}, "
            f"cache={results['cache_entries']}"
        )

        return results

    async def _cleanup_sessions(self) -> int:
        """Clean up expired in-memory sessions"""
        try:
            from app.services.session_store import session_store
        except ImportError:
            return 0

        # Only clean memory sessions - Redis handles its own TTL
        if not hasattr(session_store, "_sessions"):
            return 0

        now = datetime.now()
        expired_sessions = []

        for session_id, session in list(session_store._sessions.items()):
            # Check if session has expired
            created_at = session.get("created_at")
            if created_at:
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue

                age = now - created_at.replace(tzinfo=None)
                if age > self.session_max_age:
                    expired_sessions.append(session_id)

        # Delete expired sessions
        for session_id in expired_sessions:
            try:
                # Trigger cascade cleanup
                from app.services.security import (
                    csrf_protection,
                    rate_limiter,
                    sql_integrity,
                )

                sql_integrity.cleanup_session(session_id)
                csrf_protection.cleanup_session(session_id)
                rate_limiter.cleanup_session(session_id)

                # Remove from memory
                session_store._sessions.pop(session_id, None)
                logger.debug(f"Cleaned up expired session: {session_id[:8]}...")
            except Exception as e:
                logger.warning(f"Failed to cleanup session {session_id[:8]}: {e}")

        if expired_sessions:
            logger.info(
                f"Cleaned up {len(expired_sessions)} expired in-memory sessions"
            )

        return len(expired_sessions)

    async def _cleanup_sql_registry(self) -> int:
        """Clean up expired SQL integrity registry entries"""
        try:
            from app.services.security import sql_integrity
        except ImportError:
            return 0

        if not hasattr(sql_integrity, "_registry"):
            return 0

        now = datetime.now()
        max_age_seconds = self.sql_registry_max_age.total_seconds()
        expired_entries = []

        for sql_hash, entry in list(sql_integrity._registry.items()):
            created_at = entry.get("created_at", 0)
            if now.timestamp() - created_at > max_age_seconds:
                expired_entries.append(sql_hash)

        for sql_hash in expired_entries:
            sql_integrity._registry.pop(sql_hash, None)

        if expired_entries:
            logger.info(
                f"Cleaned up {len(expired_entries)} expired SQL registry entries"
            )

        return len(expired_entries)

    async def _cleanup_checkpoints(self) -> int:
        """Clean up old LangGraph checkpoints from PostgreSQL"""
        if not hasattr(settings, "DATABASE_URL") or not settings.DATABASE_URL:
            return 0

        try:
            import asyncpg
        except ImportError:
            return 0

        try:
            conn = await asyncpg.connect(settings.DATABASE_URL)

            # Check if checkpoint tables exist
            tables_exist = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'checkpoints'
                )
            """
            )

            if not tables_exist:
                await conn.close()
                return 0

            # Delete old checkpoints whose thread_id matches expired sessions.
            # The LangGraph checkpoints table has no created_at column; thread_id
            # is formatted as "session_id:run_id" (see generate_thread_id), so we
            # extract the session_id prefix and join through the sessions table.
            cutoff = datetime.now() - self.checkpoint_max_age

            # Check if sessions table exists for the join
            sessions_exist = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'sessions'
                )
            """
            )

            if sessions_exist:
                result = await conn.execute(
                    """
                    DELETE FROM checkpoints
                    WHERE split_part(thread_id, ':', 1) IN (
                        SELECT session_id FROM sessions
                        WHERE created_at < $1
                    )
                """,
                    cutoff,
                )
            else:
                # No sessions table to correlate — skip cleanup
                await conn.close()
                return 0

            # Parse result to get count
            count = 0
            if result:
                parts = result.split()
                if len(parts) >= 2:
                    try:
                        count = int(parts[1])
                    except ValueError:
                        pass

            # Also clean up checkpoint_writes if exists
            writes_exist = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'checkpoint_writes'
                )
            """
            )

            if writes_exist and sessions_exist:
                await conn.execute(
                    """
                    DELETE FROM checkpoint_writes
                    WHERE split_part(thread_id, ':', 1) IN (
                        SELECT session_id FROM sessions
                        WHERE created_at < $1
                    )
                """,
                    cutoff,
                )

            await conn.close()

            if count > 0:
                logger.info(f"Cleaned up {count} old LangGraph checkpoints")

            return count

        except Exception as e:
            logger.debug(f"Checkpoint cleanup skipped: {e}")
            return 0

    async def _cleanup_cache(self) -> int:
        """Clean up expired memory cache entries"""
        try:
            from app.services.cache_service import cache_service
        except ImportError:
            return 0

        # Only for memory backend
        if not hasattr(cache_service, "_backend"):
            return 0

        backend = cache_service._backend
        if backend is None or not hasattr(backend, "_cache"):
            return 0

        now = datetime.now()
        expired_keys = []

        for key, entry in list(backend._cache.items()):
            expires_at = entry.get("expires_at")
            if expires_at and now > expires_at:
                expired_keys.append(key)

        for key in expired_keys:
            backend._cache.pop(key, None)

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

        return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics"""
        return {
            "last_run": (
                self.stats.last_run.isoformat() if self.stats.last_run else None
            ),
            "total_runs": self.stats.total_runs,
            "sessions_cleaned": self.stats.sessions_cleaned,
            "sql_entries_cleaned": self.stats.sql_entries_cleaned,
            "checkpoints_cleaned": self.stats.checkpoints_cleaned,
            "cache_entries_cleaned": self.stats.cache_entries_cleaned,
            "errors": self.stats.errors,
            "last_error": self.stats.last_error,
            "running": self._running,
            "interval_seconds": self.cleanup_interval,
        }


# Singleton instance
cleanup_service = CleanupService(
    cleanup_interval_seconds=300,  # 5 minutes
    session_max_age_hours=settings.SESSION_EXPIRY_HOURS,
    sql_registry_max_age_hours=2,
    checkpoint_max_age_hours=48,
)
