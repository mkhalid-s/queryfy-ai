# ============================================
# FILE: app/api/consolidated.py
#
# Consolidated API endpoints to reduce API calls
# See: BACKEND-API-CONSOLIDATION.md
# ============================================
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import settings
from app.core.csrf_utils import verify_csrf_token
from app.core.dependencies import check_rate_limit, get_session, validate_request
from app.core.logging_config import get_logger
from app.models.consolidated_schemas import (
    ActionResult,
    BatchActionRequest,
    BatchActionResponse,
    InitRequest,
    InitResponse,
    QueryGenerateExtendedRequest,
    QueryGenerateExtendedResponse,
    RestoreSessionResponse,
    SessionSummary,
)
from app.models.schemas import (
    DatabaseConfig,
    DefaultDBConfig,
    DefaultLLMConfig,
    ExecuteQueryResponse,
    HistoryEntry,
    HistoryResponse,
    LLMConfig,
    PinnedQueryRequest,
    ReexecuteFromHistoryRequest,
    mask_connection_url,
)
from app.services.database_service import DatabaseService
from app.services.llm_service import LLMService
from app.services.query_history_service import query_history_service
from app.services.security import (
    AuditLogger,
    ErrorSanitizer,
    ResultSizeLimiter,
    SecurityService,
    csrf_protection,
    rate_limiter,
    sql_integrity,
)
from app.services.session_store import session_store
from app.services.sql_agent import run_sql_agent
from app.services.sql_generation import SQLGenerationService
from app.services.vector_db import vector_db

router = APIRouter()
logger = get_logger(__name__)


@router.post("/init", response_model=InitResponse)
async def initialize_app(request: InitRequest):
    """
    Initialize app with all necessary data in one call.

    Combines:
    - GET /config/defaults
    - GET /sessions/{id} (restore)
    - GET /history/{id}

    Returns defaults + optionally restored session + history + CSRF token
    """
    # Rate limiting - use session_id if provided, otherwise use a generic key
    rate_limit_key = request.previous_session_id or "init_anonymous"
    allowed, rate_msg = rate_limiter.check_rate_limit(rate_limit_key, "generate")
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_msg)

    # Get default configuration
    llm_defaults = settings.get_default_llm_config()
    db_defaults = settings.get_default_db_config()

    llm_config = DefaultLLMConfig(
        provider=llm_defaults["provider"],
        base_url=llm_defaults["base_url"],
        token_url=llm_defaults["token_url"],
        client_id=llm_defaults["client_id"],
        client_secret_set=bool(settings.DEFAULT_LLM_CLIENT_SECRET),
        auth_scope=llm_defaults["auth_scope"],
        auth_type=llm_defaults["auth_type"],
        tenant=llm_defaults["tenant"],
        star=llm_defaults["star"],
        chat_endpoint=llm_defaults["chat_endpoint"],
        api_key_set=bool(settings.DEFAULT_LLM_API_KEY),
        model=llm_defaults["model"],
    )

    raw_connection_url = db_defaults["connection_url"]
    db_config = DefaultDBConfig(
        db_type=db_defaults["db_type"],
        connection_url=mask_connection_url(raw_connection_url),
        connection_url_set=bool(raw_connection_url),
        name=db_defaults["name"],
    )

    response = InitResponse(
        has_defaults=settings.has_default_llm_config(),
        llm_config=llm_config,
        db_config=db_config,
        session=None,
        history=[],
        csrf_token=None,
        token_info=None,
    )

    # Try to restore session if previous_session_id provided
    if request.previous_session_id:
        session = session_store.get(request.previous_session_id)
        if session:
            # Compute connection hash for history filtering
            connection_url = session["db_config"].get("connection_url", "")
            connection_hash = (
                vector_db._hash_connection(connection_url) if connection_url else None
            )

            # Session found - restore it
            response.session = SessionSummary(
                id=session["id"],
                locked=session.get("locked", False),
                db_type=session["db_config"].get("db_type", ""),
                llm_provider=session["llm_config"].get("provider", ""),
                created_at=session.get("created_at", ""),
                updated_at=session.get("updated_at", ""),
                connection_hash=connection_hash,
            )

            # Include history with all fields for proper frontend grouping
            history_entries = session.get("history", [])
            response.history = [
                HistoryEntry(
                    id=h.get("id", ""),
                    query=h.get("query", ""),
                    sql=h.get("sql", ""),
                    timestamp=h.get("timestamp", ""),
                    feedback_rating=h.get("feedback_rating"),
                    sql_hash=h.get("sql_hash"),
                    explanation=h.get("explanation"),
                    pinned=h.get("pinned", False),
                    connection_id=h.get("connection_id"),
                    db_type=h.get("db_type"),
                    success=h.get("success"),
                    error_message=h.get("error_message"),
                    session_id=h.get("session_id") or request.previous_session_id,
                    # Analyst mode fields for full conversation restore
                    mode=h.get("mode"),
                    answer=h.get("answer"),
                    key_findings=h.get("key_findings"),
                    confidence=h.get("confidence"),
                    chart_spec=h.get("chart_spec"),
                    raw_result_summary=h.get("raw_result_summary"),
                    tools_used=h.get("tools_used"),
                    agent_steps=h.get("agent_steps"),
                    is_follow_up=h.get("is_follow_up"),
                    conversation_turn=h.get("conversation_turn"),
                )
                for h in history_entries
            ]

            # Generate new CSRF token
            response.csrf_token = csrf_protection.generate_token(
                request.previous_session_id
            )

            # Include token info if available
            response.token_info = session.get("token_info")

            logger.info(
                "Session restored via /init", session_id=request.previous_session_id[:8]
            )

    return response


