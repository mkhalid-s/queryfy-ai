# ============================================
# FILE: app/api/queries.py
# ============================================
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

# pandas is lazily imported inside ``export_to_excel`` — it's only used
# there, and a top-level import slows agent startup + breaks any test
# environment that doesn't ship pandas (everything else in this module
# is dataframe-free).

from app.core.config import settings
from app.core.csrf_utils import verify_csrf_token
from app.core.dependencies import get_session, validate_request
from app.core.logging_config import get_logger
from app.models.schemas import (
    ERROR_RESPONSES,
    DatabaseConfig,
    ExecuteQueryRequest,
    ExecuteQueryResponse,
    ExplainRequest,
    ExplainResponse,
    FeedbackRequest,
    FeedbackResponse,
    HistoryResponse,
    LLMConfig,
    QueryRequest,
    QueryResponse,
)
from app.services.database_service import DatabaseService
from app.services.llm_service import LLMService
from app.services.query_history_service import query_history_service
from app.services.security import (
    AuditLogger,
    ErrorSanitizer,
    ResultSizeLimiter,
    SecurityService,
    sql_integrity,
)
from app.services.session_store import session_store
from app.services.sql_agent import run_sql_agent
from app.services.sql_generation import SQLGenerationService
from app.services.vector_db import vector_db

router = APIRouter()
logger = get_logger(__name__)


async def _stream_sql_generation(ctx, session_id: str):
    """
    Generate SSE stream of SQL chunks.

    SSE Protocol:
    - data: <chunk>       - SQL content chunk (newlines escaped)
    - data: [META]<json>  - Metadata with query_id and sql_hash
    - data: [DONE]        - Completion signal
    - data: [ERROR] <msg> - Error message
    """
    import asyncio

    sql_generator = None

    try:
        # Fetch similar queries for few-shot learning (non-blocking for streaming)
        few_shot_examples = []
        try:
            few_shot_examples = vector_db.find_similar_queries(
                ctx.db_config.connection_url, ctx.sanitized_query, n=3
            )
        except Exception as e:
            # Non-critical for streaming, but log for debugging
            logger.debug(f"Vector DB lookup failed (non-critical): {e}")

        # Call LLM with streaming
        sql_generator, _ = await LLMService.generate_sql(
            ctx.llm_config,
            ctx.sanitized_query,
            ctx.relevant_schema,
            ctx.conversation_history,
            ctx.db_config.db_type,
            stream=True,
            few_shot_examples=few_shot_examples,
        )

        # Use list for O(n) concatenation instead of O(n²) string concat
        chunks = []
        try:
            async with asyncio.timeout(settings.AGENT_TIMEOUT_SECONDS):
                async for chunk in sql_generator:
                    chunks.append(chunk)
                    # Escape newlines for SSE compatibility
                    escaped = chunk.replace("\n", "\\n").replace("\r", "\\r")
                    yield f"data: {escaped}\n\n"
        except asyncio.TimeoutError:
            logger.warning(
                "Streaming SQL generation timed out", session_id=session_id[:8]
            )
            yield "data: [ERROR] SQL generation timed out\n\n"
            return

        full_sql = "".join(chunks)

        # After streaming complete, clean and validate SQL
        from app.services.prompt_providers import get_prompt_provider

        prompt_provider = get_prompt_provider(ctx.db_config.db_type)
        cleaned_sql = prompt_provider.clean_response(full_sql)

        # Validate the generated SQL
        is_valid, validation_msg = SecurityService.validate_generated_sql(
            cleaned_sql, ctx.db_config.db_type
        )

        if not is_valid:
            logger.warning("Streaming SQL validation failed", reason=validation_msg)
            # Escape validation message for SSE safety
            safe_msg = validation_msg.replace("\n", " ").replace("\r", " ")
            yield f"data: [ERROR] Invalid SQL generated: {safe_msg}\n\n"
            return

        # Update session history first to get the entry_id
        # Include db_type and connection_id for history re-execution support
        connection_hash = vector_db._hash_connection(ctx.db_config.connection_url)
        logger.info(
            "Streaming: registering SQL",
            session_id=session_id[:8],
            sql_length=len(cleaned_sql),
        )
        history_entry = {
            "query": ctx.natural_language,
            "sanitized_query": ctx.sanitized_query,
            "sql": cleaned_sql,
            "db_type": ctx.db_config.db_type,
            "connection_id": connection_hash,
        }
        query_id = session_store.add_history(session_id, history_entry)
        logger.info(
            "Streaming: history added", session_id=session_id[:8], query_id=query_id[:8]
        )

        # Register SQL for integrity tracking
        sql_hash = sql_integrity.register_sql(session_id, query_id, cleaned_sql)

        # Update history entry with sql_hash for re-execution support
        session_store.update_history_entry(session_id, query_id, {"sql_hash": sql_hash})

        # Persist to PostgreSQL for long-term storage (cross-session re-execution)
        await query_history_service.save_query(
            query_id=query_id,
            connection_hash=connection_hash,
            db_type=ctx.db_config.db_type,
            natural_query=ctx.natural_language,
            sql=cleaned_sql,
            sanitized_query=ctx.sanitized_query,
            sql_hash=sql_hash,
        )

        logger.info(
            "Streaming: SQL integrity registered",
            session_id=session_id[:8],
            query_id=query_id[:8],
            hash_prefix=sql_hash[:16],
        )

        # Send metadata as final message
        meta = {
            "query_id": query_id,
            "sql_hash": sql_hash,
            "sql": cleaned_sql,  # Send cleaned SQL for frontend to use
        }
        yield f"data: [META]{json.dumps(meta)}\n\n"
        yield "data: [DONE]\n\n"

        logger.info(
            "Streaming SQL generation complete",
            session_id=session_id[:8],
            query_id=query_id[:8],
        )

    except Exception as e:
        logger.error(
            "SQL generation stream failed", error=ErrorSanitizer.safe_log_error(e)
        )
        error_msg = ErrorSanitizer.sanitize_error(e)
        # Escape error message for SSE safety
        safe_error = str(error_msg).replace("\n", " ").replace("\r", " ")
        yield f"data: [ERROR] {safe_error}\n\n"
    finally:
        # Cleanup generator if it supports aclose
        if sql_generator and hasattr(sql_generator, "aclose"):
            try:
                await sql_generator.aclose()
            except Exception:
                pass  # Ignore cleanup errors


