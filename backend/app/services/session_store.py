"""
QueryfyAI - Session Store

Redis-backed session management with in-memory fallback
SECURITY: Uses JSON serialization instead of pickle to prevent RCE
SECURITY: Uses signed session tokens to prevent forgery
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.security import SessionTokenService

logger = logging.getLogger(__name__)


class SecureJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime and other types"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        return super().default(obj)


def secure_json_decoder(dct):
    """Custom JSON decoder for datetime"""
    if "__datetime__" in dct:
        return datetime.fromisoformat(dct["__datetime__"])
    return dct


class SessionStore:
    """Session management with Redis and in-memory fallback"""

    _instance = None
    _initialized: bool

    # Memory store limits to prevent memory leaks
    MAX_MEMORY_SESSIONS = 1000  # Max sessions to keep in memory
    MEMORY_CLEANUP_INTERVAL = 300  # 5 minutes between cleanups

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        import threading

        self.redis_client = None
        self.memory_store: Dict[str, Dict] = {}
        self._memory_lock = threading.Lock()  # Thread safety for memory_store
        self._last_cleanup = datetime.now()
        self._init_redis()
        self._initialized = True

    def _init_redis(self):
        """Initialize Redis connection"""
        try:
            import redis

            self.redis_client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=False,
                socket_connect_timeout=2,  # Fast timeout for startup
            )
            self.redis_client.ping()
            logger.info(
                "✓ Session store: Redis connected (sessions persist across restarts)"
            )
        except Exception as e:
            logger.warning(
                f"⚠ Session store: Redis not available ({e}) - using in-memory (sessions lost on restart)"
            )
            self.redis_client = None

    def create_session(self, llm_config: Dict, db_config: Dict) -> str:
        """Create a new session with configuration"""
        # SECURITY: Use signed session ID to prevent forgery
        session_id = SessionTokenService.create_signed_session_id()

        session_data = {
            "id": session_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "llm_config": llm_config,
            "db_config": db_config,
            "locked": False,
            "history": [],
            "feedback": [],
            "context_window": [],
            "token_info": None,
            # Conversation support fields
            "conversation_thread_id": None,  # Persistent thread for checkpointing
            "result_cache": {},  # query_id -> {columns, rows, sql, timestamp}
            "explored_tables": [],  # Tables agent has examined in this conversation
            "last_query_context": None,  # Most recent query for follow-up detection
        }

        self._save(session_id, session_data)
        logger.info(f"Session created: {session_id[:8]}...")
        self._emit_active_sessions_metric()
        return session_id

    def get(self, session_id: str, verify_signature: bool = True) -> Optional[Dict]:
        """Get session by ID"""
        # SECURITY: Verify session ID signature to prevent forgery
        if verify_signature:
            is_valid, msg = SessionTokenService.verify_session_id(session_id)
            if not is_valid:
                logger.warning(f"Invalid session ID signature: {msg}")
                return None

        # Try Redis first
        if self.redis_client:
            try:
                data = self.redis_client.get(f"session:{session_id}")
                if data:
                    # SECURITY: Use JSON instead of pickle to prevent RCE
                    return json.loads(
                        data.decode("utf-8"), object_hook=secure_json_decoder
                    )
            except Exception as e:
                logger.error(f"Redis get error: {e}")

        # Fallback to memory (thread-safe)
        with self._memory_lock:
            return self.memory_store.get(session_id)

    def update(self, session_id: str, updates: Dict):
        """Update session data"""
        session = self.get(session_id)
        if not session:
            raise ValueError("Session not found")

        session.update(updates)
        session["updated_at"] = datetime.now().isoformat()
        self._save(session_id, session)

    def add_history(
        self,
        session_id: str,
        entry: Dict,
        # Optional analyst mode fields
        answer: Optional[str] = None,
        key_findings: Optional[List[str]] = None,
        confidence: Optional[float] = None,
        chart_spec: Optional[Dict] = None,
        raw_result_summary: Optional[Dict] = None,
        tools_used: Optional[List[str]] = None,
        agent_steps: Optional[List[Dict]] = None,
        is_follow_up: bool = False,
        conversation_turn: Optional[int] = None,
    ) -> str:
        """
        Add to conversation history and maintain context_window.

        Args:
            session_id: Session identifier
            entry: Base history entry (query, sql, sql_hash, mode, success)
            answer: Optional analyst-generated answer
            key_findings: Optional list of key insights
            confidence: Optional confidence score (0-1)
            chart_spec: Optional chart specification
            raw_result_summary: Optional result summary for lightweight storage
            tools_used: Optional list of tools used (analyst mode)
            agent_steps: Optional agent execution steps
            is_follow_up: Whether this is a follow-up query
            conversation_turn: Conversation turn number

        Returns:
            entry_id: Unique identifier for the history entry
        """
        session = self.get(session_id)
        if not session:
            raise ValueError("Session not found")

        entry_id = str(uuid.uuid4())
        history_entry = {
            **entry,  # Base fields (query, sql, sql_hash, mode, success)
            "id": entry_id,
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
        }

        # Add analyst mode fields if provided
        if answer is not None:
            history_entry["answer"] = answer
        if key_findings is not None:
            history_entry["key_findings"] = key_findings
        if confidence is not None:
            history_entry["confidence"] = confidence
        if chart_spec is not None:
            history_entry["chart_spec"] = chart_spec
        if raw_result_summary is not None:
            history_entry["raw_result_summary"] = raw_result_summary
        if tools_used is not None:
            history_entry["tools_used"] = tools_used
        if agent_steps is not None:
            history_entry["agent_steps"] = agent_steps
        if is_follow_up:
            history_entry["is_follow_up"] = is_follow_up
        if conversation_turn is not None:
            history_entry["conversation_turn"] = conversation_turn

        # Lock session after first interaction
        if not session["locked"]:
            session["locked"] = True

        session["history"].append(history_entry)

        # CRITICAL: Maintain context window for conversation threading
        session["context_window"] = session["history"][-settings.MAX_CONTEXT_WINDOW :]

        # Trim history if too long
        if len(session["history"]) > settings.MAX_HISTORY_ITEMS:
            session["history"] = session["history"][-settings.MAX_HISTORY_ITEMS :]

        session["updated_at"] = datetime.now().isoformat()
        self._save(session_id, session)

        return entry_id

    def add_feedback(
        self, session_id: str, query_id: str, rating: int, comment: Optional[str] = None
    ):
        """Add feedback for a query"""
        session = self.get(session_id)
        if not session:
            raise ValueError("Session not found")

        session["feedback"].append(
            {
                "query_id": query_id,
                "rating": rating,
                "comment": comment,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Cap feedback to most recent 100 entries
        if len(session["feedback"]) > 100:
            session["feedback"] = session["feedback"][-100:]

        # Update history entry with feedback
        for entry in session["history"]:
            if entry.get("id") == query_id:
                entry["feedback_rating"] = rating
                break

        self._save(session_id, session)

    # =============================================
    # Conversation Support Methods
    # =============================================

    def cache_query_result(
        self,
        session_id: str,
        query_id: str,
        result: Dict[str, Any],
        max_cache_size: int = 10,
    ) -> None:
        """
        Cache query result for later reference in conversation.

        Stores lightweight version: columns, first 100 rows, row_count, sql, timestamp.
        Auto-prunes to keep only most recent max_cache_size entries.

        Args:
            session_id: Session identifier
            query_id: Unique query identifier
            result: Query execution result dict
            max_cache_size: Maximum number of cached queries (default 10)
        """
        session = self.get(session_id)
        if not session:
            logger.warning(f"Cannot cache result - session {session_id[:8]} not found")
            return

        cache = session.get("result_cache", {})

        # Store lightweight version (max 100 rows)
        cache[query_id] = {
            "columns": result.get("columns", []),
            "rows": result.get("rows", [])[:100],  # Max 100 rows
            "row_count": result.get("row_count", len(result.get("rows", []))),
            "sql": result.get("sql", ""),
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Prune old entries (keep most recent)
        if len(cache) > max_cache_size:
            sorted_items = sorted(
                cache.items(),
                key=lambda x: x[1].get("timestamp", ""),
                reverse=True,
            )
            cache = dict(sorted_items[:max_cache_size])

        self.update(session_id, {"result_cache": cache})
        logger.debug(
            f"Cached query result {query_id[:8]} for session {session_id[:8]}, "
            f"cache size: {len(cache)}"
        )

    def get_cached_result(
        self,
        session_id: str,
        query_id: str = "last",
    ) -> Optional[Dict]:
        """
        Retrieve cached query result.

        Args:
            session_id: Session identifier
            query_id: Specific query ID or "last" for most recent

        Returns:
            Cached result dict or None if not found
        """
        session = self.get(session_id)
        if not session:
            return None

        cache = session.get("result_cache", {})

        if not cache:
            return None

        if query_id == "last":
            # Return most recent by timestamp
            sorted_items = sorted(
                cache.items(),
                key=lambda x: x[1].get("timestamp", ""),
                reverse=True,
            )
            return sorted_items[0][1] if sorted_items else None

        return cache.get(query_id)

    def reset_conversation(self, session_id: str) -> None:
        """
        Reset conversation state while preserving history.

        Clears: conversation_thread_id, last_query_context, result_cache, explored_tables
        Keeps: history, schema, db_config, llm_config
        """
        session = self.get(session_id)
        if not session:
            logger.warning(
                f"Cannot reset conversation - session {session_id[:8]} not found"
            )
            return

        self.update(
            session_id,
            {
                "conversation_thread_id": None,
                "last_query_context": None,
                "result_cache": {},
                "explored_tables": [],
                "context_window": [],
            },
        )
        logger.info(f"Reset conversation state for session {session_id[:8]}")

    def get_conversation_context(
        self,
        session_id: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Get last N conversation turns from context_window.

        Returns structured conversation history for agent context building.
        Limited to last 'limit' turns (default 5) for token efficiency.

        Args:
            session_id: Session identifier
            limit: Maximum number of recent turns to return

        Returns:
            List of conversation turn dicts with question, query, db_type, success
        """
        session = self.get(session_id)
        if not session:
            return []

        context_window = session.get("context_window", [])
        recent_turns = context_window[-limit:] if context_window else []

        # Transform to conversation context format
        conversation_context = []
        for i, entry in enumerate(recent_turns):
            raw_summary = entry.get("raw_result_summary", {}) or {}
            conversation_context.append(
                {
                    "turn": i + 1,
                    "question": entry.get("query", ""),
                    "generated_query": entry.get("sql", ""),  # Works for SQL, MongoDB, etc.
                    "db_type": session.get("db_config", {}).get("db_type", "sql"),
                    "success": entry.get("success", True),
                    "timestamp": entry.get("timestamp", ""),
                    "answer": (entry.get("answer") or "")[:300],
                    "key_findings": (entry.get("key_findings") or [])[:3],
                    "row_count": raw_summary.get("row_count", 0),
                    "columns": (raw_summary.get("columns") or [])[:10],
                }
            )

        return conversation_context

    def toggle_pin(self, session_id: str, query_id: str, pinned: bool) -> bool:
        """Toggle pin status of a history entry"""
        session = self.get(session_id)
        if not session:
            raise ValueError("Session not found")

        found = False
        for entry in session["history"]:
            if entry.get("id") == query_id:
                entry["pinned"] = pinned
                found = True
                break

        if found:
            self._save(session_id, session)

        return found

    def get_pinned_queries(
        self,
        session_id: str,
        connection_id: Optional[str] = None,
        db_type: Optional[str] = None,
    ) -> List[Dict]:
        """Get all pinned queries for a session, optionally filtered by connection"""
        session = self.get(session_id)
        if not session:
            return []

        history = [
            entry for entry in session.get("history", []) if entry.get("pinned", False)
        ]

        # Filter by connection_id if provided
        if connection_id:
            history = [h for h in history if h.get("connection_id") == connection_id]

        # Filter by db_type if provided
        if db_type:
            history = [h for h in history if h.get("db_type") == db_type]

        return history

    def search_history(
        self,
        session_id: str,
        search_term: Optional[str] = None,
        pinned_only: bool = False,
        connection_id: Optional[str] = None,
        db_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        """Search through history entries with optional connection/db_type filtering"""
        session = self.get(session_id)
        if not session:
            return []

        history = session.get("history", [])

        # Filter by connection_id (connection hash) if provided
        if connection_id:
            history = [h for h in history if h.get("connection_id") == connection_id]

        # Filter by db_type if provided
        if db_type:
            history = [h for h in history if h.get("db_type") == db_type]

        # Filter by pinned if requested
        if pinned_only:
            history = [h for h in history if h.get("pinned", False)]

        # Filter by search term (searches query and sql)
        if search_term:
            search_lower = search_term.lower()
            history = [
                h
                for h in history
                if search_lower in h.get("query", "").lower()
                or search_lower in h.get("sql", "").lower()
            ]

        # Sort by timestamp (newest first)
        history = sorted(history, key=lambda x: x.get("timestamp", ""), reverse=True)

        # Apply pagination
        return history[offset : offset + limit]

    def get_history_entry(self, session_id: str, query_id: str) -> Optional[Dict]:
        """Get a specific history entry by ID"""
        session = self.get(session_id)
        if not session:
            return None

        for entry in session.get("history", []):
            if entry.get("id") == query_id:
                return entry

        return None

    def get_history_for_reexecution(
        self,
        session_id: str,
        query_id: str,
        current_connection_hash: str,
    ) -> tuple[Optional[Dict], Optional[str]]:
        """
        Get a history entry for re-execution with connection verification.

        SECURITY: This method verifies that the query was originally run on
        the same database connection before returning the SQL.

        Args:
            session_id: Current session ID
            query_id: ID of the query to re-execute
            current_connection_hash: Hash of current database connection

        Returns:
            Tuple of (history_entry, error_message)
            - If successful: (entry_dict, None)
            - If error: (None, error_message)
        """
        session = self.get(session_id)
        if not session:
            return None, "Session not found"

        # Find the history entry
        entry = None
        for h in session.get("history", []):
            if h.get("id") == query_id:
                entry = h
                break

        if not entry:
            return None, f"Query {query_id} not found in history"

        # SECURITY: Verify connection matches
        # This prevents re-executing queries on a different database
        stored_connection_id = entry.get("connection_id")
        if stored_connection_id:
            if stored_connection_id != current_connection_hash:
                query_prefix = query_id[:8] if query_id else "None"
                stored_prefix = stored_connection_id[:8] if stored_connection_id else "None"
                current_prefix = (
                    current_connection_hash[:8] if current_connection_hash else "None"
                )
                logger.warning(
                    f"Connection mismatch for re-execution: query={query_prefix}, "
                    f"stored_conn={stored_prefix}, current_conn={current_prefix}"
                )
                return None, "Query was run on a different database. Cannot re-execute."
        else:
            # Legacy entry without connection_id - allow but log warning
            logger.warning(
                f"Re-executing query {query_id[:8]} without connection verification "
                "(legacy entry missing connection_id)"
            )

        # Verify SQL exists
        if not entry.get("sql"):
            return None, "Query has no SQL stored"

        return entry, None

    def update_history_entry(
        self, session_id: str, query_id: str, updates: Dict
    ) -> bool:
        """Update a specific history entry"""
        session = self.get(session_id)
        if not session:
            raise ValueError("Session not found")

        found = False
        for entry in session["history"]:
            if entry.get("id") == query_id:
                # Only allow updating specific safe fields
                # NOTE: sql_hash, db_type, connection_id are needed for history re-execution
                safe_fields = [
                    "pinned",
                    "feedback_rating",
                    "explanation",
                    "success",
                    "error_message",
                    "sql_hash",
                    "db_type",
                    "connection_id",
                ]
                for key, value in updates.items():
                    if key in safe_fields:
                        entry[key] = value
                found = True
                break

        if found:
            self._save(session_id, session)

        return found

    def update_token_info(self, session_id: str, token_info: Dict):
        """Update token information for session"""
        session = self.get(session_id)
        if not session:
            raise ValueError("Session not found")

        session["token_info"] = token_info
        session["updated_at"] = datetime.now().isoformat()
        self._save(session_id, session)

    def delete(self, session_id: str):
        """Delete a session"""
        if self.redis_client:
            try:
                self.redis_client.delete(f"session:{session_id}")
            except Exception as e:
                logger.debug(f"Redis delete failed (will use memory): {e}")

        # Thread-safe memory deletion (use pop to avoid KeyError)
        with self._memory_lock:
            self.memory_store.pop(session_id, None)

        logger.info(f"Session deleted: {session_id[:8]}...")
        self._emit_active_sessions_metric()

    def get_storage_info(self) -> Dict[str, Any]:
        """Get information about current storage backend"""
        if self.redis_client:
            try:
                self.redis_client.ping()
                return {
                    "backend": "redis",
                    "persistent": True,
                    "url": (
                        settings.REDIS_URL.split("@")[-1]
                        if "@" in settings.REDIS_URL
                        else settings.REDIS_URL
                    ),
                    "session_count": len(self.redis_client.keys("session:*")),
                }
            except Exception:
                pass
        return {
            "backend": "memory",
            "persistent": False,
            "session_count": len(self.memory_store),
        }

    def count_active_sessions(self) -> int:
        """
        Return the current count of active sessions. Same source as
        ``get_storage_info()["session_count"]`` but only the integer.
        Falls back to 0 on backend errors so the Prometheus gauge
        emitter (``_emit_active_sessions_metric``) cannot block a
        session lifecycle event.
        """
        if self.redis_client:
            try:
                return len(self.redis_client.keys("session:*"))
            except Exception:
                pass
        with self._memory_lock:
            return len(self.memory_store)

    def _emit_active_sessions_metric(self) -> None:
        """
        Update the ``queryfyai_active_sessions`` Prometheus gauge to the
        current session count. Called after every lifecycle event
        (``create_session``, ``delete``) and once at app startup so the
        gauge reflects truth, not an in-process counter (which would be
        wrong under gunicorn multi-process scraping).

        Lazy import keeps the dependency direction clean — metrics
        already lazy-imports session_store; we mirror that on the
        other side to avoid the import cycle.
        """
        try:
            from app.api.metrics import update_active_sessions

            update_active_sessions(self.count_active_sessions())
        except Exception as e:  # pragma: no cover — metrics is best-effort
            logger.debug(f"active_sessions gauge update skipped: {e}")

    def list_sessions(self, limit: int = 50) -> List[Dict]:
        """List recent sessions"""
        sessions = []

        if self.redis_client:
            try:
                keys = self.redis_client.keys("session:*")
                for key in keys[:limit]:
                    data = self.redis_client.get(key)
                    if data:
                        # SECURITY: Use JSON instead of pickle
                        session = json.loads(
                            data.decode("utf-8"), object_hook=secure_json_decoder
                        )
                        sessions.append(
                            {
                                "id": session["id"],
                                "created_at": session["created_at"],
                                "locked": session["locked"],
                                "history_count": len(session.get("history", [])),
                            }
                        )
            except Exception as e:
                logger.error(f"Redis list error: {e}")
        else:
            # Thread-safe iteration over memory store
            with self._memory_lock:
                for session_id, session in list(self.memory_store.items())[:limit]:
                    sessions.append(
                        {
                            "id": session["id"],
                            "created_at": session["created_at"],
                            "locked": session["locked"],
                            "history_count": len(session.get("history", [])),
                        }
                    )

        return sorted(sessions, key=lambda x: x["created_at"], reverse=True)

    def _save(self, session_id: str, data: Dict):
        """Save session to store"""
        expiry = settings.SESSION_EXPIRY_HOURS * 3600

        redis_success = False
        if self.redis_client:
            try:
                # SECURITY: Use JSON instead of pickle to prevent RCE
                self.redis_client.setex(
                    f"session:{session_id}",
                    expiry,
                    json.dumps(data, cls=SecureJSONEncoder),
                )
                redis_success = True
            except Exception as e:
                logger.error(f"Redis save error: {e}")

        # Keep in memory ONLY as fallback when Redis is not available
        # Thread-safe memory operations
        with self._memory_lock:
            if not redis_success:
                self.memory_store[session_id] = data
            elif session_id in self.memory_store:
                # Redis succeeded - remove from memory to prevent memory leak
                del self.memory_store[session_id]

        # Trigger cleanup if needed (outside lock to avoid deadlock)
        if not redis_success:
            self._maybe_cleanup_memory()

    def _maybe_cleanup_memory(self):
        """Cleanup memory store if it's getting too large or enough time has passed.
        Thread-safe via _memory_lock.
        """
        now = datetime.now()

        # Quick check without lock (may have race but cleanup is not critical)
        if (now - self._last_cleanup).total_seconds() < self.MEMORY_CLEANUP_INTERVAL:
            with self._memory_lock:
                if len(self.memory_store) <= self.MAX_MEMORY_SESSIONS:
                    return

        self._last_cleanup = now

        # If Redis is available, we can be aggressive about memory cleanup
        if self.redis_client:
            try:
                self.redis_client.ping()
                with self._memory_lock:
                    # Remove oldest sessions from memory (keep only recent ones)
                    if len(self.memory_store) > self.MAX_MEMORY_SESSIONS // 2:
                        # Sort by updated_at and keep only the most recent
                        # Use epoch as default so missing timestamps sort as oldest
                        sorted_sessions = sorted(
                            self.memory_store.items(),
                            key=lambda x: x[1].get("updated_at", "1970-01-01T00:00:00"),
                            reverse=True,
                        )
                        # Keep only the most recent half
                        keep_count = self.MAX_MEMORY_SESSIONS // 2
                        self.memory_store = dict(sorted_sessions[:keep_count])
                        removed = len(sorted_sessions) - keep_count
                        if removed > 0:
                            logger.info(
                                f"Memory cleanup: removed {removed} old sessions (Redis is primary)"
                            )
                return
            except Exception:
                pass  # Redis unavailable, be more conservative

        # Redis unavailable - clean up expired sessions only
        expiry_seconds = settings.SESSION_EXPIRY_HOURS * 3600
        expired_ids = []

        with self._memory_lock:
            # Build list of expired sessions
            for session_id, data in list(self.memory_store.items()):
                updated_at = data.get("updated_at")
                if updated_at:
                    try:
                        if isinstance(updated_at, str):
                            updated = datetime.fromisoformat(updated_at)
                        else:
                            updated = updated_at
                        if (now - updated).total_seconds() > expiry_seconds:
                            expired_ids.append(session_id)
                    except (ValueError, TypeError):
                        pass

            # Remove expired sessions
            for session_id in expired_ids:
                self.memory_store.pop(session_id, None)

            if expired_ids:
                logger.info(
                    f"Memory cleanup: removed {len(expired_ids)} expired sessions"
                )

            # If still over limit, remove oldest
            if len(self.memory_store) > self.MAX_MEMORY_SESSIONS:
                sorted_sessions = sorted(
                    self.memory_store.items(),
                    key=lambda x: x[1].get("updated_at", "1970-01-01T00:00:00"),
                    reverse=True,
                )
                self.memory_store = dict(sorted_sessions[: self.MAX_MEMORY_SESSIONS])
                logger.warning(
                    f"Memory store at limit ({self.MAX_MEMORY_SESSIONS}), removed oldest sessions"
                )


# Global instance
session_store = SessionStore()
