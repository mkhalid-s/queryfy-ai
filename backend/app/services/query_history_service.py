"""
QueryfyAI - Query History Persistence Service

Long-term storage for query history in PostgreSQL.
Enables cross-session re-execution of queries.

Architecture:
- Hot storage: Redis/memory (session_store) - fast, 24h TTL
- Cold storage: PostgreSQL (this service) - persistent, 30+ days

Security:
- connection_hash verification prevents cross-database execution
- db_type validation prevents SQL dialect mismatches
- SQL stored server-side, never trusted from client
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, delete, func, or_, select, update

from app.core.config import settings
from app.core.database import get_db_session, is_database_configured
from app.models.db_models import QueryHistory

logger = logging.getLogger(__name__)


class QueryHistoryService:
    """
    Service for persistent query history storage.

    Provides long-term storage complementing the session-based Redis store.
    """

    # Default retention period (days)
    DEFAULT_RETENTION_DAYS = 30

    @staticmethod
    def is_available() -> bool:
        """Check if persistent storage is available."""
        return is_database_configured()

    @staticmethod
    async def save_query(
        query_id: str,
        connection_hash: str,
        db_type: str,
        natural_query: str,
        sql: str,
        sanitized_query: Optional[str] = None,
        sql_hash: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        explanation: Optional[str] = None,
        # Analyst mode fields
        mode: str = "standard",
        answer: Optional[str] = None,
        key_findings: Optional[List[str]] = None,
        confidence: Optional[float] = None,
        chart_spec: Optional[Dict] = None,
        raw_result_summary: Optional[Dict] = None,
        tools_used: Optional[List[str]] = None,
        agent_steps: Optional[List[Dict]] = None,
        # Conversation threading
        is_follow_up: bool = False,
        conversation_turn: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Save a query to persistent storage with full conversation data.

        Args:
            query_id: Unique query identifier (from session history)
            connection_hash: Database connection hash
            db_type: Database type (postgresql, mysql, etc.)
            natural_query: User's natural language question
            sql: Generated SQL
            sanitized_query: Cleaned query text
            sql_hash: HMAC hash for integrity (session-bound)
            success: Whether execution succeeded
            error_message: Error if execution failed
            explanation: AI explanation of the SQL
            mode: Query mode ('standard' or 'analyst')
            answer: Analyst mode synthesized answer
            key_findings: Array of insights from analyst mode
            confidence: Confidence score (0-1)
            chart_spec: Chart configuration with data
            raw_result_summary: Lightweight result summary {columns, row_count, sample_rows}
            tools_used: Array of tool names used by agent
            agent_steps: Array of agent step objects
            is_follow_up: Whether this is a follow-up query
            conversation_turn: Turn number in conversation
            session_id: Session ID for conversation grouping

        Returns:
            Query ID if saved, None if storage unavailable
        """
        if not is_database_configured():
            logger.debug("Database not configured, skipping persistent storage")
            return None

        try:
            async with get_db_session() as session:
                # Check if query already exists (upsert logic)
                existing = await session.execute(
                    select(QueryHistory).where(QueryHistory.id == query_id)
                )
                record = existing.scalar_one_or_none()

                if record:
                    # Update existing record with all fields
                    record.sql = sql
                    record.sql_hash = sql_hash
                    record.success = success
                    record.error_message = error_message
                    record.explanation = explanation
                    # Analyst mode fields
                    record.mode = mode
                    record.answer = answer
                    record.key_findings = key_findings
                    record.confidence = confidence  # type: ignore[assignment]
                    record.chart_spec = chart_spec
                    record.raw_result_summary = raw_result_summary
                    record.tools_used = tools_used
                    record.agent_steps = agent_steps
                    # Conversation threading
                    record.is_follow_up = is_follow_up
                    record.conversation_turn = conversation_turn
                    record.session_id = session_id
                    record.updated_at = datetime.utcnow()
                    logger.debug(f"Updated existing query history: {query_id[:8]}")
                else:
                    # Create new record with all fields
                    record = QueryHistory(
                        id=query_id,
                        connection_hash=connection_hash,
                        db_type=db_type,
                        natural_query=natural_query,
                        sanitized_query=sanitized_query,
                        sql=sql,
                        sql_hash=sql_hash,
                        success=success,
                        error_message=error_message,
                        explanation=explanation,
                        # Analyst mode fields
                        mode=mode,
                        answer=answer,
                        key_findings=key_findings,
                        confidence=confidence,  # type: ignore[arg-type]
                        chart_spec=chart_spec,
                        raw_result_summary=raw_result_summary,
                        tools_used=tools_used,
                        agent_steps=agent_steps,
                        # Conversation threading
                        is_follow_up=is_follow_up,
                        conversation_turn=conversation_turn,
                        session_id=session_id,
                    )
                    session.add(record)
                    logger.debug(f"Saved new query history: {query_id[:8]}")

                return query_id

        except Exception as e:
            logger.error(f"Failed to save query history: {e}")
            return None

    @staticmethod
    async def get_query_for_reexecution(
        query_id: str,
        current_connection_hash: str,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Get a query from persistent storage for re-execution.

        SECURITY: Verifies connection_hash matches before returning SQL.

        Args:
            query_id: Query ID to retrieve
            current_connection_hash: Current database connection hash

        Returns:
            Tuple of (history_entry_dict, error_message)
            - Success: (entry_dict, None)
            - Error: (None, error_message)
        """
        if not is_database_configured():
            return None, "Persistent storage not configured"

        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(QueryHistory).where(QueryHistory.id == query_id)
                )
                record = result.scalar_one_or_none()

                if not record:
                    return None, f"Query {query_id} not found in history"

                # SECURITY: Verify connection matches
                if record.connection_hash != current_connection_hash:
                    stored_hash = record.connection_hash or ""
                    logger.warning(
                        f"Connection mismatch for re-execution: "
                        f"query={query_id[:8]}, "
                        f"stored={stored_hash[:8]}, "
                        f"current={current_connection_hash[:8]}"
                    )
                    return None, "Query was run on a different database. Cannot re-execute."

                # Update execution tracking
                record.execution_count = (record.execution_count or 0) + 1
                record.last_executed_at = datetime.utcnow()

                return record.to_history_entry(), None

        except Exception as e:
            logger.error(f"Failed to get query for re-execution: {e}")
            return None, f"Database error: {str(e)}"

    @staticmethod
    async def search_history(
        connection_hash: str,
        db_type: Optional[str] = None,
        search_term: Optional[str] = None,
        pinned_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        """
        Search persistent query history.

        Args:
            connection_hash: Filter by database connection
            db_type: Optional filter by database type
            search_term: Optional text search in query/SQL
            pinned_only: Only return pinned queries
            limit: Max results to return
            offset: Pagination offset

        Returns:
            List of history entry dicts
        """
        if not is_database_configured():
            return []

        try:
            async with get_db_session() as session:
                query = select(QueryHistory).where(
                    QueryHistory.connection_hash == connection_hash
                )

                if db_type:
                    query = query.where(QueryHistory.db_type == db_type)

                if pinned_only:
                    query = query.where(QueryHistory.pinned == True)  # noqa: E712

                if search_term:
                    search_pattern = f"%{search_term}%"
                    query = query.where(
                        or_(
                            QueryHistory.natural_query.ilike(search_pattern),
                            QueryHistory.sql.ilike(search_pattern),
                        )
                    )

                query = query.order_by(QueryHistory.created_at.desc())
                query = query.limit(limit).offset(offset)

                result = await session.execute(query)
                records = result.scalars().all()

                return [r.to_history_entry() for r in records]

        except Exception as e:
            logger.error(f"Failed to search history: {e}")
            return []

    @staticmethod
    async def update_query(
        query_id: str,
        updates: Dict,
    ) -> bool:
        """
        Update a query record.

        Args:
            query_id: Query ID to update
            updates: Dict of fields to update (pinned, feedback_rating, explanation, etc.)

        Returns:
            True if updated, False otherwise
        """
        if not is_database_configured():
            return False

        # Whitelist of allowed update fields
        allowed_fields = {
            "pinned", "feedback_rating", "explanation",
            "success", "error_message", "sql_hash"
        }

        filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered_updates:
            return False

        try:
            async with get_db_session() as session:
                filtered_updates["updated_at"] = datetime.utcnow()

                result = await session.execute(
                    update(QueryHistory)
                    .where(QueryHistory.id == query_id)
                    .values(**filtered_updates)
                )

                return result.rowcount > 0  # type: ignore[attr-defined]

        except Exception as e:
            logger.error(f"Failed to update query: {e}")
            return False

    @staticmethod
    async def toggle_pin(query_id: str, pinned: bool) -> bool:
        """Toggle pinned status for a query."""
        return await QueryHistoryService.update_query(query_id, {"pinned": pinned})

    @staticmethod
    async def cleanup_old_queries(
        retention_days: Optional[int] = None,
        keep_pinned: bool = True,
    ) -> int:
        """
        Clean up old query history records.

        Args:
            retention_days: Days to keep (default from settings)
            keep_pinned: Whether to keep pinned queries regardless of age

        Returns:
            Number of records deleted
        """
        if not is_database_configured():
            return 0

        days = retention_days or getattr(
            settings, "QUERY_HISTORY_RETENTION_DAYS",
            QueryHistoryService.DEFAULT_RETENTION_DAYS
        )
        # Ensure days is an integer for timedelta
        days_int = int(days) if days is not None else QueryHistoryService.DEFAULT_RETENTION_DAYS
        cutoff = datetime.utcnow() - timedelta(days=days_int)

        try:
            async with get_db_session() as session:
                conditions = [QueryHistory.created_at < cutoff]

                if keep_pinned:
                    conditions.append(QueryHistory.pinned == False)  # noqa: E712

                result = await session.execute(
                    delete(QueryHistory).where(and_(*conditions))
                )

                deleted = result.rowcount  # type: ignore[attr-defined]
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old query history records")

                return deleted

        except Exception as e:
            logger.error(f"Failed to cleanup old queries: {e}")
            return 0

    @staticmethod
    async def get_stats(connection_hash: str) -> Dict:
        """
        Get statistics for a connection's query history.

        Args:
            connection_hash: Database connection hash

        Returns:
            Dict with stats (total, pinned, success_rate, etc.)
        """
        if not is_database_configured():
            return {"available": False}

        try:
            async with get_db_session() as session:
                # Total count
                total_result = await session.execute(
                    select(func.count(QueryHistory.id)).where(
                        QueryHistory.connection_hash == connection_hash
                    )
                )
                total = total_result.scalar() or 0

                # Pinned count
                pinned_result = await session.execute(
                    select(func.count(QueryHistory.id)).where(
                        and_(
                            QueryHistory.connection_hash == connection_hash,
                            QueryHistory.pinned == True,  # noqa: E712
                        )
                    )
                )
                pinned = pinned_result.scalar() or 0

                # Success rate
                success_result = await session.execute(
                    select(func.count(QueryHistory.id)).where(
                        and_(
                            QueryHistory.connection_hash == connection_hash,
                            QueryHistory.success == True,  # noqa: E712
                        )
                    )
                )
                successful = success_result.scalar() or 0

                return {
                    "available": True,
                    "total": total,
                    "pinned": pinned,
                    "successful": successful,
                    "success_rate": (successful / total * 100) if total > 0 else 0,
                }

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"available": False, "error": str(e)}

    @staticmethod
    async def get_history_by_session_id(
        session_id: str,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Load history from PostgreSQL by session_id.

        Used when session memory has expired but PostgreSQL still has the data.
        Enables cross-session conversation restore for up to 30 days.

        Args:
            session_id: Session ID to filter by
            limit: Maximum number of entries to return

        Returns:
            List of history entries as dictionaries
        """
        if not is_database_configured():
            logger.debug("Database not configured, cannot load history by session")
            return []

        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(QueryHistory)
                    .where(QueryHistory.session_id == session_id)
                    .order_by(QueryHistory.created_at.asc())  # Chronological order
                    .limit(limit)
                )
                records = result.scalars().all()
                return [r.to_history_entry() for r in records]

        except Exception as e:
            logger.error(f"Failed to get history by session_id: {e}")
            return []


# Singleton instance
query_history_service = QueryHistoryService()
