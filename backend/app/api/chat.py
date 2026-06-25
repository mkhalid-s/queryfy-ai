# ============================================
# FILE: app/api/chat.py
#
# Unified Chat Endpoint for All Query Modes
# ============================================
"""
Single unified chat endpoint that handles all query interactions:
- Standard mode: SQL generation only (fast, single-pass)
- Analyst mode: Insight-rich answers with SQL, charts, and key findings

Everything goes through POST /chat
"""

import asyncio
import re
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.csrf_utils import verify_csrf_token
from app.core.dependencies import validate_request
from app.core.logging_config import get_logger
from app.models.chat_models import (
    ChatMode,
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
)
from app.models.schemas import ERROR_RESPONSES, DatabaseConfig, LLMConfig
from app.services.answer_generator import AnswerGenerator
from app.services.database_service import DatabaseService
from app.services.llm_service import LLMService
from app.services.prompt_providers import get_prompt_provider
from app.services.query_history_service import query_history_service
from app.services.react_agent import ReActAgent, generate_data_summary, run_react_agent
from app.services.security import (
    ErrorSanitizer,
    SecurityService,
    sql_integrity,
)
from app.services.session_store import session_store
from app.services.sql_generation import SQLGenerationService
from app.services.vector_db import vector_db

router = APIRouter()
logger = get_logger(__name__)


# ============================================
# HELPER FUNCTIONS
# ============================================


def _generate_query_id() -> str:
    """Generate a unique query ID."""
    return str(uuid.uuid4())[:8]


def _get_llm_config(session: dict) -> LLMConfig:
    """
    Extract LLMConfig from session data.

    Args:
        session: Session dictionary containing llm_config key.

    Returns:
        LLMConfig instance with provider, model, and API key settings.
    """
    llm_dict = session.get("llm_config", {})
    return LLMConfig(**llm_dict)


def _get_db_config(session: dict) -> DatabaseConfig:
    """
    Extract DatabaseConfig from session data.

    Args:
        session: Session dictionary containing db_config key.

    Returns:
        DatabaseConfig instance with connection URL and database type.
    """
    db_dict = session.get("db_config", {})
    return DatabaseConfig(**db_dict)


# ============================================
# CONVERSATION CONTEXT HELPERS
# ============================================


def _detect_follow_up(message: str, last_context: Optional[Dict]) -> bool:
    """
    Detect if message is a follow-up to previous query.

    Uses pattern matching to identify conversational continuations:
    - References to "that", "this", "it"
    - Conjunctions starting sentences
    - References to "previous", "last"
    - Questions about prior results

    Args:
        message: User's current message
        last_context: Previous query context from session

    Returns:
        True if message appears to be a follow-up
    """
    if not message or not message.strip():
        return False

    if not last_context:
        return False

    follow_up_patterns = [
        r"^(break|split|group|filter|sort|order)\s+(that|this|it)",
        r"^(and|but|also|now)\s+",
        r"^(what about|how about|can you also)",
        r"^(show me|give me)\s+(more|less|only)",
        r"previous|last\s+(query|result|data)",
        r"^(why|how come|explain)",
        r"^(the same|same thing)\s+(but|for)",
        r"\b(that|this|those|these)\s+(data|result|query|table)",
    ]

    message_lower = message.lower().strip()
    is_follow_up = any(re.search(p, message_lower) for p in follow_up_patterns)

    if is_follow_up:
        logger.debug(f"Detected follow-up query: {message[:50]}...")

    return is_follow_up