@router.post("/query/generate-extended", response_model=QueryGenerateExtendedResponse)
async def generate_sql_extended(
    request: QueryGenerateExtendedRequest,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
    use_agent: bool = Query(
        False,
        description="Use LangGraph agent for self-healing SQL generation with retries",
    ),
):
    """
    Enhanced SQL generation endpoint.

    Combines:
    - POST /query/generate
    - GET /history/{id} (included in response)
    - POST /query/execute (optional, if auto_execute=True)

    Returns: SQL + updated history + optional execution results
    """
    # Consolidated validation: session lookup, CSRF, rate limit
    session = validate_request(
        request.session_id, csrf_token, rate_limit_action="generate"
    )

    # Prepare generation context (sanitizes input, extracts configs, gets schema)
    ctx, error_result = await SQLGenerationService.prepare_context(
        request.session_id, session, request.natural_language
    )

    if error_result:
        return QueryGenerateExtendedResponse(
            error=error_result.error,
            warnings=error_result.warnings,
            message=error_result.message,
        )

    # At this point, ctx is guaranteed to be non-None (prepare_context ensures one or the other)
    assert ctx is not None, "Context must be non-None when error_result is None"

    # Helper to build history entries for response
    def get_recent_history() -> List[HistoryEntry]:
        updated_session = session_store.get(request.session_id)
        if not updated_session:
            return []
        history_entries = updated_session.get("history", [])[-10:]
        return [
            HistoryEntry(
                id=h.get("id", ""),
                query=h.get("query", ""),
                sql=h.get("sql", ""),
                timestamp=h.get("timestamp", ""),
                feedback_rating=h.get("feedback_rating"),
                sql_hash=h.get("sql_hash"),
                explanation=h.get("explanation"),
                pinned=h.get("pinned", False),
                connection_id=h.get("connection_id"),
                db_type=h.get("db_type"),
                success=h.get("success"),
                error_message=h.get("error_message"),
                session_id=h.get("session_id") or request.session_id,
                # Analyst mode fields
                mode=h.get("mode"),
                answer=h.get("answer"),
                key_findings=h.get("key_findings"),
                confidence=h.get("confidence"),
                chart_spec=h.get("chart_spec"),
                raw_result_summary=h.get("raw_result_summary"),
                tools_used=h.get("tools_used"),
                agent_steps=h.get("agent_steps"),
                is_follow_up=h.get("is_follow_up"),
                conversation_turn=h.get("conversation_turn"),
            )
            for h in history_entries
        ]

    # ========================================
    # AGENT MODE: Use LangGraph SQLAgent
    # ========================================
    if use_agent:
        try:
            logger.info(
                "Using SQLAgent (extended)", query_preview=ctx.sanitized_query[:50]
            )

            agent_result = await run_sql_agent(
                question=ctx.sanitized_query,
                llm_config=ctx.llm_config,
                db_config=ctx.db_config,
                schema=ctx.relevant_schema,
                session_id=request.session_id,
            )

            if agent_result["success"]:
                # Register agent result using helper
                result = await SQLGenerationService.register_agent_result(
                    ctx,
                    agent_result["sql"],
                    agent_attempts=agent_result.get("attempts", 1),
                    agent_explanation=agent_result.get("explanation"),
                )

                logger.info(
                    "SQLAgent (extended) success",
                    attempts=agent_result.get("attempts", 1),
                    session_id=request.session_id[:8],
                )

                # Get usage data from agent result
                usage_data = agent_result.get("usage")

                # In success case, SQL and query_id must be present
                assert result.sql is not None, "SQL must be present in successful generation"
                assert result.query_id is not None, "Query ID must be present in successful generation"

                response = QueryGenerateExtendedResponse(
                    sql=result.sql,
                    query_id=result.query_id,
                    sql_hash=result.sql_hash,
                    message=f"Generated with {agent_result.get('attempts', 1)} attempt(s)",
                    history=get_recent_history(),
                    usage=usage_data,
                )

                # Auto-execute if requested (agent already executed, use its result)
                if request.auto_execute and agent_result.get("result"):
                    response.executed = True
                    # Add db_type to results for frontend view detection
                    agent_exec_result = {
                        **agent_result["result"],
                        "db_type": ctx.db_config.db_type,
                    }
                    response.execution_result = ExecuteQueryResponse(
                        **agent_exec_result
                    )
                    sql_integrity.mark_executed(request.session_id, result.query_id)
                    AuditLogger.log_sql_execution(
                        request.session_id,
                        result.query_id,
                        result.sql,
                        success=True,
                        row_count=agent_result["result"].get("row_count", 0),
                    )

                return response
            else:
                return QueryGenerateExtendedResponse(
                    error="Unable to generate valid SQL",
                    message=f"Agent failed after {agent_result.get('attempts', 1)} attempts: {agent_result.get('error', 'Unknown error')}",
                )

        except Exception as e:
            logger.error(
                "SQLAgent (extended) error", error=ErrorSanitizer.safe_log_error(e)
            )
            raise HTTPException(
                status_code=500, detail=ErrorSanitizer.sanitize_error(e)
            )

    # ========================================
    # STANDARD MODE: Use SQL Generation Helper
    # ========================================
    result = await SQLGenerationService.generate_sql(ctx)

    if not result.success:
        return QueryGenerateExtendedResponse(error=result.error, message=result.message)

    # In success case, SQL and query_id must be present
    assert result.sql is not None, "SQL must be present in successful generation"
    assert result.query_id is not None, "Query ID must be present in successful generation"

    # Build extended response with history and usage
    response = QueryGenerateExtendedResponse(
        sql=result.sql,
        query_id=result.query_id,
        sql_hash=result.sql_hash,
        history=get_recent_history(),
        usage=result.usage,
    )

    # Auto-execute if requested
    if request.auto_execute:
        try:
            exec_results = await DatabaseService.execute_query(
                ctx.db_config, result.sql, request.execute_limit
            )
            # Add db_type to results for frontend view detection
            exec_results["db_type"] = ctx.db_config.db_type
            response.executed = True
            response.execution_result = ExecuteQueryResponse(**exec_results)

            # Mark as executed
            sql_integrity.mark_executed(request.session_id, result.query_id)

            # Audit log
            AuditLogger.log_sql_execution(
                request.session_id,
                result.query_id,
                result.sql,
                success=True,
                row_count=exec_results.get("row_count", 0),
            )

        except Exception as e:
            response.executed = False
            response.execution_error = ErrorSanitizer.sanitize_error(e)
            logger.warning(
                "Auto-execute failed", error=ErrorSanitizer.safe_log_error(e)
            )

    return response