@router.post(
    "/query/generate",
    response_model=QueryResponse,
    responses={
        400: ERROR_RESPONSES[400],
        404: ERROR_RESPONSES[404],
        429: ERROR_RESPONSES[429],
        500: ERROR_RESPONSES[500],
    },
)
async def generate_sql(
    request: QueryRequest,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
    use_agent: bool = Query(
        False,
        description="Use LangGraph agent for self-healing SQL generation with retries",
    ),
    stream: bool = Query(
        False, description="Stream SQL generation via Server-Sent Events (SSE)"
    ),
):
    """
    Generate SQL from natural language.

    .. deprecated::
        Use POST /chat instead. This endpoint is kept for backward compatibility only.
        The /chat endpoint provides a unified interface with both standard and analyst modes.

    Args:
        use_agent: If True, uses LangGraph SQLAgent which provides:
            - Self-healing: Automatically retries on SQL errors
            - Up to 3 attempts with error context
            - Auto-execution and explanation
        stream: If True, returns SSE stream for progressive output.
            Not compatible with agent mode.
    """
    # Streaming not supported with agent mode
    if stream and use_agent:
        raise HTTPException(
            status_code=400,
            detail="Streaming is not supported with agent mode. Use stream=false with use_agent=true, or vice versa.",
        )

    # Consolidated validation: session lookup, CSRF, rate limit, schema check
    session = validate_request(
        request.session_id,
        csrf_token,
        rate_limit_action="generate",
        require_schema_ready=True,
    )

    # Prepare generation context (sanitizes input, extracts configs, gets schema)
    ctx, error_result = await SQLGenerationService.prepare_context(
        request.session_id, session, request.natural_language
    )

    if error_result:
        if stream:
            # For streaming, return error as SSE
            async def error_stream():
                yield f"data: [ERROR] {error_result.error or error_result.message}\n\n"

            return StreamingResponse(
                error_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        return QueryResponse(
            error=error_result.error,
            warnings=error_result.warnings,
            message=error_result.message,
        )

    # ========================================
    # STREAMING MODE: Return SSE stream
    # ========================================
    if stream:
        return StreamingResponse(
            _stream_sql_generation(ctx, request.session_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    # ========================================
    # AGENT MODE: Use LangGraph SQLAgent
    # ========================================
    if use_agent:
        # Type guard: ctx should not be None here since we checked error_result
        assert ctx is not None, "Context should not be None after prepare_context"

        try:
            logger.info("Using SQLAgent", query_preview=ctx.sanitized_query[:50])

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
                    "SQLAgent success",
                    attempts=agent_result.get("attempts", 1),
                    session_id=request.session_id[:8],
                )

                # Get usage data from agent result
                usage_data = agent_result.get("usage")
                usage_dict = (
                    usage_data.to_dict()
                    if usage_data and hasattr(usage_data, "to_dict")
                    else usage_data
                )

                return QueryResponse(
                    sql=result.sql,
                    query_id=result.query_id,
                    sql_hash=result.sql_hash,
                    message=f"Generated with {agent_result.get('attempts', 1)} attempt(s)",
                    usage=usage_dict,
                )
            else:
                return QueryResponse(
                    error="Unable to generate valid SQL",
                    message=f"Agent failed after {agent_result.get('attempts', 1)} attempts: {agent_result.get('error', 'Unknown error')}",
                )

        except Exception as e:
            logger.error("SQLAgent error", error=ErrorSanitizer.safe_log_error(e))
            raise HTTPException(
                status_code=500, detail=ErrorSanitizer.sanitize_error(e)
            )

    # ========================================
    # STANDARD MODE: Use SQL Generation Helper
    # ========================================
    # Type guard: ctx should not be None here since we checked error_result
    assert ctx is not None, "Context should not be None after prepare_context"

    result = await SQLGenerationService.generate_sql(ctx)

    if not result.success:
        return QueryResponse(error=result.error, message=result.message)

    return QueryResponse(
        sql=result.sql,
        query_id=result.query_id,
        sql_hash=result.sql_hash,
        usage=result.usage,
    )


@router.post(
    "/query/explain",
    responses={
        404: ERROR_RESPONSES[404],
        429: ERROR_RESPONSES[429],
        500: ERROR_RESPONSES[500],
    },
)
async def explain_sql(
    request: ExplainRequest, csrf_token: Optional[str] = Depends(verify_csrf_token)
):
    """
    Explain SQL in plain language.

    Set `stream=true` in the request body to receive Server-Sent Events (SSE)
    for progressive streaming. Otherwise returns JSON with complete explanation.
    """
    # Consolidated validation: session lookup, CSRF, rate limit
    session = validate_request(
        request.session_id, csrf_token, rate_limit_action="generate"
    )

    # Verify SQL was generated in this session (for explain, we allow it to proceed even if not found)
    is_verified, _ = sql_integrity.verify_sql(
        request.session_id, "", request.sql_query, None
    )
    if not is_verified:
        logger.warning(
            "Explain requested for unregistered SQL", session_id=request.session_id[:8]
        )

    llm_config = LLMConfig(**session["llm_config"])
    db_config = DatabaseConfig(**session["db_config"])
    schema = vector_db.get_full_schema_text(db_config.connection_url)

    # === Streaming mode ===
    if request.stream:

        async def generate_stream():
            """Generate SSE stream of explanation chunks"""
            try:
                # Use consolidated explain_sql with stream=True
                stream_result = await LLMService.explain_sql(
                    llm_config,
                    request.sql_query,
                    schema,
                    db_config.db_type,
                    stream=True,
                )
                # For streaming, result is (generator, None)
                stream_generator = (
                    stream_result[0]
                    if isinstance(stream_result, tuple)
                    else stream_result
                )
                async for chunk in stream_generator:
                    # SSE format: data: <content>\n\n
                    # Escape newlines in chunk for SSE compatibility
                    escaped_chunk = chunk.replace("\n", "\\n").replace("\r", "\\r")
                    yield f"data: {escaped_chunk}\n\n"

                # Signal completion
                yield "data: [DONE]\n\n"

            except Exception as e:
                logger.error(
                    "SQL explain stream failed", error=ErrorSanitizer.safe_log_error(e)
                )
                error_msg = ErrorSanitizer.sanitize_error(e)
                yield f"data: [ERROR] {error_msg}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    # === Non-streaming mode (default) ===
    try:
        result = await LLMService.explain_sql(
            llm_config, request.sql_query, schema, db_config.db_type, stream=False
        )
        # Result is now a tuple (explanation, usage)
        explanation, usage = result
        usage_dict = usage.to_dict() if usage and hasattr(usage, "to_dict") else None
        return ExplainResponse(explanation=explanation, usage=usage_dict)
    except Exception as e:
        logger.error("SQL explain failed", error=ErrorSanitizer.safe_log_error(e))
        raise HTTPException(status_code=500, detail=ErrorSanitizer.sanitize_error(e))


@router.post(
    "/query/execute",
    response_model=ExecuteQueryResponse,
    responses={
        400: ERROR_RESPONSES[400],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
        429: ERROR_RESPONSES[429],
        500: ERROR_RESPONSES[500],
    },
)
async def execute_query(
    request: ExecuteQueryRequest, csrf_token: Optional[str] = Depends(verify_csrf_token)
):
    """Execute SQL query (read-only) with security verification"""
    logger.info(
        "Execute request",
        session_id=request.session_id[:8],
        sql_length=len(request.sql_query),
    )

    # Consolidated validation: session lookup, CSRF, rate limit
    session = validate_request(
        request.session_id, csrf_token, rate_limit_action="execute"
    )

    # SECURITY: Verify SQL integrity
    # This ensures the SQL was generated in this session and hasn't been tampered with
    query_id = getattr(request, "query_id", None)
    sql_hash = getattr(request, "sql_hash", None)

    is_verified, verify_msg = sql_integrity.verify_sql(
        request.session_id, query_id or "", request.sql_query, sql_hash
    )

    if not is_verified:
        AuditLogger.log_security_event(
            request.session_id,
            "SQL_VERIFICATION_FAILED",
            f"Reason: {verify_msg}, SQL: {request.sql_query[:100]}...",
        )
        raise HTTPException(
            status_code=403, detail=f"Security check failed: {verify_msg}"
        )

    try:
        db_config = DatabaseConfig(**session["db_config"])
        logger.info("DB config loaded", db_type=db_config.db_type)
    except Exception as e:
        logger.error("Failed to parse db_config", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Invalid database configuration: {e}"
        )

    try:
        logger.info("Executing verified SQL", sql_preview=request.sql_query[:100])
        results = await DatabaseService.execute_query(
            db_config,
            request.sql_query,
            request.limit,
            force_refresh=request.force_refresh,
        )

        # SECURITY: Apply result size limits to prevent memory exhaustion
        results, size_warnings = ResultSizeLimiter.check_and_limit_results(results)
        if size_warnings:
            results["warnings"] = size_warnings
            logger.info("Result size warnings", warnings=size_warnings)

        # Add database type to response for frontend view selection
        results["db_type"] = db_config.db_type

        # Mark as executed for audit trail
        if query_id:
            sql_integrity.mark_executed(request.session_id, query_id)

        # Audit log successful execution
        AuditLogger.log_sql_execution(
            request.session_id,
            query_id or "",
            request.sql_query,
            success=True,
            row_count=results.get("row_count", 0),
        )

        logger.info("Query executed", row_count=results.get("row_count", 0))
        return ExecuteQueryResponse(**results)

    except ValueError as e:
        AuditLogger.log_sql_execution(
            request.session_id,
            query_id or "",
            request.sql_query,
            success=False,
            error=ErrorSanitizer.safe_log_error(e),
        )
        logger.warning("Validation error", error=ErrorSanitizer.safe_log_error(e))
        # SECURITY: Sanitize error message for client
        raise HTTPException(status_code=400, detail=ErrorSanitizer.sanitize_error(e))
    except Exception as e:
        AuditLogger.log_sql_execution(
            request.session_id,
            query_id or "",
            request.sql_query,
            success=False,
            error=ErrorSanitizer.safe_log_error(e),
        )
        logger.error(
            "Query execution failed",
            error_type=type(e).__name__,
            error=ErrorSanitizer.safe_log_error(e),
        )
        # SECURITY: Sanitize error message for client
        raise HTTPException(status_code=500, detail=ErrorSanitizer.sanitize_error(e))


@router.post(
    "/query/export",
    responses={
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
        429: ERROR_RESPONSES[429],
    },
)
async def export_to_excel(
    request: ExecuteQueryRequest, csrf_token: Optional[str] = Depends(verify_csrf_token)
):
    """Export query results to Excel with security verification"""
    # Consolidated validation: session lookup, CSRF, rate limit (stricter for exports)
    session = validate_request(
        request.session_id, csrf_token, rate_limit_action="export"
    )

    # SECURITY: Verify SQL integrity before export
    query_id = getattr(request, "query_id", None)
    sql_hash = getattr(request, "sql_hash", None)

    if query_id:  # Only verify if query_id is present
        is_verified, verify_msg = sql_integrity.verify_sql(
            request.session_id, query_id, request.sql_query, sql_hash
        )

        if not is_verified:
            AuditLogger.log_security_event(
                request.session_id,
                "EXPORT_VERIFICATION_FAILED",
                f"Reason: {verify_msg}, SQL: {request.sql_query[:100]}...",
            )
            raise HTTPException(
                status_code=403, detail=f"Security check failed: {verify_msg}"
            )
    else:
        logger.warning("Export without query_id - skipping verification")

    db_config = DatabaseConfig(**session["db_config"])

    # Phase 4.3: prefer the cached result over re-running the SQL. This
    # is the fix for the "summary says 200 results but export gives
    # 9000 rows" drift the user reported — both the analysis and the
    # export now read from the same materialised set, so columns and
    # counts are guaranteed consistent. Falls back to a fresh DB run
    # if the cache has expired or wasn't populated (e.g. the user
    # clicked Export 31 minutes after the query ran, past the
    # RESULT_CACHE_TTL_SECONDS budget).
    rows_ref = getattr(request, "rows_ref", None)
    cache_used = False
    results = None
    if rows_ref:
        # SECURITY HOTFIX — IDOR (CRITICAL): the caller can submit any
        # rows_ref string; without this check Mallory could set
        # ``rows_ref = result:{victim_session}:{victim_qid}`` alongside
        # her OWN session_id + CSRF + registered sql_hash, pass all
        # existing integrity checks (which only validate SQL), and
        # export Alice's cached rows. Reject any rows_ref whose session
        # prefix doesn't match the request's session.
        import hmac as _hmac

        expected_prefix = f"result:{request.session_id}:"
        # hmac.compare_digest prevents length-leak side channels, but
        # the prefix is a known public format so timing info is
        # minimal; still use it for consistency with the rest of our
        # session-token comparisons.
        prefix_actual = rows_ref[: len(expected_prefix)]
        if not _hmac.compare_digest(prefix_actual, expected_prefix):
            AuditLogger.log_security_event(
                request.session_id,
                "EXPORT_ROWS_REF_OWNERSHIP_MISMATCH",
                f"rows_ref={rows_ref[:60]}...",
            )
            raise HTTPException(
                status_code=403,
                detail="rows_ref does not belong to this session.",
            )

        try:
            from app.services.result_cache import result_cache

            # Phase 4 Batch E: async wrapper to avoid blocking on big reads.
            slice_ = await result_cache.aget_rows_slice(
                rows_ref, offset=0, limit=None
            )
            if slice_ is not None:
                results = {
                    "rows": slice_["rows"],
                    "columns": slice_["columns"],
                    "row_count": slice_["total_row_count"],
                }
                cache_used = True
                logger.info(
                    "Export sourced from cache",
                    rows_ref=rows_ref,
                    row_count=slice_["total_row_count"],
                )
        except Exception as e:
            logger.warning(
                f"Export cache lookup failed for {rows_ref}: {e} — "
                f"falling back to SQL re-execution"
            )

    if results is None:
        results = await DatabaseService.execute_query(
            db_config,
            request.sql_query,
            min(request.limit, settings.MAX_EXPORT_ROWS),
        )

    # Audit log the export (query_id may be None for manual queries)
    if query_id:
        AuditLogger.log_sql_execution(
            request.session_id,
            query_id,
            request.sql_query,
            success=True,
            row_count=results.get("row_count", 0),
        )
    logger.info(
        "Export completed",
        session_id=request.session_id[:8],
        row_count=results.get("row_count", 0),
        from_cache=cache_used,
    )

    import pandas as pd  # lazy — only the export endpoint needs it

    # Excel export bypasses the agent + frontend redaction paths
    # entirely — users pull the file straight into their local
    # tools. The cache path is already clean (execute_and_analyze
    # writes redacted rows). But the fallback SQL re-execution path
    # (``DatabaseService.execute_query`` above when ``rows_ref``
    # expired) returns RAW rows — redact before DataFrame
    # construction to keep the file safe regardless of source.
    try:
        from app.services.tools.query_tools import (
            _load_pii_column_set_for_query,
            _redact_pii_in_rows,
        )
        _export_columns = list(results.get("columns", []))
        _export_rows = results.get("rows", []) or []
        # Query-scoped helper narrows the dictionary lookup to tables
        # referenced by ``request.sql_query`` across SQL/CQL/PartiQL/
        # Mongo dialects. Falls through to connection-wide OR-
        # semantics when the SQL doesn't parse to identifiers.
        _pii_cols = await _load_pii_column_set_for_query(
            db_config, _export_columns, request.sql_query
        )
        _redact_pii_in_rows(_export_rows, _pii_cols)
        if _pii_cols:
            logger.info(
                "export.pii_masked",
                rows_ref=rows_ref or "",
                pii_columns=sorted(_pii_cols),
                affected_rows=len(_export_rows),
            )
    except Exception as _pii_err:
        # Never block a legitimate export on a dictionary lookup
        # failure — the fallback SQL path above would have already
        # failed if the connection were broken. Log and continue.
        logger.warning(
            f"export: PII redaction skipped for {rows_ref or 'fresh-query'}: {_pii_err}"
        )

    df = pd.DataFrame(results["rows"])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
    output.seek(0)

    filename = f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    # Phase 4.3 Batch B (M7): tell the frontend whether this export
    # was sourced from the result cache or freshly re-executed. The
    # UI uses this to toast "Export sourced from fresh query (cache
    # expired)" so the user knows the data may differ from what the
    # analysis described.
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Export-Source": "cache" if cache_used else "sql",
            # Allow the browser fetch to read the custom header in CORS contexts.
            "Access-Control-Expose-Headers": "X-Export-Source, Content-Disposition",
        },
    )