def _build_conversation_context(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build conversation context from session's context_window.

    Transforms stored history entries into structured format for agent.
    Returns last 5 turns by default (configurable in session_store.get_conversation_context).

    Args:
        session: Session dictionary from session store

    Returns:
        List of conversation turn dicts with question, query, db_type, success, timestamp
    """
    if not session:
        logger.warning("Attempted to build conversation context with None session")
        return []

    # Delegate to session_store which handles the transformation
    return session_store.get_conversation_context(
        session_id=session.get("id", ""),
        limit=5,  # Last 5 turns for optimal token usage
    )


def _detect_query_type(sql: str) -> str:
    """Detect the type of SQL query."""
    sql_upper = sql.strip().upper()
    for keyword in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"]:
        if sql_upper.startswith(keyword):
            return "DDL" if keyword in ["CREATE", "ALTER", "DROP"] else keyword
    return "OTHER"


def _flatten_insights_to_key_findings(insights: List[Dict[str, Any]]) -> List[str]:
    """
    Flatten the structured ``insights`` payload into the legacy
    ``key_findings`` string list that older UI surfaces still read.

    Single source of truth for the flattening — the streaming and
    non-streaming analyst-mode paths both delegate here so a future
    refactor can't update one and silently drift from the other.

    Takes the first 5 insights and prefixes each with ``[SEVERITY]``
    when available. Defensive against missing severity / description
    fields.
    """
    out: List[str] = []
    for insight in (insights or [])[:5]:
        severity = insight.get("severity", "")
        desc = insight.get("description", "")
        prefix = f"[{severity.upper()}] " if severity else ""
        out.append(prefix + desc)
    return out


def _combine_usage(usage1: Optional[dict], usage2: Optional[dict]) -> dict:
    """Combine usage data from multiple LLM calls."""
    if not usage1 and not usage2:
        return {}
    combined = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "calls": 0}
    for usage in [usage1, usage2]:
        if usage:
            combined["prompt_tokens"] += usage.get("prompt_tokens", 0)
            combined["completion_tokens"] += usage.get("completion_tokens", 0)
            combined["total_tokens"] += usage.get("total_tokens", 0)
            combined["cost_usd"] += usage.get("cost_usd", 0.0)
            combined["calls"] += usage.get("calls", 1)
    return combined


# ============================================
# STANDARD MODE HANDLER
# ============================================


async def _handle_standard_mode(
    session_id: str,
    session: dict,
    message: str,
    llm_config: LLMConfig,
    db_config: DatabaseConfig,
    continue_conversation: bool = True,
) -> ChatResponse:
    """Handle standard SQL generation mode with conversation support."""
    # Calculate conversation turn
    conversation_turn = len(session.get("context_window", [])) + 1

    ctx, error_result = await SQLGenerationService.prepare_context(
        session_id, session, message, continue_conversation=continue_conversation
    )

    if error_result:
        return ChatResponse(
            success=False,
            mode=ChatMode.STANDARD,
            error=error_result.error,
            warnings=error_result.warnings or [],
            is_follow_up=False,
            conversation_turn=conversation_turn,
        )

    # At this point, ctx is guaranteed to be non-None (prepare_context ensures one or the other)
    assert ctx is not None, "Context must be non-None when error_result is None"

    result = await SQLGenerationService.generate_sql(ctx)

    if not result.success:
        return ChatResponse(
            success=False,
            mode=ChatMode.STANDARD,
            error=result.error,
            warnings=[result.message] if result.message else [],
            is_follow_up=ctx.is_follow_up,
            conversation_turn=conversation_turn,
        )

    # In success case, SQL and query_id must be present
    assert result.sql is not None, "SQL must be present in successful generation"
    assert result.query_id is not None, "Query ID must be present in successful generation"

    # Update last_query_context for follow-up detection
    session_store.update(
        session_id,
        {
            "last_query_context": {
                "query_id": result.query_id,
                "question": message,
                "sql": result.sql,
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )

    return ChatResponse(
        success=True,
        mode=ChatMode.STANDARD,
        sql=result.sql,
        is_valid=True,
        query_type=_detect_query_type(result.sql),
        query_id=result.query_id,
        sql_hash=result.sql_hash,
        is_follow_up=ctx.is_follow_up,
        conversation_turn=conversation_turn,
    )


# ============================================
# ANALYST MODE HANDLER
# ============================================


async def _handle_analyst_mode(
    session_id: str,
    session: dict,
    message: str,
    llm_config: LLMConfig,
    db_config: DatabaseConfig,
    include_reasoning: bool = False,
    include_chart: bool = True,
    continue_conversation: bool = True,
) -> ChatResponse:
    """Handle analyst mode with insight-rich responses and conversation support."""
    query_id = _generate_query_id()
    tools_used = []

    # Reset conversation state on Fresh start
    if not continue_conversation:
        session_store.reset_conversation(session_id)
        session = session_store.get(session_id) or session

    # Build conversation context
    conversation_context = _build_conversation_context(session) if continue_conversation else None
    is_follow_up = _detect_follow_up(message, session.get("last_query_context")) if continue_conversation else False
    conversation_turn = len(session.get("context_window", [])) + 1

    # Fetch data dictionary context for enriched agent responses
    data_dictionary_context = None
    try:
        connection_hash = vector_db._hash_connection(db_config.connection_url)
        business_terms_ctx, column_ctx = await SQLGenerationService._get_data_dictionary_context(
            connection_hash=connection_hash,
            query=message,
        )
        # Combine business terms and column context
        parts = []
        if business_terms_ctx:
            parts.append(business_terms_ctx)
        if column_ctx:
            parts.append(column_ctx)
        if parts:
            data_dictionary_context = "\n\n".join(parts)
    except Exception as e:
        logger.debug("Failed to fetch data dictionary context for analyst mode", error=str(e))

    try:
        reasoning = None

        logger.info(
            "Starting analyst mode",
            session_id=session_id[:8],
            question_preview=message[:50],
            is_follow_up=is_follow_up,
            conversation_turn=conversation_turn,
            has_data_dictionary=bool(data_dictionary_context),
        )

        agent_result = await run_react_agent(
            question=message,
            llm_config=llm_config,
            db_config=db_config,
            session_id=session_id,
            max_iterations=10,
            resume=is_follow_up and continue_conversation,
            conversation_context=conversation_context if continue_conversation else None,
            data_dictionary_context=data_dictionary_context,
        )

        if not agent_result.get("success"):
            return ChatResponse(
                success=False,
                mode=ChatMode.ANALYST,
                error=agent_result.get("error", "Agent failed to generate SQL"),
                query_id=query_id,
                is_follow_up=is_follow_up,
                conversation_turn=conversation_turn,
            )

        sql = agent_result.get("sql")
        tools_used = agent_result.get("tools_used", [])

        if not sql:
            return ChatResponse(
                success=False,
                mode=ChatMode.ANALYST,
                error="Agent did not generate SQL",
                tools_used=tools_used,
                query_id=query_id,
                is_follow_up=is_follow_up,
                conversation_turn=conversation_turn,
            )

        # Register SQL and get the correct hash (HMAC-based for security)
        sql_hash = sql_integrity.register_sql(session_id, query_id, sql)

        # Get execution result from agent (now contains structured data)
        execution_result = agent_result.get("execution_result")
        if not execution_result or not execution_result.get("success"):
            # Agent didn't execute, run query ourselves
            try:
                # Use force_refresh to ensure fresh data matches what agent reported
                exec_result = await DatabaseService.execute_query(db_config, sql, limit=500, force_refresh=True)
                execution_result = {
                    "columns": exec_result.get("columns", []),
                    "rows": exec_result.get("rows", []),
                    "row_count": exec_result.get("row_count", 0),
                }
            except Exception as e:
                logger.error("SQL execution failed", error=str(e))
                return ChatResponse(
                    success=False,
                    mode=ChatMode.ANALYST,
                    sql=sql,
                    sql_hash=sql_hash,
                    error=f"SQL execution failed: {ErrorSanitizer.sanitize_error(e)}",
                    tools_used=tools_used,
                    query_id=query_id,
                    is_follow_up=is_follow_up,
                    conversation_turn=conversation_turn,
                )
        # Agent's execution_result already has structured data (columns, rows, row_count)
        row_count = execution_result.get('row_count', 0)
        rows_len = len(execution_result.get('rows', []))
        logger.info(f"Analyst mode: execution_result row_count={row_count}, actual_rows={rows_len}, success={execution_result.get('success')}")

        # Generate data-driven summary (accurate, based on actual data)
        data_summary = generate_data_summary(message, execution_result)

        # Check if we have pre-computed analysis from execute_and_analyze
        has_analysis = execution_result.get("has_analysis", False)

        if has_analysis:
            # Use pre-computed data (skip expensive AnswerGenerator call)
            logger.info("Using pre-computed analysis from execute_and_analyze - skipping AnswerGenerator")

            # Single source of truth — the streaming path uses the
            # same helper.
            key_findings = _flatten_insights_to_key_findings(
                execution_result.get("insights", [])
            )

            # Extract pre-computed chart
            chart_raw = execution_result.get("chart")
            chart_dict = None
            if chart_raw and include_chart:
                # Ensure proper format for frontend
                chart_dict = {
                    "chart_type": chart_raw.get("recommended_chart", chart_raw.get("chart_type", "bar")),
                    "title": chart_raw.get("title", "Analysis"),
                    "x_axis": chart_raw.get("config", {}).get("x_axis", "") or chart_raw.get("x_axis", ""),
                    "y_axis": chart_raw.get("config", {}).get("y_axis", "") or chart_raw.get("y_axis", ""),
                }

            # Confidence from quality score
            quality_score = execution_result.get("quality", {}).get("overall_score", 95)
            confidence = min(0.95, quality_score / 100)

        else:
            # Original path: Generate LLM insights (for execute_sql or when no analysis)
            logger.info("Generating LLM insights via AnswerGenerator")

            answer_result = await AnswerGenerator.generate(
                llm_config=llm_config,
                question=message,
                sql=sql,
                result=execution_result,
                db_type=db_config.db_type,
                include_reasoning=include_reasoning,
            )

            key_findings = answer_result.key_findings if answer_result else []
            confidence = answer_result.confidence if answer_result else 0.5
            reasoning = answer_result.reasoning if answer_result and include_reasoning else None

            # Build chart dict
            chart_dict = None
            if include_chart and answer_result.chart:
                chart_dict = {
                    "chart_type": answer_result.chart.chart_type.value,
                    "title": answer_result.chart.title,
                    "x_axis": answer_result.chart.x_axis,
                    "y_axis": answer_result.chart.y_axis,
                    "data": answer_result.chart.data,
                }

        # Build raw_result_summary for persistence. Phase 4 wiring fix:
        # the tool already returns a 20-row preview (not the full set),
        # so don't re-truncate to 5 — it just hides rows the user could
        # otherwise see while waiting for the cache fetch.
        # ALSO carry rows_ref / rows_cached / preview_row_count /
        # rows_truncated through so the frontend can fetch the full
        # rows from /api/v1/results/{rows_ref}. Without these the
        # whole Phase 4 cache pipeline is invisible to the UI.
        raw_result_summary = {
            "columns": execution_result.get("columns", [])[:20],  # Max 20 columns
            "row_count": execution_result.get("row_count", 0),
            # E2E hotfix: frontend reads ``rows`` consistently (both the
            # live SSE ``done`` event and history restore). Keep
            # ``sample_rows`` as an alias for any older clients still
            # reading the historical key.
            "rows": execution_result.get("rows", []),
            "sample_rows": execution_result.get("rows", []),  # 20-row preview as-is
            "rows_ref": execution_result.get("rows_ref"),
            "rows_cached": execution_result.get("rows_cached", False),
            "preview_row_count": execution_result.get("preview_row_count"),
            "rows_truncated": execution_result.get("rows_truncated", False),
            "rows_truncated_reason": execution_result.get("rows_truncated_reason"),
        }

        # Get connection hash for PostgreSQL persistence
        connection_hash = vector_db._hash_connection(db_config.connection_url)

        # Add to session history with full analyst data
        base_entry = {
            "query": message,
            "sql": sql,
            "sql_hash": sql_hash,
            "mode": "analyst",
            "success": True,
        }

        session_store.add_history(
            session_id,
            base_entry,
            answer=data_summary,
            key_findings=key_findings,
            confidence=confidence,
            chart_spec=chart_dict,
            raw_result_summary=raw_result_summary,
            tools_used=tools_used,
            agent_steps=None,  # Agent steps not captured in non-streaming
            is_follow_up=is_follow_up,
            conversation_turn=conversation_turn,
        )

        # Persist to PostgreSQL for cross-session restore
        await query_history_service.save_query(
            query_id=query_id,
            connection_hash=connection_hash,
            db_type=db_config.db_type,
            natural_query=message,
            sql=sql,
            sql_hash=sql_hash,
            mode="analyst",
            answer=data_summary,
            key_findings=answer_result.key_findings if answer_result else [],
            confidence=answer_result.confidence if answer_result else None,
            chart_spec=chart_dict,
            raw_result_summary=raw_result_summary,
            tools_used=tools_used,
            agent_steps=None,
            is_follow_up=is_follow_up,
            conversation_turn=conversation_turn,
            session_id=session_id,
        )

        # Cache result for conversation reference
        session_store.cache_query_result(
            session_id,
            query_id,
            {
                "columns": execution_result.get("columns", []),
                "rows": execution_result.get("rows", []),
                "row_count": execution_result.get("row_count", 0),
                "sql": sql,
            },
        )

        # Update last_query_context for follow-up detection
        session_store.update(
            session_id,
            {
                "last_query_context": {
                    "query_id": query_id,
                    "question": message,
                    "sql": sql,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            },
        )

        # Extract follow-up suggestions from agent result
        suggestions_list = agent_result.get("suggestions")

        logger.info("Analyst mode complete", tools_used=tools_used, has_chart=chart_dict is not None)

        # Create lightweight result summary (full data fetched on-demand
        # via /api/v1/results/{rows_ref} after Phase 4.3). Carry the
        # rows_ref + cache-state fields through; without them the
        # frontend can't know to fetch and falls back to the 20-row
        # preview indefinitely.
        result_summary = {
            "row_count": execution_result.get("row_count", 0),
            "columns": execution_result.get("columns", []),
            # 20-row preview as-is — Phase 4.1 already capped it at 20
            # in the tool layer. Re-slicing here just hid more rows.
            # E2E hotfix: frontend reads ``rows`` consistently (both the
            # live SSE ``done`` event and history restore). Keep
            # ``sample_rows`` as an alias for any older clients still
            # reading the historical key.
            "rows": execution_result.get("rows", []),
            "sample_rows": execution_result.get("rows", []),
            "has_more": execution_result.get("row_count", 0)
            > len(execution_result.get("rows", [])),
            # Phase 4 cache plumbing — required for ResultsExpander
            # and the export endpoint to read from the cache.
            "rows_ref": execution_result.get("rows_ref"),
            "rows_cached": execution_result.get("rows_cached", False),
            "preview_row_count": execution_result.get("preview_row_count"),
            "rows_truncated": execution_result.get("rows_truncated", False),
            "rows_truncated_reason": execution_result.get("rows_truncated_reason"),
            # Phase 3a.3 aggregation flags — useful for chart hints + UI badges
            "aggregated": execution_result.get("aggregated", False),
            "grouping_columns": execution_result.get("grouping_columns", []),
            "aggregate_columns": execution_result.get("aggregate_columns", []),
        }

        # PHASE 2B: Extract quality metrics if available
        data_quality = None
        if execution_result.get("has_analysis"):
            quality_info = execution_result.get("quality", {})
            if quality_info:
                data_quality = {
                    "overall_score": quality_info.get("overall_score", 0),
                    "completeness": quality_info.get("completeness", 100),
                    "issues": quality_info.get("issues", [])[:3],  # Top 3 issues only
                }
                logger.info(f"Extracted data quality: score={data_quality['overall_score']}, completeness={data_quality['completeness']}%")

        return ChatResponse(
            success=True,
            mode=ChatMode.ANALYST,
            sql=sql,
            is_valid=True,
            query_type=_detect_query_type(sql),
            answer=data_summary,  # Use data-driven summary for accuracy
            key_findings=key_findings,
            # Mission-critical wiring: the STRUCTURED insights list
            # (LLM business_insight + detector findings) now travels
            # to the frontend's InsightCard. Previously only the
            # flattened string ``key_findings`` reached the UI, so
            # the rich narrative (title / severity / recommendations /
            # metrics) was invisible. Empty list when no analysis ran.
            insights=execution_result.get("insights", []) if execution_result else [],
            # Surface narrator status so the empty-insights section
            # can render an honest fallback instead of a silent blank
            # strip.
            narrator_status=execution_result.get("narrator_status") if execution_result else None,
            insights_type=execution_result.get("insights_type") if execution_result else None,
            # Sampling metadata as its own field — keeps the insights
            # list pure of meta-commentary cards.
            sampling_used=execution_result.get("sampling_used") if execution_result else None,
            confidence=confidence,
            chart=chart_dict,
            raw_result=result_summary,  # Lightweight summary instead of full data
            reasoning=reasoning,
            data_quality=data_quality,  # PHASE 2B: Data quality assessment
            suggestions=suggestions_list,
            tools_used=tools_used,
            query_id=query_id,
            sql_hash=sql_hash,
            is_follow_up=is_follow_up,
            conversation_turn=conversation_turn,
        )

    except Exception as e:
        logger.error("Analyst mode failed", error=str(e), exc_info=True)
        return ChatResponse(
            success=False,
            mode=ChatMode.ANALYST,
            error=ErrorSanitizer.sanitize_error(e),
            tools_used=tools_used,
            query_id=query_id,
            is_follow_up=is_follow_up,
            conversation_turn=conversation_turn,
        )


# ============================================
# STREAMING HANDLER
# ============================================


def _format_sse(event: ChatStreamEvent) -> str:
    """Format event as SSE data line."""
    return f"data: {event.model_dump_json()}\n\n"


async def _stream_chat(
    session_id: str,
    session: dict,
    message: str,
    mode: ChatMode,
    llm_config: LLMConfig,
    db_config: DatabaseConfig,
    include_reasoning: bool,
    include_chart: bool,
    continue_conversation: bool = True,
) -> AsyncGenerator[str, None]:
    """Stream chat response with real-time progress events and conversation support."""
    query_id = _generate_query_id()

    # Reset conversation state on Fresh start
    if not continue_conversation:
        session_store.reset_conversation(session_id)
        session = session_store.get(session_id) or session

    # Build conversation context
    conversation_context = _build_conversation_context(session) if continue_conversation else None
    is_follow_up = _detect_follow_up(message, session.get("last_query_context")) if continue_conversation else False
    conversation_turn = len(session.get("context_window", [])) + 1

    try:
        yield _format_sse(ChatStreamEvent(event="thinking", content="Analyzing...", progress=0.1))

        if mode == ChatMode.ANALYST:
            # Create agent for real-time streaming
            agent = ReActAgent(
                llm_config=llm_config,
                db_config=db_config,
                session_id=session_id,
                max_iterations=10,
            )

            sql = None
            sql_hash = None
            tools_used = []
            agent_result = None
            execution_result = None

            # Stream agent events in real-time with conversation context
            async for event in agent.run_streaming(
                question=message,
                resume=is_follow_up and continue_conversation,
                conversation_context=conversation_context,
            ):
                event_type = event.get("event")

                if event_type == "thinking":
                    yield _format_sse(ChatStreamEvent(
                        event="thinking",
                        content=event.get("content", "Processing..."),
                        progress=event.get("progress", 0.2),
                    ))

                elif event_type == "tool_call":
                    tool_name = event.get("tool_name")
                    if tool_name and tool_name not in tools_used:
                        tools_used.append(tool_name)
                    # Include CLI-style fields at top level for frontend
                    yield _format_sse(ChatStreamEvent(
                        event="tool_call",
                        tool_name=tool_name,
                        tool_args=event.get("tool_args"),
                        progress=event.get("progress", 0.3),
                        step_number=event.get("step_number"),
                        description=event.get("description"),
                    ))

                elif event_type == "tool_result":
                    # Include CLI-style summary at top level for frontend
                    yield _format_sse(ChatStreamEvent(
                        event="tool_result",
                        tool_name=event.get("tool_name"),
                        content=event.get("content"),
                        progress=event.get("progress", 0.4),
                        summary=event.get("summary"),
                    ))

                elif event_type == "sql_generated":
                    sql = event.get("sql")
                    if sql:
                        # Don't generate hash yet - wait until we register at the end
                        yield _format_sse(ChatStreamEvent(
                            event="sql",
                            content=sql,
                            progress=0.6,
                        ))

                elif event_type == "executing":
                    yield _format_sse(ChatStreamEvent(
                        event="executing",
                        content=event.get("content", "Executing SQL..."),
                        progress=0.7,
                    ))

                elif event_type == "complete":
                    agent_result = event.get("result", {})

                elif event_type == "error":
                    yield _format_sse(ChatStreamEvent(
                        event="error",
                        content=event.get("error", "Agent failed"),
                    ))
                    return

            # Handle agent completion
            if not agent_result:
                yield _format_sse(ChatStreamEvent(event="error", content="Agent did not complete"))
                return

            if not agent_result.get("success"):
                yield _format_sse(ChatStreamEvent(event="error", content=agent_result.get("error", "Failed")))
                return

            # Get SQL from agent result if not already captured
            if not sql:
                sql = agent_result.get("sql")
                if sql:
                    yield _format_sse(ChatStreamEvent(event="sql", content=sql, progress=0.6))

            # Check if agent provided a text response without SQL (e.g., refusal, explanation)
            agent_message = agent_result.get("agent_message") or agent_result.get("data_summary")

            if not sql:
                # No SQL generated - check if agent provided an explanation
                if agent_message and not agent_result.get("execution_result"):
                    # Agent provided a direct text response (refusal, explanation, etc.)
                    # Return this as a successful completion
                    yield _format_sse(ChatStreamEvent(
                        event="done",
                        content=agent_message,
                        progress=1.0,
                        data={
                            "query_id": query_id,
                            "mode": "analyst",
                            "answer": agent_message,
                            "sql": None,
                            "is_agent_message": True,  # Flag to indicate this is agent communication
                            "tools_used": agent_result.get("tools_used", []),
                            "total_steps": agent_result.get("total_steps", 0),
                        }
                    ))
                    return
                else:
                    # No SQL and no agent message - this is an error
                    yield _format_sse(ChatStreamEvent(event="error", content="No SQL generated"))
                    return

            # Get execution result from agent (now contains structured data)
            execution_result = agent_result.get("execution_result")
            used_agent_execution = bool(execution_result and execution_result.get("success"))

            if not used_agent_execution:
                # Agent didn't execute successfully, run query ourselves
                yield _format_sse(ChatStreamEvent(event="executing", content="Running query...", progress=0.7))
                try:
                    # Use force_refresh to ensure fresh data matches what agent reported
                    exec_result = await DatabaseService.execute_query(db_config, sql, limit=500, force_refresh=True)
                    execution_result = {
                        "columns": exec_result.get("columns", []),
                        "rows": exec_result.get("rows", []),
                        "row_count": exec_result.get("row_count", 0),
                        "success": True,
                    }
                except Exception as e:
                    logger.error("SQL execution failed in stream fallback", error=str(e), exc_info=True)
                    yield _format_sse(ChatStreamEvent(
                        event="error",
                        content=f"SQL execution failed: {ErrorSanitizer.sanitize_error(e)}",
                    ))
                    return
            # Agent's execution_result already has structured data (columns, rows, row_count)

            row_count = execution_result.get('row_count', 0)
            rows_len = len(execution_result.get('rows', []))
            logger.info(f"Streaming: execution_result row_count={row_count}, actual_rows={rows_len}, success={execution_result.get('success')}")
            yield _format_sse(ChatStreamEvent(event="result", content=f"Found {row_count} rows", progress=0.75))

            # Generate data-driven summary from ACTUAL execution results
            # Always regenerate to ensure it matches the data we're showing
            data_summary = generate_data_summary(message, execution_result)

            # Use the generated data-driven summary
            answer_text = data_summary

            # Check if we have pre-computed analysis from execute_and_analyze
            has_analysis = execution_result.get("has_analysis", False)

            if has_analysis:
                # Use pre-computed data (skip expensive AnswerGenerator call)
                logger.info("Streaming: Using pre-computed analysis from execute_and_analyze")

                # Single source of truth for the insights→key_findings
                # flattening; same helper on the non-streaming path.
                key_findings = _flatten_insights_to_key_findings(
                    execution_result.get("insights", [])
                )

                # Extract pre-computed chart
                chart_raw = execution_result.get("chart")
                chart_dict = None
                if chart_raw and include_chart:
                    # Ensure proper format for frontend
                    chart_dict = {
                        "chart_type": chart_raw.get("recommended_chart", chart_raw.get("chart_type", "bar")),
                        "title": chart_raw.get("title", "Analysis"),
                        "x_axis": chart_raw.get("config", {}).get("x_axis", "") or chart_raw.get("x_axis", ""),
                        "y_axis": chart_raw.get("config", {}).get("y_axis", "") or chart_raw.get("y_axis", ""),
                        "x_label": chart_raw.get("config", {}).get("x_label", "") or chart_raw.get("x_label", ""),
                        "y_label": chart_raw.get("config", {}).get("y_label", "") or chart_raw.get("y_label", ""),
                        "data": chart_raw.get("data", []),
                    }

                # Confidence from quality score
                quality_score = execution_result.get("quality", {}).get("overall_score", 95)
                confidence = min(0.95, quality_score / 100)

            else:
                # Original path: No pre-computed analysis, set defaults and optionally call AnswerGenerator
                key_findings = []
                confidence = 0.9 if row_count > 0 else 0.5
                chart_dict = None

            # Optionally generate LLM insights for richer analysis (only if no pre-computed analysis)
            if not has_analysis and (include_reasoning or include_chart):
                yield _format_sse(ChatStreamEvent(event="analyzing", content="Generating insights...", progress=0.8))
                try:
                    answer_result = await AnswerGenerator.generate(
                        llm_config=llm_config,
                        question=message,
                        sql=sql,
                        result=execution_result,
                        db_type=db_config.db_type,
                        include_reasoning=include_reasoning,
                    )
                    # Use LLM key findings but keep data-driven answer for accuracy
                    key_findings = answer_result.key_findings
                    confidence = answer_result.confidence

                    if include_chart and answer_result.chart:
                        chart_dict = {
                            "chart_type": answer_result.chart.chart_type.value,
                            "title": answer_result.chart.title,
                            "x_axis": answer_result.chart.x_axis,
                            "y_axis": answer_result.chart.y_axis,
                            "x_label": answer_result.chart.x_label,
                            "y_label": answer_result.chart.y_label,
                            "data": answer_result.chart.data,
                        }
                except Exception as e:
                    logger.warning(f"LLM insights generation failed: {e}")

            # Update tools_used from agent result if we missed any
            tools_used = agent_result.get("tools_used", tools_used)
            total_steps = agent_result.get("total_steps", len(tools_used))

            # Extract follow-up suggestions from agent result
            suggestions_list = agent_result.get("suggestions")

            # Register SQL and get the correct HMAC hash for security verification
            sql_hash = sql_integrity.register_sql(session_id, query_id, sql)

            # Build raw_result_summary for persistence — Phase 4 wiring fix.
            # Same as the non-streaming path: don't re-truncate the
            # 20-row preview, AND carry rows_ref / cache state so
            # restored history can fetch full rows from the cache.
            raw_result_summary = {
                "columns": execution_result.get("columns", [])[:20],  # Max 20 columns
                "row_count": execution_result.get("row_count", 0),
                # E2E hotfix: frontend reads ``rows`` consistently (both the
            # live SSE ``done`` event and history restore). Keep
            # ``sample_rows`` as an alias for any older clients still
            # reading the historical key.
            "rows": execution_result.get("rows", []),
            "sample_rows": execution_result.get("rows", []),
                "rows_ref": execution_result.get("rows_ref"),
                "rows_cached": execution_result.get("rows_cached", False),
                "preview_row_count": execution_result.get("preview_row_count"),
                "rows_truncated": execution_result.get("rows_truncated", False),
                "rows_truncated_reason": execution_result.get("rows_truncated_reason"),
            }

            # Get connection hash for PostgreSQL persistence
            connection_hash = vector_db._hash_connection(db_config.connection_url)

            # Add to session history with full analyst data
            base_entry = {
                "query": message,
                "sql": sql,
                "sql_hash": sql_hash,
                "mode": "analyst",
                "success": True,
            }

            session_store.add_history(
                session_id,
                base_entry,
                answer=answer_text,
                key_findings=key_findings,
                confidence=confidence,
                chart_spec=chart_dict,
                raw_result_summary=raw_result_summary,
                tools_used=tools_used,
                agent_steps=None,  # Could be extracted from streaming events if needed
                is_follow_up=is_follow_up,
                conversation_turn=conversation_turn,
            )

            # Persist to PostgreSQL for cross-session restore
            await query_history_service.save_query(
                query_id=query_id,
                connection_hash=connection_hash,
                db_type=db_config.db_type,
                natural_query=message,
                sql=sql,
                sql_hash=sql_hash,
                mode="analyst",
                answer=answer_text,
                key_findings=key_findings,
                confidence=confidence,
                chart_spec=chart_dict,
                raw_result_summary=raw_result_summary,
                tools_used=tools_used,
                agent_steps=None,
                is_follow_up=is_follow_up,
                conversation_turn=conversation_turn,
                session_id=session_id,
            )

            # Cache result for conversation reference.
            # Phase 4.2 wiring: include rows_ref so get_previous_result
            # can hand it back to the LLM for inspect_cached_result /
            # get_cached_rows follow-ups (full 9000-row drill-down
            # instead of the 10-row sample baked into this cache).
            session_store.cache_query_result(
                session_id,
                query_id,
                {
                    "columns": execution_result.get("columns", []),
                    "rows": execution_result.get("rows", []),
                    "row_count": execution_result.get("row_count", 0),
                    "sql": sql,
                    "rows_ref": execution_result.get("rows_ref"),
                },
            )

            # Update last_query_context for follow-up detection
            session_store.update(
                session_id,
                {
                    "last_query_context": {
                        "query_id": query_id,
                        "question": message,
                        "sql": sql,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                },
            )

            # Create lightweight result summary — Phase 4 wiring fix.
            # Carry rows_ref + cache state so the frontend's
            # ResultsExpander can fetch the full set from
            # /api/v1/results/{rows_ref}; carry the 20-row preview as-is
            # rather than re-truncating to 5.
            result_summary = {
                "row_count": execution_result.get("row_count", 0),
                "columns": execution_result.get("columns", []),
                # E2E hotfix: frontend reads ``rows`` consistently (both the
            # live SSE ``done`` event and history restore). Keep
            # ``sample_rows`` as an alias for any older clients still
            # reading the historical key.
            "rows": execution_result.get("rows", []),
            "sample_rows": execution_result.get("rows", []),
                "has_more": execution_result.get("row_count", 0)
                > len(execution_result.get("rows", [])),
                "rows_ref": execution_result.get("rows_ref"),
                "rows_cached": execution_result.get("rows_cached", False),
                "preview_row_count": execution_result.get("preview_row_count"),
                "rows_truncated": execution_result.get("rows_truncated", False),
                "rows_truncated_reason": execution_result.get("rows_truncated_reason"),
                "aggregated": execution_result.get("aggregated", False),
                "grouping_columns": execution_result.get("grouping_columns", []),
                "aggregate_columns": execution_result.get("aggregate_columns", []),
            }

            # PHASE 2B: Extract quality metrics if available
            data_quality = None
            if execution_result.get("has_analysis"):
                quality_info = execution_result.get("quality", {})
                if quality_info:
                    data_quality = {
                        "overall_score": quality_info.get("overall_score", 0),
                        "completeness": quality_info.get("completeness", 100),
                        "issues": quality_info.get("issues", [])[:3],  # Top 3 issues only
                    }
                    logger.info(f"Streaming: Extracted data quality: score={data_quality['overall_score']}, completeness={data_quality['completeness']}%")

            yield _format_sse(ChatStreamEvent(event="done", content=answer_text, progress=1.0, data={
                "query_id": query_id, "sql_hash": sql_hash, "mode": "analyst",
                "answer": answer_text, "key_findings": key_findings,
                # Mission-critical wiring: structured insights (LLM
                # narrative + detector findings) travel to the
                # frontend's InsightCard. Without this the rich LLM
                # output gets stripped to plain string key_findings
                # and the beautiful cards stay empty.
                "insights": execution_result.get("insights", []) if execution_result else [],
                # Narrator observability — same shape as the non-
                # streaming path so the streaming UI can also show an
                # honest fallback when insights is empty.
                "narrator_status": execution_result.get("narrator_status") if execution_result else None,
                "insights_type": execution_result.get("insights_type") if execution_result else None,
                # Sampling metadata as its own field.
                "sampling_used": execution_result.get("sampling_used") if execution_result else None,
                "confidence": confidence, "chart": chart_dict, "sql": sql,
                "raw_result": result_summary,  # Lightweight summary (full data fetched on-demand)
                "data_quality": data_quality,  # PHASE 2B: Data quality assessment
                "suggestions": suggestions_list,
                "tools_used": tools_used,
                "total_steps": total_steps,
                "is_follow_up": is_follow_up,
                "conversation_turn": conversation_turn,
            }))

        else:
            # Standard mode with true SQL streaming
            ctx, error_result = await SQLGenerationService.prepare_context(
                session_id, session, message, continue_conversation=continue_conversation
            )
            if error_result:
                yield _format_sse(ChatStreamEvent(event="error", content=error_result.error))
                return

            # At this point, ctx is guaranteed to be non-None
            assert ctx is not None, "Context must be non-None when error_result is None"

            yield _format_sse(ChatStreamEvent(event="thinking", content="Generating SQL...", progress=0.1))

            # Fetch few-shot examples (non-blocking for streaming)
            few_shot_examples = []
            try:
                few_shot_examples = vector_db.find_similar_queries(
                    ctx.db_config.connection_url, ctx.sanitized_query, n=3
                )
            except Exception as e:
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

            # Stream SQL chunks
            chunks = []
            try:
                # Use analyst timeout for analyst mode
                timeout_seconds = (
                    settings.effective_analyst_timeout
                    if mode == ChatMode.ANALYST
                    else settings.AGENT_TIMEOUT_SECONDS
                )
                async with asyncio.timeout(timeout_seconds):
                    async for chunk in sql_generator:
                        chunks.append(chunk)
                        # Yield sql_chunk event for progressive display
                        yield _format_sse(ChatStreamEvent(
                            event="sql_chunk",
                            content=chunk,
                            progress=min(0.2 + len(chunks) * 0.01, 0.7)
                        ))
            except asyncio.TimeoutError:
                logger.warning("Streaming SQL generation timed out", session_id=session_id[:8])
                yield _format_sse(ChatStreamEvent(event="error", content="SQL generation timed out"))
                return

            full_sql = "".join(chunks)

            # Clean and validate SQL
            prompt_provider = get_prompt_provider(ctx.db_config.db_type)
            cleaned_sql = prompt_provider.clean_response(full_sql)

            is_valid, validation_msg = SecurityService.validate_generated_sql(
                cleaned_sql, ctx.db_config.db_type
            )

            if not is_valid:
                logger.warning("Streaming SQL validation failed", reason=validation_msg)
                yield _format_sse(ChatStreamEvent(event="error", content=f"Invalid SQL: {validation_msg}"))
                return

            # Register in history
            connection_hash = vector_db._hash_connection(ctx.db_config.connection_url)
            history_entry = {
                "query": ctx.natural_language,
                "sanitized_query": ctx.sanitized_query,
                "sql": cleaned_sql,
                "db_type": ctx.db_config.db_type,
                "connection_id": connection_hash,
            }
            entry_id = session_store.add_history(session_id, history_entry)

            # Register SQL integrity
            sql_hash = sql_integrity.register_sql(session_id, entry_id, cleaned_sql)
            session_store.update_history_entry(session_id, entry_id, {"sql_hash": sql_hash})

            # Persist to PostgreSQL with conversation fields
            await query_history_service.save_query(
                query_id=entry_id,
                connection_hash=connection_hash,
                db_type=ctx.db_config.db_type,
                natural_query=ctx.natural_language,
                sql=cleaned_sql,
                sanitized_query=ctx.sanitized_query,
                sql_hash=sql_hash,
                # Conversation fields for full persistence
                mode="standard",
                is_follow_up=ctx.is_follow_up,
                conversation_turn=conversation_turn,
                session_id=session_id,
            )

            # Store for learning
            vector_db.store_successful_query(
                ctx.db_config.connection_url, ctx.sanitized_query, cleaned_sql
            )

            # Update last_query_context for follow-up detection
            session_store.update(
                session_id,
                {
                    "last_query_context": {
                        "query_id": entry_id,
                        "question": message,
                        "sql": cleaned_sql,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                },
            )

            # Yield validated SQL and done event
            yield _format_sse(ChatStreamEvent(
                event="sql_complete",
                content=cleaned_sql,
                progress=0.9
            ))
            yield _format_sse(ChatStreamEvent(
                event="done",
                content="Complete",
                progress=1.0,
                data={
                    "query_id": entry_id,
                    "sql_hash": sql_hash,
                    "mode": "standard",
                    "sql": cleaned_sql,
                    "is_follow_up": ctx.is_follow_up,
                    "conversation_turn": conversation_turn,
                }
            ))

    except Exception as e:
        logger.error("Stream chat failed", error=str(e))
        yield _format_sse(ChatStreamEvent(event="error", content=ErrorSanitizer.sanitize_error(e)))


# ============================================
# API ENDPOINT
# ============================================


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: ERROR_RESPONSES[400],
        404: ERROR_RESPONSES[404],
        429: ERROR_RESPONSES[429],
        500: ERROR_RESPONSES[500],
    },
    summary="Unified Chat Endpoint",
    description="Primary endpoint for all query interactions. Supports both SQL generation and AI analyst modes.",
)
async def chat(
    request: ChatRequest,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
):
    """
    Unified chat endpoint for all query interactions.

    This is the primary endpoint for interacting with the NL2SQL system.
    It replaces the older /query/generate endpoint with a unified interface.

    **Modes:**
    - **standard**: Fast SQL generation (single LLM call, optimized for speed)
    - **analyst**: Insight-rich answers with SQL, charts, key findings, and confidence scores

    **Streaming:**
    Set `stream=true` for Server-Sent Events (SSE) streaming. Event types:
    - `thinking`: Processing status updates
    - `sql_chunk`: Progressive SQL tokens (standard mode)
    - `sql_complete`: Final validated SQL
    - `tool_result`: Tool execution results (analyst mode)
    - `executing`: Query execution status (analyst mode)
    - `analyzing`: Analysis in progress (analyst mode)
    - `done`: Final response with all data
    - `error`: Error occurred

    **Returns:**
    - `sql`: Generated SQL query
    - `query_id`: Unique identifier for this query
    - `sql_hash`: Integrity hash for the SQL
    - Additional fields in analyst mode: `answer`, `key_findings`, `confidence`, `chart`
    """
    session = validate_request(
        request.session_id,
        csrf_token,
        rate_limit_action="generate",
        require_schema_ready=True,
    )

    # Validate query length before any processing
    if len(request.message) > settings.MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Query exceeds maximum length of {settings.MAX_QUERY_LENGTH} characters",
        )

    llm_config = _get_llm_config(session)
    db_config = _get_db_config(session)

    # Streaming mode
    if request.stream:
        return StreamingResponse(
            _stream_chat(
                session_id=request.session_id,
                session=session,
                message=request.message,
                mode=request.mode,
                llm_config=llm_config,
                db_config=db_config,
                include_reasoning=request.include_reasoning,
                include_chart=request.include_chart,
                continue_conversation=request.continue_conversation,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # Non-streaming mode
    if request.mode == ChatMode.ANALYST:
        return await _handle_analyst_mode(
            session_id=request.session_id,
            session=session,
            message=request.message,
            llm_config=llm_config,
            db_config=db_config,
            include_reasoning=request.include_reasoning,
            include_chart=request.include_chart,
            continue_conversation=request.continue_conversation,
        )
    else:
        return await _handle_standard_mode(
            session_id=request.session_id,
            session=session,
            message=request.message,
            llm_config=llm_config,
            db_config=db_config,
            continue_conversation=request.continue_conversation,
        )