@router.post("/query/actions", response_model=BatchActionResponse)
async def batch_query_actions(
    request: BatchActionRequest, csrf_token: Optional[str] = Depends(verify_csrf_token)
):
    """
    Execute multiple query actions in one request.

    Combines:
    - POST /query/explain
    - POST /feedback

    Supported actions:
    - {"type": "explain"}
    - {"type": "feedback", "params": {"rating": 5, "comment": "..."}}
    """
    # Consolidated validation: session lookup + CSRF (rate limit per action)
    session = validate_request(request.session_id, csrf_token, require_csrf=True)

    llm_config = LLMConfig(**session["llm_config"])
    db_config = DatabaseConfig(**session["db_config"])

    results: List[ActionResult] = []

    for action in request.actions:
        action_result = ActionResult(type=action.type, success=False)

        try:
            if action.type == "explain":
                # Rate limit check (using try/except to capture rate limit errors)
                try:
                    check_rate_limit(request.session_id, "generate")
                except HTTPException as rate_err:
                    action_result.error = rate_err.detail
                else:
                    # SECURITY: Verify SQL was generated in this session (log warning if not)
                    # query_id is optional for explain action
                    if request.query_id:
                        is_verified, _ = sql_integrity.verify_sql(
                            request.session_id,
                            request.query_id,
                            request.sql_query,
                            request.sql_hash,
                        )
                        if not is_verified:
                            logger.warning(
                                "Explain requested for unregistered SQL",
                                session_id=request.session_id[:8],
                            )
                    else:
                        logger.debug("Explain without query_id - skipping verification")

                    schema = vector_db.get_full_schema_text(db_config.connection_url)
                    # Returns (explanation, usage) tuple
                    explanation, usage = await LLMService.explain_sql(
                        llm_config, request.sql_query, schema, db_config.db_type
                    )
                    action_result.success = True
                    usage_dict = (
                        usage.to_dict() if usage and hasattr(usage, "to_dict") else None
                    )
                    action_result.data = {
                        "explanation": explanation,
                        "usage": usage_dict,
                    }

            elif action.type == "feedback":
                params = action.params or {}
                rating = params.get("rating", 5)
                comment = params.get("comment")

                if not request.query_id:
                    action_result.error = "query_id required for feedback"
                else:
                    session_store.add_feedback(
                        request.session_id, request.query_id, rating, comment
                    )
                    action_result.success = True
                    action_result.data = {"rating": rating}

            else:
                action_result.error = f"Unknown action type: {action.type}"

        except Exception as e:
            action_result.error = ErrorSanitizer.sanitize_error(e)
            logger.error(
                "Action failed",
                action_type=action.type,
                error=ErrorSanitizer.safe_log_error(e),
            )

        results.append(action_result)

    return BatchActionResponse(results=results)