@router.get(
    "/results/{rows_ref}",
    responses={
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def get_cached_query_result(
    rows_ref: str,
    session_id: str = Query(
        ..., description="Session that owns this cached result"
    ),
    offset: int = Query(0, ge=0, description="0-based row offset"),
    limit: int = Query(
        100, ge=1, le=1000, description="Rows per page (max 1000)"
    ),
):
    """
    Phase 4.3: paginated fetch of a cached query result.

    Authorization (hotfix): the endpoint REQUIRES ``session_id`` as a
    query parameter, validates the session exists, AND verifies the
    rows_ref belongs to that session (prefix match using
    ``hmac.compare_digest``). Without these checks any leaked
    rows_ref would read cross-session cached rows — the original
    implementation had no auth at all and relied on a docstring
    claim that production had "additional middleware" that did not
    in fact exist in this repo.

    Rate limiting: also enforced via validate_request.
    """
    import hmac as _hmac

    # Step 1: verify the session exists AND is this caller's
    # (ties into the existing validate_request pipeline; also
    # applies per-session rate limiting under action=results_read).
    from app.core.dependencies import validate_request

    validate_request(
        session_id,
        csrf_token=None,  # GET requests are CSRF-exempt by convention
        rate_limit_action="results_read",
        require_csrf=False,
    )

    # Step 2: verify rows_ref is owned by this session. Rows_ref is
    # ``result:{session_id}:{query_id}`` — a foreign prefix means
    # another session's handle is being read.
    expected_prefix = f"result:{session_id}:"
    if not _hmac.compare_digest(
        rows_ref[: len(expected_prefix)], expected_prefix
    ):
        AuditLogger.log_security_event(
            session_id,
            "RESULTS_FETCH_FOREIGN_ROWS_REF",
            f"rows_ref={rows_ref[:60]}...",
        )
        raise HTTPException(
            status_code=403,
            detail="rows_ref does not belong to this session.",
        )

    from app.services.result_cache import result_cache

    # Phase 4 Batch E: aget_rows_slice wraps the sync redis GET in
    # asyncio.to_thread so this endpoint doesn't block the FastAPI
    # event loop on big page reads.
    slice_ = await result_cache.aget_rows_slice(
        rows_ref, offset=offset, limit=limit
    )
    if slice_ is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Cached result {rows_ref!r} not found or expired. "
                f"Re-run the query to repopulate the cache."
            ),
        )

    return {
        "rows_ref": rows_ref,
        "offset": slice_["offset"],
        "limit": slice_["limit"],
        "rows": slice_["rows"],
        "columns": slice_["columns"],
        "total_row_count": slice_["total_row_count"],
        "has_more": slice_["has_more"],
    }