@router.post("/sessions/{session_id}/restore", response_model=RestoreSessionResponse)
async def restore_session(session_id: str):
    """
    Restore session with all necessary data in one call.

    Alternative to using /init with previous_session_id.
    Returns session info + history + CSRF token + token info
    """
    # Consolidated validation: rate limit + session lookup (no CSRF needed for restore)
    check_rate_limit(session_id, "generate")
    session = get_session(session_id)

    # Generate new CSRF token
    csrf_token = csrf_protection.generate_token(session_id)

    # Get history
    history_entries = session.get("history", [])

    # Restore SQL registry from history (for SQL integrity verification)
    sql_integrity.restore_from_history(session_id, history_entries)

    # Compute connection hash for history filtering
    connection_url = session["db_config"].get("connection_url", "")
    connection_hash = (
        vector_db._hash_connection(connection_url) if connection_url else None
    )

    logger.info("Session restored", session_id=session_id[:8])

    return RestoreSessionResponse(
        session=SessionSummary(
            id=session["id"],
            locked=session.get("locked", False),
            db_type=session["db_config"].get("db_type", ""),
            llm_provider=session["llm_config"].get("provider", ""),
            created_at=session.get("created_at", ""),
            updated_at=session.get("updated_at", ""),
            connection_hash=connection_hash,
        ),
        history=[
            HistoryEntry(
                id=h.get("id", ""),
                query=h.get("query", ""),
                sql=h.get("sql", ""),
                timestamp=h.get("timestamp", ""),
                feedback_rating=h.get("feedback_rating"),
                sql_hash=h.get("sql_hash"),
                explanation=h.get("explanation"),
                pinned=h.get("pinned", False),
                connection_id=h.get("connection_id"),
                db_type=h.get("db_type"),
                success=h.get("success"),
                error_message=h.get("error_message"),
                session_id=h.get("session_id") or session_id,
                # Analyst mode fields for full conversation restore
                mode=h.get("mode"),
                answer=h.get("answer"),
                key_findings=h.get("key_findings"),
                confidence=h.get("confidence"),
                chart_spec=h.get("chart_spec"),
                raw_result_summary=h.get("raw_result_summary"),
                tools_used=h.get("tools_used"),
                agent_steps=h.get("agent_steps"),
                is_follow_up=h.get("is_follow_up"),
                conversation_turn=h.get("conversation_turn"),
            )
            for h in history_entries
        ],
        csrf_token=csrf_token,
        token_info=session.get("token_info"),
    )


# ============== History Management Endpoints ==============


@router.get("/history/search", response_model=HistoryResponse)
async def search_history(
    session_id: str = Query(..., description="Session ID"),
    search_term: Optional[str] = Query(None, description="Search term"),
    pinned_only: bool = Query(False, description="Only return pinned queries"),
    connection_id: Optional[str] = Query(None, description="Filter by connection hash"),
    db_type: Optional[str] = Query(None, description="Filter by database type"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    Search through query history with optional filters.

    Supports:
    - Text search across query and SQL
    - Filter by pinned status
    - Filter by connection (connection_id = connection hash)
    - Filter by database type
    - Pagination
    """
    check_rate_limit(session_id, "generate")
    get_session(session_id)  # Validate session exists

    # Get current session history from Redis (hot storage)
    session_history = session_store.search_history(
        session_id,
        search_term=search_term,
        pinned_only=pinned_only,
        connection_id=connection_id,
        db_type=db_type,
        limit=limit,
        offset=offset,
    )

    # If connection_id provided, also fetch from PostgreSQL (cold storage, cross-session)
    history_entries = session_history
    if connection_id and query_history_service.is_available():
        try:
            # Fetch persistent history for this database connection
            persistent_history = await query_history_service.search_history(
                connection_hash=connection_id,
                db_type=db_type,
                search_term=search_term,
                pinned_only=pinned_only,
                limit=limit * 2,  # Fetch more since we'll deduplicate
                offset=offset
            )

            # Merge: Redis first (most recent), then PostgreSQL (deduplicate by ID)
            session_ids = {h.get("id") for h in session_history}
            merged = session_history + [
                h for h in persistent_history
                if h.get("id") not in session_ids
            ]

            # Re-sort by timestamp (newest first), apply final limit
            merged.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            history_entries = merged[:limit]

            logger.debug(
                f"Merged history: {len(session_history)} session + "
                f"{len(persistent_history)} persistent → {len(history_entries)} total"
            )
        except Exception as e:
            # Graceful degradation: if PostgreSQL fails, use session history only
            logger.warning(f"Failed to load connection history from PostgreSQL: {e}")
            history_entries = session_history

    return HistoryResponse(
        history=[
            HistoryEntry(
                id=h.get("id", ""),
                query=h.get("query", ""),
                sql=h.get("sql", ""),
                timestamp=h.get("timestamp", ""),
                feedback_rating=h.get("feedback_rating"),
                sql_hash=h.get("sql_hash"),
                explanation=h.get("explanation"),
                pinned=h.get("pinned", False),
                connection_id=h.get("connection_id"),
                db_type=h.get("db_type"),
                success=h.get("success"),
                error_message=h.get("error_message"),
                session_id=h.get("session_id") or session_id,
                # Analyst mode fields
                mode=h.get("mode"),
                answer=h.get("answer"),
                key_findings=h.get("key_findings"),
                confidence=h.get("confidence"),
                chart_spec=h.get("chart_spec"),
                raw_result_summary=h.get("raw_result_summary"),
                tools_used=h.get("tools_used"),
                agent_steps=h.get("agent_steps"),
                is_follow_up=h.get("is_follow_up"),
                conversation_turn=h.get("conversation_turn"),
            )
            for h in history_entries
        ]
    )


@router.get("/history/pinned", response_model=HistoryResponse)
async def get_pinned_queries(
    session_id: str = Query(..., description="Session ID"),
    connection_id: Optional[str] = Query(None, description="Filter by connection hash"),
    db_type: Optional[str] = Query(None, description="Filter by database type"),
):
    """
    Get all pinned queries for the session, optionally filtered by connection.
    """
    check_rate_limit(session_id, "generate")
    get_session(session_id)  # Validate session exists

    history_entries = session_store.get_pinned_queries(
        session_id,
        connection_id=connection_id,
        db_type=db_type,
    )

    return HistoryResponse(
        history=[
            HistoryEntry(
                id=h.get("id", ""),
                query=h.get("query", ""),
                sql=h.get("sql", ""),
                timestamp=h.get("timestamp", ""),
                feedback_rating=h.get("feedback_rating"),
                sql_hash=h.get("sql_hash"),
                explanation=h.get("explanation"),
                pinned=h.get("pinned", False),
                connection_id=h.get("connection_id"),
                db_type=h.get("db_type"),
                success=h.get("success"),
                error_message=h.get("error_message"),
                session_id=h.get("session_id") or session_id,
                # Analyst mode fields
                mode=h.get("mode"),
                answer=h.get("answer"),
                key_findings=h.get("key_findings"),
                confidence=h.get("confidence"),
                chart_spec=h.get("chart_spec"),
                raw_result_summary=h.get("raw_result_summary"),
                tools_used=h.get("tools_used"),
                agent_steps=h.get("agent_steps"),
                is_follow_up=h.get("is_follow_up"),
                conversation_turn=h.get("conversation_turn"),
            )
            for h in history_entries
        ]
    )


@router.post("/history/pin")
async def toggle_pin_query(
    request: PinnedQueryRequest,
    session_id: str = Query(..., description="Session ID"),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
):
    """
    Pin or unpin a query in history.

    Pinned queries are synced to backend and persist across devices.
    """
    validate_request(session_id, csrf_token, require_csrf=True)

    found = session_store.toggle_pin(session_id, request.query_id, request.pinned)

    if not found:
        raise HTTPException(status_code=404, detail="Query not found in history")

    return {"success": True, "query_id": request.query_id, "pinned": request.pinned}


@router.get("/history/{query_id}")
async def get_history_entry(
    query_id: str,
    session_id: str = Query(..., description="Session ID"),
):
    """
    Get a specific history entry by ID.

    Used for re-executing past queries using sql_hash.
    """
    check_rate_limit(session_id, "generate")
    get_session(session_id)  # Validate session exists

    entry = session_store.get_history_entry(session_id, query_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Query not found in history")

    return HistoryEntry(
        id=entry.get("id", ""),
        query=entry.get("query", ""),
        sql=entry.get("sql", ""),
        timestamp=entry.get("timestamp", ""),
        feedback_rating=entry.get("feedback_rating"),
        sql_hash=entry.get("sql_hash"),
        explanation=entry.get("explanation"),
        pinned=entry.get("pinned", False),
        connection_id=entry.get("connection_id"),
        db_type=entry.get("db_type"),
        success=entry.get("success"),
        error_message=entry.get("error_message"),
        session_id=entry.get("session_id") or session_id,
        # Analyst mode fields
        mode=entry.get("mode"),
        answer=entry.get("answer"),
        key_findings=entry.get("key_findings"),
        confidence=entry.get("confidence"),
        chart_spec=entry.get("chart_spec"),
        raw_result_summary=entry.get("raw_result_summary"),
        tools_used=entry.get("tools_used"),
        agent_steps=entry.get("agent_steps"),
        is_follow_up=entry.get("is_follow_up"),
        conversation_turn=entry.get("conversation_turn"),
    )


@router.post("/query/reexecute", response_model=ExecuteQueryResponse)
async def reexecute_from_history(
    request: ReexecuteFromHistoryRequest,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
):
    """
    Re-execute a query from history without requiring sql_hash.

    SECURITY MODEL:
    - SQL is fetched SERVER-SIDE from history using query_id
    - Client NEVER provides SQL - prevents tampering
    - Connection verification ensures query runs on same database
    - SQL is re-validated as read-only before execution
    - Works across sessions (no session-bound hash required)

    This enables:
    - Re-execution after logout/login
    - Re-execution from any device with same session history
    - Long-term history re-execution (no 1-hour expiry)

    Args:
        request: Contains session_id, query_id, and limit

    Returns:
        ExecuteQueryResponse with query results
    """
    logger.info(
        "Re-execute from history request",
        session_id=request.session_id[:8] if request.session_id else "None",
        query_id=request.query_id[:8] if request.query_id else "None",
    )

    # Validate session and rate limit
    session = validate_request(
        request.session_id, csrf_token, rate_limit_action="execute"
    )

    # Get current connection hash from session's db_config
    try:
        db_config = DatabaseConfig(**session["db_config"])
        current_connection_hash = vector_db._hash_connection(db_config.connection_url)
    except Exception as e:
        logger.error("Failed to parse db_config for re-execution", error=str(e))
        raise HTTPException(status_code=500, detail="Invalid database configuration")

    # SECURITY: Fetch SQL from history with connection verification
    # This is the core security mechanism - SQL comes from server storage
    # Try session store (Redis) first, then fall back to PostgreSQL for cross-session
    history_entry, error = session_store.get_history_for_reexecution(
        request.session_id,
        request.query_id,
        current_connection_hash,
    )

    # If not found in session store, try PostgreSQL (long-term storage)
    if error or not history_entry:
        logger.info(
            "Query not in session store, checking PostgreSQL",
            query_id=request.query_id[:8] if request.query_id else "None",
            session_error=error,
        )
        history_entry, error = await query_history_service.get_query_for_reexecution(
            request.query_id,
            current_connection_hash,
        )

    if error or not history_entry:
        logger.warning(
            "Re-execution denied",
            query_id=request.query_id[:8] if request.query_id else "None",
            reason=error or "History entry not found",
        )
        AuditLogger.log_security_event(
            request.session_id,
            "REEXECUTION_DENIED",
            f"Query: {request.query_id}, Reason: {error or 'not found'}",
        )
        raise HTTPException(status_code=403, detail=error or "Query not found")

    # Get the server-stored SQL (history_entry is guaranteed to be non-None here)
    sql = history_entry["sql"]
    stored_db_type = history_entry.get("db_type")

    # SECURITY: Validate db_type matches - prevent cross-database execution
    if stored_db_type and stored_db_type != db_config.db_type:
        logger.warning(
            "Re-execution denied: db_type mismatch",
            query_id=request.query_id[:8] if request.query_id else "None",
            stored_db_type=stored_db_type,
            current_db_type=db_config.db_type,
        )
        AuditLogger.log_security_event(
            request.session_id,
            "REEXECUTION_DENIED",
            f"Query: {request.query_id}, DB type mismatch: {stored_db_type} vs {db_config.db_type}",
        )
        raise HTTPException(
            status_code=403,
            detail=f"Query was generated for {stored_db_type}, but current database is {db_config.db_type}",
        )

    # Use stored db_type for validation, fallback to current for legacy entries
    validation_db_type = stored_db_type or db_config.db_type

    # SECURITY: Re-validate SQL is read-only (defense in depth)
    # Even though we stored it, verify it's still safe
    is_valid, validation_msg = SecurityService.validate_generated_sql(
        sql, validation_db_type
    )

    if not is_valid:
        logger.error(
            "Stored SQL failed validation on re-execution",
            query_id=request.query_id[:8] if request.query_id else "None",
            validation_msg=validation_msg,
        )
        AuditLogger.log_security_event(
            request.session_id,
            "STORED_SQL_INVALID",
            f"Query: {request.query_id}, SQL validation failed: {validation_msg}",
        )
        raise HTTPException(
            status_code=403,
            detail=f"Stored query failed safety validation: {validation_msg}",
        )

    # Execute the server-stored SQL
    try:
        logger.info(
            "Executing from history",
            query_id=request.query_id[:8] if request.query_id else "None",
            sql_preview=sql[:50] + "..." if len(sql) > 50 else sql,
        )

        results = await DatabaseService.execute_query(
            db_config,
            sql,
            request.limit,
            force_refresh=request.force_refresh,
        )

        # Apply result size limits
        results, size_warnings = ResultSizeLimiter.check_and_limit_results(results)
        if size_warnings:
            results["warnings"] = size_warnings

        # Add database type to response
        results["db_type"] = db_config.db_type

        # IMPORTANT: Register SQL hash for this session to enable export
        # This allows export after re-execution from history
        sql_hash = sql_integrity.register_sql(
            request.session_id,
            request.query_id,
            sql,
        )
        results["sql_hash"] = sql_hash

        # Audit log successful execution
        AuditLogger.log_sql_execution(
            request.session_id,
            request.query_id,
            sql,
            success=True,
            row_count=results.get("row_count", 0),
        )

        logger.info(
            "Re-execution successful",
            query_id=request.query_id[:8] if request.query_id else "None",
            row_count=results.get("row_count", 0),
            sql_hash=sql_hash[:8] if sql_hash else "None",
        )

        return ExecuteQueryResponse(**results)

    except ValueError as e:
        AuditLogger.log_sql_execution(
            request.session_id,
            request.query_id,
            sql,
            success=False,
            error=ErrorSanitizer.safe_log_error(e),
        )
        raise HTTPException(status_code=400, detail=ErrorSanitizer.sanitize_error(e))

    except Exception as e:
        AuditLogger.log_sql_execution(
            request.session_id,
            request.query_id,
            sql,
            success=False,
            error=ErrorSanitizer.safe_log_error(e),
        )
        logger.error("Re-execution error", error=ErrorSanitizer.safe_log_error(e))
        raise HTTPException(status_code=500, detail=ErrorSanitizer.sanitize_error(e))