@router.get(
    "/history/{session_id}",
    response_model=HistoryResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_history(session_id: str):
    """Get query history"""
    # Session lookup only (no CSRF for GET, no rate limit for history)
    session = get_session(session_id)
    return HistoryResponse(history=session.get("history", []))


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest, csrf_token: Optional[str] = Depends(verify_csrf_token)
) -> FeedbackResponse:
    """Submit feedback for a query"""
    # Consolidated validation: session lookup + CSRF (no rate limit for feedback)
    session = validate_request(request.session_id, csrf_token, require_csrf=True)

    # Store feedback in session
    session_store.add_feedback(
        request.session_id, request.query_id, request.rating, request.comment
    )

    # Update vector_db with feedback rating for improved few-shot learning
    try:
        if not request.query_id:
            logger.warning("Feedback received with empty query_id")
        else:
            # Find the query in history to get the SQL and original question
            found = False
            for entry in session.get("history", []):
                if entry.get("id") == request.query_id:
                    found = True
                    query_text = entry.get("sanitized_query") or entry.get("query", "")
                    sql = entry.get("sql", "")
                    db_config = session.get("db_config", {})
                    connection_url = db_config.get("connection_url", "")

                    if query_text and sql and connection_url:
                        # Re-store the query with the updated rating
                        vector_db.store_successful_query(
                            connection_url, query_text, sql, rating=request.rating
                        )
                        logger.info(
                            "Vector DB updated with feedback",
                            query_id=request.query_id[:8] if request.query_id else "unknown",
                            rating=request.rating,
                        )
                    break

            if not found:
                logger.warning(
                    "Feedback query_id not found in history",
                    query_id=request.query_id[:8] if request.query_id else "unknown",
                )
    except Exception as e:
        # Non-critical - don't fail the request
        logger.debug("Vector DB feedback update skipped", error=str(e))

    return FeedbackResponse(message="Feedback submitted", rating=request.rating)
