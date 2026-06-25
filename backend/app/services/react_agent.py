"""
QueryfyAI - ReAct Agent for Analyst Mode (LangGraph + LiteLLM)

Uses LangGraph's built-in tool support with LiteLLM for provider-agnostic tool calling.

Architecture:
- LangGraph StateGraph for agent orchestration
- LiteLLM for LLM calls with tool binding
- ToolRegistry for tool execution

Flow:
1. LLM receives question and bound tools
2. LLM decides which tools to call
3. Tools execute and return results
4. LLM processes results and decides next action
5. Repeat until SQL is generated
6. Execute SQL and return results
"""

import asyncio
import copy
import json
import operator
import time
from typing import (
    Annotated,
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    TypedDict,
    Union,
)

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.core.logging_config import get_logger
from app.models.schemas import DatabaseConfig, LLMConfig
from app.services.checkpointer import (
    generate_thread_id,
    get_checkpoint_config,
    get_checkpointer,
    get_checkpointer_backend,
)
from app.services.distributed_lock import DistributedLock
from app.services.llm_service import (
    LLMUsageData,
    ToolCall,  # For type clarity - used via response.tool_calls
    ToolCallingService,
)
from app.services.message_truncator import (
    MessageTruncator,
    TruncationStats,  # noqa: F401 - Used via truncator.truncate() return type
)
from app.services.session_store import session_store
from app.services.tools.analysis_tools import _generate_followups
from app.services.tools.registry import ToolContext, ToolRegistry

logger = get_logger(__name__)


def _extract_first_table_from_sql(sql: str) -> Optional[Tuple[Optional[str], str]]:
    """
    Best-effort extraction of the first table reference in a SQL /
    Cassandra CQL / DynamoDB PartiQL / MongoDB shell query string.
    Returns ``(schema_name_or_None, table_name)`` or ``None`` if the
    query has no recognizable FROM/JOIN/INTO/UPDATE / ``db.<coll>``
    reference.

    Delegates to the shared multi-dialect parser in ``query_tools``
    and returns its first result. The single-table flavour exists
    so error-recovery hooks that just need *some* affected table
    don't have to deal with the full list.
    """
    if not sql:
        return None
    # Local import — query_tools doesn't import from react_agent, so
    # the one-way call-time import is safe and avoids any module-load
    # ordering surprise.
    from app.services.tools.query_tools import _extract_tables_from_sql

    refs = _extract_tables_from_sql(sql)
    return refs[0] if refs else None


def _maybe_schedule_schema_refresh_on_column_error(
    error_info: dict,
    tool_args: dict,
    tool_context: Any,
) -> None:
    """
    Fire-and-forget single-table schema refresh on a COLUMN_NOT_FOUND
    classification — schema can drift between full re-extraction
    runs (DDL on the live DB), so the next iteration's
    ``get_table_schema`` should see a fresh indexed copy without
    blocking the current turn.

    Best-effort and silent: skips when the feature flag is off, the
    SQL has no parseable table, ``db_config`` is missing, or the
    underlying refresh raises (its own logging covers that). Never
    raises; never awaits.
    """
    if not getattr(settings, "SCHEMA_AUTO_REFRESH_ON_COLUMN_NOT_FOUND", True):
        return
    if (error_info or {}).get("error_type") != "COLUMN_NOT_FOUND":
        return
    sql = (tool_args or {}).get("sql")
    if not sql:
        return
    db_config = getattr(tool_context, "db_config", None)
    if not db_config:
        return

    parsed = _extract_first_table_from_sql(sql)
    if parsed is None:
        logger.debug(
            "schema_refresh.skipped",
            extra={"reason": "could_not_parse_table_from_sql"},
        )
        return
    schema_name, table_name = parsed

    try:
        from app.models.schemas import DatabaseConfig as _DBConfig
        from app.services.schema_refresh import refresh_table_schema

        _resolved_db_config = (
            _DBConfig(**db_config)
            if isinstance(db_config, dict)
            else db_config
        )
        # Fire-and-forget — the agent loop continues without awaiting.
        # asyncio.create_task captures the coroutine into the running
        # loop; on completion, errors land on the loop's exception
        # handler (already wired via the project's logging config).
        asyncio.create_task(
            refresh_table_schema(
                db_config=_resolved_db_config,
                schema_name=schema_name,
                table_name=table_name,
                reason="column_not_found",
            )
        )
        logger.info(
            "schema_refresh.scheduled_on_column_not_found",
            extra={
                "schema_name": schema_name or "",
                "table_name": table_name,
            },
        )
    except Exception as e:
        # If we can't even schedule the task, the recovery hint in
        # the COLUMN_NOT_FOUND message still fires — user gets the
        # manual recovery path. Don't break tool_node on this.
        logger.warning(
            "schema_refresh.schedule_failed: %s", e
        )


class AgentStatus:
    """Valid status values for ReActState"""
    THINKING = "thinking"
    READY = "ready"
    COMPLETE = "complete"
    ERROR = "error"

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        return status in (cls.COMPLETE, cls.ERROR, cls.READY)


TOOL_EXECUTION_TIMEOUT = getattr(settings, 'AGENT_TOOL_TIMEOUT', 30.0)

# Phase 1 Day 4 (legacy): data-lake / warehouse query engines routinely
# need minutes for non-trivial queries. A 30-second global timeout kills
# them client-side while the query keeps running (and billing) on the
# server. The frozenset below marks the db_types where the legacy
# Phase 1 code extended the timeout to at least 5 minutes. Kept for the
# rollback branch of _effective_tool_timeout (flag off).
DATA_LAKE_DB_TYPES: frozenset = frozenset({
    "athena",
    "bigquery",
    "clickhouse",
    "databricks",
    "hive",
    "presto",
    "redshift",
    "snowflake",
    "spark",
    "trino",
})

# Phase 3a Day 1: explicit per-DB tool-execution timeout map. Each entry
# reflects the typical query-duration profile of that engine in the wild
# — BigQuery/Hive/Spark analytical queries commonly need >5 min; Athena
# and ClickHouse are usually faster; transactional stores stay at 30s.
# Values are in SECONDS. ``AGENT_TOOL_TIMEOUT`` (operator-configurable,
# default 30s) acts as a floor: if an operator deliberately raises it,
# we won't shrink below that floor.
TOOL_TIMEOUT_BY_DB: Dict[str, float] = {
    # Transactional / OLTP — fast queries expected
    "postgresql": 30.0,
    "mysql": 30.0,
    "sqlite": 30.0,
    "sqlserver": 30.0,
    "oracle": 30.0,
    "duckdb": 30.0,
    # NoSQL / key-value — fast, single-doc/row operations
    "mongodb": 30.0,
    "cassandra": 30.0,
    "dynamodb": 30.0,
    # Analytical engines — usually fast, can spike for JOINs
    "athena": 180.0,
    "clickhouse": 180.0,
    # Distributed SQL engines — real analytical workloads
    "trino": 300.0,
    "presto": 300.0,
    "redshift": 300.0,
    "snowflake": 300.0,
    "databricks": 300.0,
    # Big analytical reads — multi-minute norms
    "bigquery": 600.0,
    "hive": 600.0,
    "spark": 600.0,
}

# Minimum timeout for data-lake tool executions (seconds). Applied when
# the configured timeout is shorter. Used only on the legacy (Phase 1
# Day 4) code path when the Phase 3a per-DB map is disabled.
_DATA_LAKE_MIN_TIMEOUT = 300.0


def _effective_tool_timeout(db_type: Optional[str]) -> float:
    """
    Return the tool execution timeout appropriate for the target database.

    Phase 3a Day 1 (``FIX_DB_SPECIFIC_TIMEOUTS`` on):
        Uses the explicit ``TOOL_TIMEOUT_BY_DB`` map; each engine gets a
        timeout tuned to its typical query-duration profile. The legacy
        ``AGENT_TOOL_TIMEOUT`` acts as a floor — operators who raise the
        global default still get the override. Unknown db_types fall back
        to the global default.

    Phase 1 Day 4 (``FIX_DB_SPECIFIC_TIMEOUTS`` off, ``FIX_DATA_LAKE_TIMEOUT`` on):
        Binary split — transactional 30s, data-lake 300s. Kept as the
        emergency rollback branch.

    Both flags off: returns the raw ``AGENT_TOOL_TIMEOUT``.

    Records a ``data_lake_timeout`` fix event whenever the effective
    timeout ends up longer than the global default (i.e. one of the
    Phase 3a/1 remediations actually contributed), so the diagnostic
    endpoint can show the feature is live.
    """
    base = float(TOOL_EXECUTION_TIMEOUT)
    db_key = db_type.lower() if db_type else None

    # Phase 3a per-DB map
    if settings.FIX_DB_SPECIFIC_TIMEOUTS:
        mapped = TOOL_TIMEOUT_BY_DB.get(db_key) if db_key else None
        if mapped is None:
            return base
        effective = max(mapped, base)
        if effective > base:
            try:
                from app.api.metrics import record_fix_event
                record_fix_event("data_lake_timeout")
            except Exception:
                pass
        return effective

    # Phase 1 Day 4 fallback — binary split.
    # (Flag amnesty 2026-05-12: FIX_DATA_LAKE_TIMEOUT rollback path removed.)
    if db_key and db_key in DATA_LAKE_DB_TYPES and base < _DATA_LAKE_MIN_TIMEOUT:
        try:
            from app.api.metrics import record_fix_event
            record_fix_event("data_lake_timeout")
        except Exception:
            pass
        return _DATA_LAKE_MIN_TIMEOUT
    return base


def _db_type_from_context(tool_context: Any) -> Optional[str]:
    """
    Pull the db_type out of a ``ToolContext`` in a shape-agnostic way.
    ``db_config`` may be a ``DatabaseConfig`` object or a plain dict.
    """
    if not tool_context:
        return None
    db_config = getattr(tool_context, "db_config", None)
    if db_config is None:
        return None
    if isinstance(db_config, dict):
        return db_config.get("db_type")
    return getattr(db_config, "db_type", None)


def is_anthropic_model(model: str) -> bool:
    """
    Detect if the model is an Anthropic model.

    Anthropic models include:
    - Direct Anthropic API: claude-*
    - AWS Bedrock: anthropic.claude-*
    - OAuth Gateway with Bedrock: anthropic.claude-*
    """
    if not model:
        return False
    model_lower = model.lower()
    return (
        model_lower.startswith("claude-") or
        model_lower.startswith("anthropic.claude-") or
        "claude" in model_lower
    )


# ============================================================================
# STATE DEFINITION
# ============================================================================


class ReActState(TypedDict):
    """State for the ReAct agent."""

    # Conversation messages
    messages: Annotated[List[BaseMessage], operator.add]

    # User's original question
    question: str

    # Generated SQL (when ready)
    sql: Optional[str]

    # Execution result
    execution_result: Optional[Dict[str, Any]]

    # Tool tracking
    tools_used: List[str]
    tool_calls_count: int

    # Failed attempts tracking (for error recovery learning)
    failed_attempts: List[Dict[str, Any]]

    # LLM usage
    total_usage: Optional[Dict[str, Any]]

    # Status
    status: str  # "thinking", "ready", "complete", "error"
    error: Optional[str]

    # Iteration tracking
    iteration: int
    max_iterations: int

    # Loop prevention: consecutive responses without tool calls
    consecutive_no_tools: int
    consecutive_failures: int
    # Iterations where the agent called non-SQL tools only. Reset whenever
    # execute_sql or execute_and_analyze is invoked (success OR failure).
    # Circuit breaker trips at >= 10 (Phase 2) / >= 7 (Phase 1 legacy).
    iterations_without_execution: int
    # Phase 2 Day 1: count of execute_sql / execute_and_analyze attempts that
    # returned success=False. Independent of consecutive_failures (which
    # counts any tool failure). Reset on a successful SQL execution. Circuit
    # breaker trips at >= 3.
    sql_attempts_failed: int

    # Wall-clock budget for the agent run. ``max_iterations`` (10)
    # plus per-tool timeouts (30 s default, up to 5 min for data
    # lakes) gives a 50-minute worst-case for runaway runs.
    # ``wall_clock_start`` is set on initial state via
    # ``time.monotonic()``; ``should_continue`` compares against
    # ``wall_clock_budget_seconds`` and returns "end" when exceeded.
    # 0 disables.
    wall_clock_start: float
    wall_clock_budget_seconds: float


# ============================================================================
# LANGGRAPH-COMPATIBLE TOOL WRAPPERS
# ============================================================================


def create_langchain_tools(tool_context: ToolContext) -> List:
    """
    Create LangChain-compatible tools from our ToolRegistry.

    These tools can be used with LangGraph's ToolNode.
    Uses detailed descriptions from definitions.py for better LLM guidance.
    """
    from langchain_core.tools import StructuredTool

    from app.services.tools.analysis_definitions import (
        ANALYZE_STATISTICS,
        ANNOTATE_CHART,
        CHECK_DATA_QUALITY,
        COMPARE_PERIODS,
        DETECT_INSIGHTS,
        PREPARE_CHART_DATA,
        RECOMMEND_CHART,
        SUGGEST_FOLLOWUPS,
    )
    from app.services.tools.definitions import (
        EXECUTE_AND_ANALYZE,
        EXECUTE_SQL,
        FIND_SIMILAR_QUERIES,
        GET_PREVIOUS_RESULT,
        GET_SAMPLE_DATA,
        GET_TABLE_SCHEMA,
        LOOKUP_BUSINESS_TERM,
        SEARCH_TABLES,
    )

    tools = []

    # search_tables
    async def _search_tables(query: str, max_results: int = 5) -> str:
        """Search for database tables relevant to a query."""
        return await ToolRegistry.execute(
            "search_tables", tool_context, query=query, max_results=max_results
        )

    tools.append(StructuredTool.from_function(
        coroutine=_search_tables,
        name="search_tables",
        description=SEARCH_TABLES.description,
    ))

    # get_table_schema
    async def _get_table_schema(table_name: str, include_sample_values: bool = False) -> str:
        """Get detailed schema for a specific table."""
        return await ToolRegistry.execute(
            "get_table_schema", tool_context,
            table_name=table_name, include_sample_values=include_sample_values
        )

    tools.append(StructuredTool.from_function(
        coroutine=_get_table_schema,
        name="get_table_schema",
        description=GET_TABLE_SCHEMA.description,
    ))

    # lookup_business_term
    async def _lookup_business_term(term: str) -> str:
        """Look up a business term's definition and SQL expression."""
        return await ToolRegistry.execute(
            "lookup_business_term", tool_context, term=term
        )

    tools.append(StructuredTool.from_function(
        coroutine=_lookup_business_term,
        name="lookup_business_term",
        description=LOOKUP_BUSINESS_TERM.description,
    ))

    # find_similar_queries
    async def _find_similar_queries(query: str, limit: int = 3) -> str:
        """Find previously successful queries similar to the current question."""
        return await ToolRegistry.execute(
            "find_similar_queries", tool_context, query=query, limit=limit
        )

    tools.append(StructuredTool.from_function(
        coroutine=_find_similar_queries,
        name="find_similar_queries",
        description=FIND_SIMILAR_QUERIES.description,
    ))

    # get_sample_data
    async def _get_sample_data(table_name: str, limit: int = 5) -> str:
        """Get sample rows from a table to understand data format."""
        return await ToolRegistry.execute(
            "get_sample_data", tool_context, table_name=table_name, limit=limit
        )

    tools.append(StructuredTool.from_function(
        coroutine=_get_sample_data,
        name="get_sample_data",
        description=GET_SAMPLE_DATA.description,
    ))

    # execute_sql
    async def _execute_sql(sql: str, limit: Optional[int] = None) -> str:
        """Execute a SQL query and return results (defaults to AGENT_QUERY_LIMIT_DEFAULT, max AGENT_QUERY_LIMIT_MAX)."""
        return await ToolRegistry.execute(
            "execute_sql", tool_context, sql=sql, limit=limit
        )

    tools.append(StructuredTool.from_function(
        coroutine=_execute_sql,
        name="execute_sql",
        description=EXECUTE_SQL.description,
    ))

    # execute_and_analyze (PRIMARY for analyst mode).
    # ``question`` is a NEW optional parameter threaded through to the
    # LLM narration step. The system prompt tells the model to always
    # pass the user's original NL question so business insights are
    # grounded in what they actually asked — without it the narrator
    # writes generic stat descriptions.
    async def _execute_and_analyze(
        sql: str,
        limit: Optional[int] = None,
        question: Optional[str] = None,
    ) -> str:
        """Execute SQL query and analyze complete result set (default 1000 rows, max 10000).

        Pass ``question`` verbatim — the user's original NL ask. It
        anchors the LLM narrator.
        """
        return await ToolRegistry.execute(
            "execute_and_analyze",
            tool_context,
            sql=sql,
            limit=limit,
            question=question,
        )

    tools.append(StructuredTool.from_function(
        coroutine=_execute_and_analyze,
        name="execute_and_analyze",
        description=EXECUTE_AND_ANALYZE.description,
    ))

    # get_previous_result (conversation context)
    async def _get_previous_result(query_reference: str = "last") -> str:
        """Retrieve result data from a previous query in this conversation."""
        return await ToolRegistry.execute(
            "get_previous_result", tool_context, query_reference=query_reference
        )

    tools.append(StructuredTool.from_function(
        coroutine=_get_previous_result,
        name="get_previous_result",
        description=GET_PREVIOUS_RESULT.description,
    ))

    # Phase 4.2: cache-inspection tools. Without these wrappers the
    # tools are registered in ToolRegistry but never bound to the
    # LangGraph agent — the LLM physically cannot call them. This was
    # the root cause of "Phase 4.2 ships but no follow-ups use it":
    # registration ≠ tool binding.
    from app.services.tools.definitions import (
        GET_CACHED_ROWS,
        INSPECT_CACHED_RESULT,
    )

    async def _get_cached_rows(
        rows_ref: str, offset: int = 0, limit: int = 20
    ) -> str:
        """Fetch a slice of rows from a cached query result."""
        return await ToolRegistry.execute(
            "get_cached_rows",
            tool_context,
            rows_ref=rows_ref,
            offset=offset,
            limit=limit,
        )

    tools.append(StructuredTool.from_function(
        coroutine=_get_cached_rows,
        name="get_cached_rows",
        description=GET_CACHED_ROWS.description,
    ))

    async def _inspect_cached_result(
        rows_ref: str,
        operation: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Run filter / top_n / describe / group_summary / count_distinct
        over a cached query result."""
        return await ToolRegistry.execute(
            "inspect_cached_result",
            tool_context,
            rows_ref=rows_ref,
            operation=operation,
            params=params or {},
        )

    tools.append(StructuredTool.from_function(
        coroutine=_inspect_cached_result,
        name="inspect_cached_result",
        description=INSPECT_CACHED_RESULT.description,
    ))

    # ========================================================================
    # ANALYSIS TOOLS - Intelligent data analysis
    # ========================================================================

    # detect_insights
    async def _detect_insights(data: str, analysis_types: Optional[List[str]] = None) -> str:
        """Find patterns, trends, anomalies, and risks in query results."""
        return await ToolRegistry.execute(
            "detect_insights", tool_context,
            data=data, analysis_types=analysis_types
        )

    tools.append(StructuredTool.from_function(
        coroutine=_detect_insights,
        name="detect_insights",
        description=DETECT_INSIGHTS.description,
    ))

    # analyze_statistics
    async def _analyze_statistics(data: str, columns: Optional[List[str]] = None) -> str:
        """Compute advanced statistics beyond basic aggregations."""
        return await ToolRegistry.execute(
            "analyze_statistics", tool_context,
            data=data, columns=columns
        )

    tools.append(StructuredTool.from_function(
        coroutine=_analyze_statistics,
        name="analyze_statistics",
        description=ANALYZE_STATISTICS.description,
    ))

    # check_data_quality
    async def _check_data_quality(data: str) -> str:
        """Assess data quality and completeness of query results."""
        return await ToolRegistry.execute(
            "check_data_quality", tool_context, data=data
        )

    tools.append(StructuredTool.from_function(
        coroutine=_check_data_quality,
        name="check_data_quality",
        description=CHECK_DATA_QUALITY.description,
    ))

    # compare_periods
    async def _compare_periods(
        current_data: str,
        comparison_type: str,
        previous_data: Optional[str] = None,
        original_sql: Optional[str] = None
    ) -> str:
        """Compare time periods or segments."""
        return await ToolRegistry.execute(
            "compare_periods", tool_context,
            current_data=current_data,
            comparison_type=comparison_type,
            previous_data=previous_data,
            original_sql=original_sql
        )

    tools.append(StructuredTool.from_function(
        coroutine=_compare_periods,
        name="compare_periods",
        description=COMPARE_PERIODS.description,
    ))

    # suggest_followups
    async def _suggest_followups(insights: str, query_context: str) -> str:
        """Generate smart follow-up questions based on insights."""
        return await ToolRegistry.execute(
            "suggest_followups", tool_context,
            insights=insights, query_context=query_context
        )

    tools.append(StructuredTool.from_function(
        coroutine=_suggest_followups,
        name="suggest_followups",
        description=SUGGEST_FOLLOWUPS.description,
    ))

    # recommend_chart
    async def _recommend_chart(
        data: str,
        insights: Optional[str] = None,
        analysis_goal: Optional[str] = None
    ) -> str:
        """Intelligently recommend the best chart type for the data."""
        return await ToolRegistry.execute(
            "recommend_chart", tool_context,
            data=data, insights=insights, analysis_goal=analysis_goal
        )

    tools.append(StructuredTool.from_function(
        coroutine=_recommend_chart,
        name="recommend_chart",
        description=RECOMMEND_CHART.description,
    ))

    # prepare_chart_data
    async def _prepare_chart_data(
        data: str,
        chart_type: str,
        max_points: int = 50,
        handle_outliers: bool = True
    ) -> str:
        """Transform data intelligently for visualization."""
        return await ToolRegistry.execute(
            "prepare_chart_data", tool_context,
            data=data,
            chart_type=chart_type,
            max_points=max_points,
            handle_outliers=handle_outliers
        )

    tools.append(StructuredTool.from_function(
        coroutine=_prepare_chart_data,
        name="prepare_chart_data",
        description=PREPARE_CHART_DATA.description,
    ))

    # annotate_chart
    async def _annotate_chart(
        chart_spec: str,
        insights: Optional[str] = None,
        statistics: Optional[str] = None,
        comparisons: Optional[str] = None
    ) -> str:
        """Add intelligent annotations to charts."""
        return await ToolRegistry.execute(
            "annotate_chart", tool_context,
            chart_spec=chart_spec,
            insights=insights,
            statistics=statistics,
            comparisons=comparisons
        )

    tools.append(StructuredTool.from_function(
        coroutine=_annotate_chart,
        name="annotate_chart",
        description=ANNOTATE_CHART.description,
    ))

    return tools


# ============================================================================
# ERROR CLASSIFICATION AND RECOVERY
# ============================================================================


def classify_error(error_message: str, tool_name: str) -> dict:
    """
    Classify errors and provide recovery guidance for the LLM.

    Returns a dict with:
    - error_type: Classification of the error
    - is_retryable: Whether the LLM should retry with different approach
    - recovery_hint: Specific guidance for the LLM to recover
    """
    error_lower = error_message.lower()

    # Permission/access errors (check early to avoid false positives with "table" keyword)
    if any(x in error_lower for x in ["permission denied", "access denied", "unauthorized", "forbidden"]):
        return {
            "error_type": "PERMISSION_ERROR",
            "is_retryable": False,
            "failure_class": "permanent",
            "recovery_hint": (
                "PERMISSION DENIED: You don't have access to this table or schema. "
                "Use search_tables to find accessible tables, or inform the user "
                "about the access limitation."
            ),
        }

    # Column not found errors (check BEFORE table errors to avoid false positives)
    # Match patterns like "column X does not exist", "unknown column", "column not found"
    if any(x in error_lower for x in ["column", "field", "attribute", "unknown column"]) and \
       any(x in error_lower for x in ["not found", "does not exist", "unknown", "no such", "invalid"]):
        return {
            "error_type": "COLUMN_NOT_FOUND",
            "is_retryable": True,
            "failure_class": "permanent",
            "recovery_hint": (
                "COLUMN NOT FOUND: Use get_table_schema to verify exact column names. "
                "Check for typos or if the column is in a different table that needs to be JOINed. "
                "The schema may also be stale — a background refresh is being triggered for "
                "the affected table."
            ),
        }

    # Foreign key violations (permanent - referential integrity)
    # Check BEFORE table errors: messages like "on table violates foreign key" contain "table"
    if any(x in error_lower for x in ["foreign key", "fk constraint", "violates constraint",
                                       "referential integrity", "constraint violation"]):
        return {
            "error_type": "FOREIGN_KEY_VIOLATION",
            "is_retryable": False,
            "failure_class": "permanent",
            "recovery_hint": (
                "FOREIGN KEY VIOLATION: The data violates referential integrity constraints. "
                "This means you're trying to insert/update a record that references a non-existent "
                "parent record, or delete a parent that has child records. "
                "Use get_table_schema to understand table relationships and foreign key constraints. "
                "This is a data integrity issue, not a query error - inform the user."
            ),
        }

    # Data type mismatches (permanent - type incompatibility)
    # Check BEFORE table errors: "operator does not exist" contains "does not exist"
    if any(x in error_lower for x in ["type mismatch", "operator does not exist",
                                       "cannot cast", "invalid input syntax for type",
                                       "incompatible types", "type conversion"]):
        # Detect specific type issue if possible
        type_hint = ""
        if "integer" in error_lower and any(x in error_lower for x in ["varchar", "text", "string"]):
            type_hint = " (Comparing integer with string - add explicit cast or fix comparison logic)"
        elif "date" in error_lower or "timestamp" in error_lower:
            type_hint = " (Date/time type mismatch - check date formats and use proper type casts)"

        return {
            "error_type": "DATA_TYPE_MISMATCH",
            "is_retryable": True,
            "failure_class": "permanent",
            "recovery_hint": (
                f"DATA TYPE MISMATCH: Comparing or operating on incompatible data types.{type_hint} "
                "Solutions: "
                "1) Use explicit type casting (PostgreSQL: column::type, Standard SQL: CAST(column AS type)), "
                "2) Check column data types with get_table_schema, "
                "3) Ensure comparison operators match column types (e.g., use = for exact match, not LIKE with numbers)."
            ),
        }

    # Table/Relation not found errors
    if any(x in error_lower for x in ["relation", "table", "does not exist", "unknown table"]) and \
       not any(x in error_lower for x in ["column", "field", "attribute"]):
        # Check if it's a schema qualification issue
        if "." not in error_message or "schema" in error_lower:
            return {
                "error_type": "TABLE_NOT_FOUND",
                "is_retryable": True,
                "failure_class": "permanent",
                "recovery_hint": (
                    "TABLE NOT FOUND: The table name may be missing the schema prefix. "
                    "Use search_tables to find the correct SCHEMA-QUALIFIED name "
                    "(e.g., 'demoapp.policies' instead of 'policies')."
                ),
            }
        return {
            "error_type": "TABLE_NOT_FOUND",
            "is_retryable": True,
            "failure_class": "permanent",
            "recovery_hint": (
                "TABLE NOT FOUND: Use search_tables to find available tables "
                "and verify the correct schema-qualified name."
            ),
        }

    # Fallback table not found check for patterns like "X not found" without column keywords
    if "not found" in error_lower and not any(x in error_lower for x in ["column", "field", "attribute"]):
        return {
            "error_type": "TABLE_NOT_FOUND",
            "is_retryable": True,
            "failure_class": "permanent",
            "recovery_hint": (
                "TABLE NOT FOUND: Use search_tables to find available tables "
                "and verify the correct schema-qualified name."
            ),
        }

    # SQL syntax errors
    if any(x in error_lower for x in ["syntax error", "parse error", "unexpected token", "invalid"]):
        return {
            "error_type": "SYNTAX_ERROR",
            "is_retryable": True,
            "failure_class": "permanent",
            "recovery_hint": (
                "SQL SYNTAX ERROR: Check the query syntax. Common issues: "
                "1) Missing quotes around strings, 2) Wrong keyword order, "
                "3) Database-specific syntax (use find_similar_queries for patterns)."
            ),
        }

    # Cassandra/NoSQL partition key errors
    if any(x in error_lower for x in ["partition key", "primary key", "clustering key", "allow filtering"]):
        return {
            "error_type": "NOSQL_KEY_ERROR",
            "is_retryable": True,
            "failure_class": "permanent",
            "recovery_hint": (
                "NOSQL KEY ERROR: Cassandra/DynamoDB requires partition key in WHERE clause. "
                "Use get_table_schema to identify the partition keys and include them in your query. "
                "For Cassandra, you may need ALLOW FILTERING for non-key columns."
            ),
        }

    # Duplicate key violations (permanent - unique constraint)
    if any(x in error_lower for x in ["duplicate key", "unique constraint", "duplicate entry",
                                       "already exists", "uniqueness violation"]):
        return {
            "error_type": "DUPLICATE_KEY",
            "is_retryable": False,
            "failure_class": "permanent",
            "recovery_hint": (
                "DUPLICATE KEY: The data violates a unique constraint - this record already exists. "
                "This is NOT a query error but a data integrity message. "
                "Inform the user that: "
                "1) The record they're trying to insert/update already exists, "
                "2) They may need to update the existing record instead of inserting a new one, "
                "3) Use get_table_schema to see which columns have unique constraints."
            ),
        }

    # Infrastructure errors (transient but critical - needs ops attention)
    if any(x in error_lower for x in ["disk full", "out of memory", "insufficient resources",
                                       "no space left", "memory exhausted", "resource limit"]):
        return {
            "error_type": "INFRASTRUCTURE_ERROR",
            "is_retryable": False,  # Don't retry - needs ops intervention
            "failure_class": "transient",  # Not a query problem
            "recovery_hint": (
                "INFRASTRUCTURE ERROR: The database server is experiencing resource constraints "
                "(disk space, memory, etc.). This is NOT a query problem - it's an infrastructure issue. "
                "Inform the user: "
                "1) The system is temporarily unable to process queries due to resource constraints, "
                "2) They should contact support or try again later, "
                "3) This is not caused by their query."
            ),
        }

    # Timeout and connection errors (transient - might succeed on retry)
    if any(x in error_lower for x in ["timeout", "timed out", "connection", "connection refused",
                                       "service unavailable", "rate limit", "too many requests"]):
        return {
            "error_type": "TIMEOUT_ERROR",
            "is_retryable": True,
            "failure_class": "transient",
            "recovery_hint": (
                "TIMEOUT/CONNECTION ERROR: The query took too long or connection failed. "
                "Try: 1) Add more restrictive WHERE clauses, 2) Reduce data volume with LIMIT, "
                "3) Simplify JOINs."
            ),
        }

    # No data returned (not an error, but worth noting)
    if "no data" in error_lower or "empty" in error_lower or "0 rows" in error_lower:
        return {
            "error_type": "NO_DATA",
            "is_retryable": True,
            "failure_class": "transient",
            "recovery_hint": (
                "NO DATA RETURNED: The query executed but found no matching rows. "
                "Use get_sample_data to verify data exists, then relax your WHERE conditions "
                "or check for NULL values."
            ),
        }

    # Generic error
    return {
        "error_type": "UNKNOWN_ERROR",
        "is_retryable": True,
        "failure_class": "transient",
        "recovery_hint": (
            f"ERROR: {error_message}. "
            "Try: 1) Verify table/column names with get_table_schema, "
            "2) Check similar_queries for correct patterns, "
            "3) Simplify the query and rebuild step by step."
        ),
    }


"""
ERROR TYPE CLASSIFICATIONS (12 total):

PERMANENT ERRORS (schema/data structure issues):
1. PERMISSION_ERROR - Access denied, unauthorized
2. COLUMN_NOT_FOUND - Column doesn't exist in table
3. TABLE_NOT_FOUND - Table/relation doesn't exist
4. SYNTAX_ERROR - SQL syntax problems
5. NOSQL_KEY_ERROR - Missing partition/clustering keys
6. FOREIGN_KEY_VIOLATION - Referential integrity violation (NEW)
7. DATA_TYPE_MISMATCH - Type incompatibility in operations (NEW)
8. DUPLICATE_KEY - Unique constraint violation (NEW)

TRANSIENT ERRORS (temporary issues):
9. TIMEOUT_ERROR - Query/connection timeouts
10. CONNECTION_ERROR - Service unavailable
11. NO_DATA - Query succeeded but no results
12. INFRASTRUCTURE_ERROR - Disk full, OOM (needs ops attention) (NEW)
13. UNKNOWN_ERROR - Unclassified errors

Circuit Breaker Logic:
- Permanent: Stop after 3 occurrences (or 2 if same error)
- Transient: Stop after 5 consecutive failures
- Infrastructure: Don't retry (needs manual intervention)
"""


def enhance_error_message(result: str, tool_name: str) -> str:
    """
    Enhance error messages with recovery guidance for the LLM.
    """
    if "Error" not in result and "error" not in result.lower():
        return result

    # Classify the error
    error_info = classify_error(result, tool_name)

    # Add recovery hint to the result
    enhanced = f"{result}\n\n---\n**RECOVERY GUIDANCE ({error_info['error_type']}):**\n{error_info['recovery_hint']}"

    return enhanced


def _is_error_result(result: Any) -> bool:
    """
    Decide whether a tool result represents an error.

    Returns True if ANY of:
    1. The result contains the literal word ``Error`` or ``error`` (legacy
       string contract — preserved so existing plain-text error messages
       still classify correctly).
    2. The result is a JSON object whose ``success`` field is ``False``
       (Day 1a fix, documented in docs/architecture-audit-2026-04-16.md —
       catches JSON-encoded error envelopes the legacy string check missed,
       e.g. ``{"success": false, "message": "timeout"}``).

    Returns False for:
    - Non-string values (defensive — should not happen in practice).
    - Plain-text successful tool output such as schema tools' bulleted lists.
    - Valid JSON with ``success`` True or missing.

    The JSON-parsing branch honors the ``FIX_JSON_ERROR_DETECTION`` feature
    flag (defaults to True). Set it to False to roll back the fix without
    reverting code — the function then behaves exactly like the legacy
    string check.

    When the JSON branch catches a failure the legacy check would have
    missed, we increment the ``json_error_detection`` fix-event counter
    (see ``/health/diagnostic``). Metrics recording is wrapped in a
    try/except so a misconfigured metrics backend can never break the
    request path.
    """
    if not isinstance(result, str):
        return False

    # Legacy contract first — keep all existing error classification intact.
    if "Error" in result or "error" in result.lower():
        return True

    # Day 1a: detect JSON-encoded errors that don't contain the word "error".
    # (Flag amnesty 2026-05-12: FIX_JSON_ERROR_DETECTION rollback path removed.)
    stripped = result.strip()
    if not stripped:
        # Pure whitespace: neither an error envelope nor a plain-text
        # error message. Treat as not-an-error; downstream handling will
        # surface it through the result's existing parse paths.
        return False
    if not stripped.startswith("{"):
        return False  # plain text — not a JSON envelope

    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, ValueError):
        return False

    if isinstance(parsed, dict) and parsed.get("success") is False:
        try:
            from app.api.metrics import record_fix_event
            record_fix_event("json_error_detection")
        except Exception:
            pass
        return True

    return False


# ============================================================================
# CLI-STYLE OUTPUT HELPERS
# ============================================================================


def get_tool_description(tool_name: str, tool_args: dict) -> str:
    """Get human-readable description for a tool call."""
    descriptions = {
        "search_tables": lambda args: f"Searching for tables matching '{args.get('query', 'data')}'",
        "get_table_schema": lambda args: f"Getting schema for {args.get('table_name', 'table')}",
        "lookup_business_term": lambda args: f"Looking up term '{args.get('term', 'term')}'",
        "find_similar_queries": lambda args: f"Finding similar queries for '{args.get('query', '')[:50]}...'",
        "get_sample_data": lambda args: f"Getting sample data from {args.get('table_name', 'table')}",
        "execute_sql": lambda args: "Executing SQL query",
    }

    formatter = descriptions.get(tool_name, lambda args: f"Running {tool_name}")
    return formatter(tool_args)


def format_tool_result_summary(tool_name: str, content: str) -> str:
    """Format tool result as a brief summary."""
    if tool_name == "search_tables":
        # Extract table names from result
        if "Tables matching" in content:
            lines = content.split('\n')
            tables = [line.strip().lstrip('- ') for line in lines if line.strip().startswith('-')]
            if tables:
                return f"Found: {', '.join(tables[:5])}" + ("..." if len(tables) > 5 else "")
        return "No tables found"

    elif tool_name == "get_table_schema":
        # Extract column count
        if "Columns:" in content:
            lines = content.split('\n')
            col_count = sum(1 for line in lines if line.strip().startswith('- '))
            return f"{col_count} columns found"
        return "Schema retrieved"

    elif tool_name == "execute_sql":
        # Extract row count
        try:
            import json
            result = json.loads(content)
            row_count = result.get("row_count", 0)
            return f"{row_count} rows returned"
        except Exception:
            if "Rows returned:" in content:
                for line in content.split('\n'):
                    if "Rows returned:" in line:
                        return line.strip()
            return "Query executed"

    elif tool_name == "get_sample_data":
        if "Sample data from" in content:
            return "Sample data retrieved"
        if "No data found" in content:
            return "Table is empty"
        return "Checked table"

    elif tool_name == "find_similar_queries":
        if "Similar queries found" in content:
            return "Found similar query patterns"
        return "No similar queries"

    elif tool_name == "lookup_business_term":
        if "not found" in content.lower():
            return "Term not defined"
        return "Term definition found"

    return content[:100] + "..." if len(content) > 100 else content


def _generate_analysis_summary(execution_result: dict) -> str:
    """
    Generate summary from pre-computed analysis data (execute_and_analyze mode).

    The text adapts to what's actually in ``execution_result`` — it
    never promises "see insights below" when the insights array is
    empty (that was the "Analyzed 556 results … See insights below"
    dead-end users reported). When detectors produced no findings, we
    compose a descriptive summary from statistics / quality / chart
    so the user still gets a useful one-liner.
    """
    row_count = execution_result.get("row_count", 0)
    columns = execution_result.get("columns", [])
    insights = execution_result.get("insights", []) or []
    statistics = execution_result.get("statistics", {}) or {}
    quality = execution_result.get("quality", {}) or {}
    chart = execution_result.get("chart") or {}
    aggregated = bool(execution_result.get("aggregated"))

    if row_count == 0:
        return "The query returned no results. The data matching your criteria does not exist."

    # Base line: what we analysed.
    summary = f"Analyzed {row_count:,} results"
    if columns:
        summary += f" ({len(columns)} columns)"
    if aggregated:
        summary += " — aggregated view"

    # Count insight types.
    business_insights = [i for i in insights if i.get("type") == "business_insight"]
    statistical_insights = [
        i for i in insights if i.get("type") != "business_insight"
    ]

    # Step 3: if the LLM produced business insights, LEAD with the
    # highest-severity one as the headline. This is what turns the
    # top-of-card text from a template ("Analyzed N rows") into an
    # actual answer ("Top 3 regions drive 67% of premium — NA
    # dominates at $12.4M...").
    if business_insights:
        severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
        best = min(
            business_insights,
            key=lambda i: severity_rank.get(i.get("severity", "low"), 4),
        )
        headline_title = (best.get("title") or "").strip()
        headline_desc = (best.get("description") or "").strip()

        # Build the lead-with-narrative form:
        # "Analyzed N rows. <TITLE>. <DESCRIPTION (up to 280 chars)>.
        #  K more insights below."
        if headline_title or headline_desc:
            parts = [summary + "."]
            if headline_title:
                parts.append(headline_title + ".")
            if headline_desc:
                # Trim to keep the summary readable — full text still
                # renders in the insights card below.
                desc = headline_desc
                if len(desc) > 320:
                    desc = desc[:317].rsplit(" ", 1)[0] + "…"
                parts.append(desc)

            remaining_business = max(len(business_insights) - 1, 0)
            remaining_statistical = len(statistical_insights)
            tail_bits = []
            if remaining_business:
                tail_bits.append(f"{remaining_business} more business insight(s)")
            if remaining_statistical:
                tail_bits.append(f"{remaining_statistical} statistical finding(s)")
            if tail_bits:
                parts.append("See also: " + ", ".join(tail_bits) + ".")

            summary = " ".join(parts)

            # Quality note if concerning.
            if quality_score := quality.get("overall_score"):
                if quality_score < 80:
                    summary += f" (Data quality: {quality_score}/100)"

            return summary

    # Build the second clause based on what's ACTUALLY available.
    # Priority: explicit insights > statistics narrative > quality score
    # > fall-through "see full result".
    clauses = []

    if business_insights:
        clauses.append(f"{len(business_insights)} business insight(s)")
    if statistical_insights:
        clauses.append(f"{len(statistical_insights)} statistical finding(s)")

    if clauses:
        summary += ". " + ", ".join(clauses) + ". See insights below for detailed analysis."
    else:
        # No insights were produced — don't promise what isn't there.
        # Compose descriptive text from whatever IS available.
        narrative_bits = []
        if statistics:
            # Phase 4 hotfix: describe up to THREE numeric columns so
            # the user gets actual detail from their 9-column query,
            # not just the first one. Picks columns with complete
            # stats dicts (skips rows that only have a count).
            usable_cols = []
            for col_name, col_stats in statistics.items():
                if not isinstance(col_stats, dict):
                    continue
                mean = col_stats.get("mean")
                mn = col_stats.get("min")
                mx = col_stats.get("max")
                if mean is None or mn is None or mx is None:
                    continue
                usable_cols.append((col_name, mn, mx, mean))
                if len(usable_cols) >= 3:
                    break
            for col_name, mn, mx, mean in usable_cols:
                narrative_bits.append(
                    f"{col_name} {mn:g} to {mx:g} (mean {mean:g})"
                )

        if quality.get("overall_score") is not None:
            narrative_bits.append(
                f"data quality {quality['overall_score']}/100"
            )
        if chart.get("recommended_chart"):
            narrative_bits.append(
                f"chart: {chart['recommended_chart']}"
            )

        if narrative_bits:
            summary += ". " + "; ".join(narrative_bits) + "."
        else:
            # Truly minimal — say so honestly rather than promise
            # non-existent insights.
            summary += (
                ". No notable patterns detected — the data is uniform "
                "or too small for statistical findings. Full rows "
                "available in the data tab."
            )

    # Add quality note if concerning (even when we already summarized).
    quality_score = quality.get("overall_score", 100)
    if quality_score < 80 and "data quality" not in summary.lower():
        summary += f" (Data quality: {quality_score}/100)"

    return summary


def generate_data_summary(question: str, execution_result: dict) -> str:
    """
    Generate accurate summary from actual query results.
    Supports both row-based (execute_sql) and analysis-based (execute_and_analyze) results.
    """
    if not execution_result:
        logger.warning("generate_data_summary: No execution_result provided")
        return "Query did not return results."

    # Debug: log the full execution_result structure
    logger.info(f"generate_data_summary: execution_result keys: {list(execution_result.keys())}")
    logger.info(f"generate_data_summary: execution_result type: {type(execution_result)}")

    # Check if we have pre-computed analysis
    has_analysis = execution_result.get("has_analysis", False)

    if has_analysis:
        # Use pre-computed insights for summary (no rows needed)
        logger.info("generate_data_summary: Using pre-computed analysis mode")
        return _generate_analysis_summary(execution_result)

    # Original row-based logic (for execute_sql)
    logger.info("generate_data_summary: Using row-based summary mode")
    columns = execution_result.get("columns", [])
    rows = execution_result.get("rows", [])
    # Use the larger of row_count or actual rows length (defensive)
    explicit_count = execution_result.get("row_count", 0)
    actual_rows_count = len(rows) if rows else 0
    row_count = max(explicit_count, actual_rows_count)

    logger.info(f"generate_data_summary: explicit_count={explicit_count}, actual_rows={actual_rows_count}, columns={len(columns)}, rows_type={type(rows)}")

    if row_count == 0:
        return "The query returned no results. The data matching your criteria does not exist or the filter conditions were too restrictive."

    if row_count == 1:
        # Single result - try to describe it
        if rows and columns:
            row = rows[0]
            details = []
            for col in columns[:3]:
                val = row.get(col) if isinstance(row, dict) else None
                if val is not None:
                    details.append(f"{col}: {val}")
            if details:
                return f"Found 1 result: {', '.join(details)}"
        return "Found 1 result matching your criteria."

    # Multiple results - provide count and column info
    summary = f"Found {row_count} results"

    if columns:
        summary += f" with columns: {', '.join(columns[:5])}"
        if len(columns) > 5:
            summary += f" (+{len(columns) - 5} more)"

    # Add data highlights if available
    if rows and len(rows) > 0:
        highlights = []

        # Try to identify numeric columns for stats
        for col in columns[:3]:
            try:
                values = [r.get(col) for r in rows if isinstance(r, dict) and r.get(col) is not None]
                if values and all(isinstance(v, (int, float)) for v in values):
                    # Type narrowing: values are confirmed to be list of int/float
                    numeric_values = [v for v in values if isinstance(v, (int, float))]
                    if numeric_values:
                        min_val = min(numeric_values)
                        max_val = max(numeric_values)
                        if min_val != max_val:
                            highlights.append(f"{col} ranges from {min_val} to {max_val}")
            except Exception:
                pass

        if highlights:
            summary += ". " + "; ".join(highlights)

    summary += ". See the data tab for complete results."
    return summary


# ============================================================================
# AGENT NODE - LLM with tool calling via LiteLLM
# ============================================================================


SYSTEM_PROMPT = """You are an AI data analyst. Your job: answer the user's question about their data with real business insight, not a mechanical stat dump.

## How you talk to the user

Speak about THEIR DATA, not about how you got it. Never mention tool names, row limits, sampling, cache handles, or any other system internals in your reply. "I looked at 5,000 policies and found..." is fine; "I called execute_and_analyze with limit=5000..." is not. If the user's question is ambiguous, ask about their data ("which quarter did you mean?"), not about the system.

## Core loop

Each turn: think about what you need, pick the right tool, read the result, decide whether you have enough to answer or need another step. Stop as soon as you can answer well. Don't explore beyond what the question requires.

## Tools

**Exploration** — learn the schema:
- `search_tables(query)` — find relevant tables. Returns SCHEMA-QUALIFIED names (e.g. `demoapp.policies`). Always use the qualified name in SQL.
- `get_table_schema(table)` — columns, types, primary/foreign keys, and for NoSQL the partition/clustering keys.
- `lookup_business_term(term)` — resolve domain terms like "revenue", "churn", "ARR" to the SQL that defines them.
- `find_similar_queries(query)` — prior successful queries as templates.
- `get_sample_data(table)` — peek at actual row values.

**Primary workhorse**:
- `execute_and_analyze(sql, limit, question)` — run the query AND produce insights, statistics, data-quality score, chart recommendation, and follow-up suggestions in one call. Use this for almost every analyst question.
  - Do NOT put `LIMIT` / `.limit()` inside the SQL/query string — pass the `limit` parameter instead (default 1000, max 10K).
  - ALWAYS pass `question=` — the user's ORIGINAL natural-language ask, verbatim. This is what grounds the business narrative. Without it you get generic stat descriptions.
  - Returns a `rows_ref` handle — a pointer to the FULL cached result set (all rows, not just the 20-row preview). Use it for follow-ups.

**Follow-ups on the same dataset** — NEVER re-run SQL for these:
- `get_cached_rows(rows_ref, offset, limit)` — page through the full cached rows (max 50 per call). Use when the user asks to see specific rows the preview didn't include.
- `inspect_cached_result(rows_ref, operation, params)` — filter / top_n / describe / group_summary / count_distinct on the cached result, no DB hit.

**ROUTING RULE** — if the user's follow-up references "those results", "the previous query", "that data", or asks for a subset/slice/detail of what you just analyzed → call `inspect_cached_result` or `get_cached_rows` on the prior `rows_ref`. Only re-run `execute_and_analyze` when the user is asking for genuinely different data (different table, different date range, or a filter that can't be applied to the cached rows).

**Raw execution**:
- `execute_sql(sql)` — exists for cases where you truly need unanalyzed rows. Prefer `execute_and_analyze` unless you have a specific reason not to.

## Rules that matter

1. **Schema-qualified names always.** `demoapp.policies`, not `policies`. Same for Cassandra keyspaces and Mongo databases.
2. **NoSQL partition keys.** Cassandra: partition key REQUIRED in WHERE. DynamoDB: partition key (and optional sort key) required.
3. **Temporal questions — filter by date, don't use bare LIMIT.** For "last 30 days" / "since January" / "this quarter":
   - Check the schema for a date/timestamp column (`created_at`, `updated_at`, etc.).
   - Use the dialect's date arithmetic:
     - PostgreSQL: `WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'`
     - MySQL: `WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)`
     - SQL Server: `WHERE created_at >= DATEADD(day, -30, GETDATE())`
     - SQLite: `WHERE created_at >= date('now', '-30 days')`
   - `LIMIT` alone returns arbitrary rows and is wrong for temporal filtering.
4. **Verify before you execute.** Column names from the schema, not memory. Handle NULLs sensibly.

## When things go wrong

- **Table not found** → `search_tables` to get the correct qualified name.
- **Column not found** → `get_table_schema` to check exact spelling, or consider a JOIN.
- **SQL syntax error** → check dialect; consult `find_similar_queries`; simplify and rebuild.
- **No rows returned** → `get_sample_data` to confirm data exists; relax filters; check for NULLs excluded by your WHERE.
- **NoSQL partition-key error** → add the partition key to WHERE.

When you can't recover, tell the user what went wrong in terms of their data, not system internals."""


class ReActAgentNodes:
    """Nodes for the ReAct agent graph."""

    def __init__(
        self,
        llm_config: LLMConfig,
        tool_context: ToolContext,
        tools: List,
    ):
        self.llm_config = llm_config
        self.tool_context = tool_context
        self.tools = tools

        # Message truncator for context management
        self.truncator = MessageTruncator()

        # Detect if using Anthropic format
        # Note: Only use Anthropic format for direct Anthropic API calls
        # OAuth Gateway uses OpenAI format even for Anthropic models (it converts internally)
        self.is_anthropic = (
            llm_config.provider == "anthropic" and
            is_anthropic_model(llm_config.model or "")
        )

        # Build tool specs in appropriate format (OpenAI or Anthropic)
        if self.is_anthropic:
            # Anthropic format: direct tool schema without wrapper
            self.tool_specs = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.args_schema.schema() if hasattr(t, 'args_schema') else {
                        "type": "object",
                        "properties": {},
                    }
                }
                for t in tools
            ]
            logger.info(f"Using Anthropic tool format for model: {llm_config.model}")
        else:
            # OpenAI format: wrapped in function object
            self.tool_specs = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.args_schema.schema() if hasattr(t, 'args_schema') else {
                            "type": "object",
                            "properties": {},
                        }
                    }
                }
                for t in tools
            ]
            logger.info(f"Using OpenAI tool format for model: {llm_config.model}")

        # Map tool names to functions
        self.tool_map = {t.name: t for t in tools}

    # ------------------------------------------------------------------
    # State-transition helpers (Phase 2 Day 1)
    # ------------------------------------------------------------------

    # ReActState fields that the circuit breaker / routing logic depends
    # on. Defensive early returns from agent/tool nodes must set every one
    # of these explicitly so a downstream node never reads a stale value
    # from the previous iteration.
    _CRITICAL_STATE_FIELDS = (
        "status",
        "consecutive_no_tools",
        "consecutive_failures",
        "iterations_without_execution",
        "sql_attempts_failed",
    )

    @staticmethod
    def _build_complete_state_update(state: "Dict[str, Any]", **overrides) -> dict:
        """
        Return a state-update dict that explicitly asserts every critical
        field, defaulting to the current value and applying any overrides.

        LangGraph's default reducer for non-annotated fields is "replace if
        the key is present, keep previous otherwise". The audit flagged
        degenerate returns such as ``{"messages": []}`` at tool_node:1584
        as a source of state-machine confusion: the node is a no-op, but
        the reader has no way to tell whether that was intentional or a
        dropped update.

        Use this helper at any defensive / early-return path so that
        every state field that affects routing has an explicit, visible
        value in the return dict.

        >>> ReActAgentNodes._build_complete_state_update(
        ...     {"status": "thinking", "consecutive_failures": 2,
        ...      "consecutive_no_tools": 0,
        ...      "iterations_without_execution": 1,
        ...      "sql_attempts_failed": 0},
        ...     status="error",
        ... )["status"]
        'error'
        """
        update: Dict[str, Any] = {}
        for field in ReActAgentNodes._CRITICAL_STATE_FIELDS:
            if field in state:
                update[field] = state[field]
        update.update(overrides)
        return update

    @staticmethod
    def _safely_resume_state(state_values: dict, question: str) -> dict:
        """
        Build a fresh state dict to resume from a checkpoint without
        mutating the checkpointer's stored state.

        The previous implementation mutated ``state.values["messages"]``
        in place (``.append(HumanMessage(...))``) and set
        ``state.values["status"] = "thinking"`` directly. Under two
        concurrent resumes on the same ``thread_id`` (possible when the
        distributed lock has silently fallen back to a process-local
        asyncio.Lock — see Phase 2 Day 3), both requests append their
        question to the shared list and the second overwrites the first.

        Fix (audit §Problem 4.2): selectively deep-copy the messages
        list (which is the only mutated field) and return a new
        top-level dict. Do NOT deep-copy the full state — it contains
        service references and asyncio primitives that either cannot
        be deep-copied or are shared on purpose.
        """
        resumed = dict(state_values)  # shallow copy of top-level dict
        resumed["messages"] = copy.deepcopy(state_values.get("messages", []))
        resumed["messages"].append(HumanMessage(content=question))
        resumed["status"] = "thinking"
        try:
            from app.api.metrics import record_fix_event
            record_fix_event("checkpoint_resume_safe_copy")
        except Exception:
            pass
        return resumed

    async def agent_node(self, state: ReActState) -> dict:
        """
        Main agent node - calls LLM with tools.

        Uses LiteLLM for tool calling, returns either:
        - Tool calls to execute
        - Final answer
        """
        # Check iteration limit
        if state["iteration"] >= state["max_iterations"]:
            return {
                "status": "error",
                "error": "Maximum iterations reached",
            }

        # Truncate messages to prevent context overflow
        # This preserves: system prompt, original question, and recent messages
        truncated_messages, stats = self.truncator.truncate(
            state["messages"],
            include_stats=True,
        )  # type: tuple[list, TruncationStats | None]
        if stats and stats.messages_removed > 0:
            logger.debug(
                f"Truncated messages: {stats.original_count} -> {stats.truncated_count} "
                f"(removed {stats.messages_removed}, truncated {stats.tool_outputs_truncated} tool outputs)"
            )

        # Convert LangChain messages to LiteLLM format
        messages = self._convert_messages(truncated_messages)

        # Check if last message is already an assistant response without tool calls
        # This prevents invalid conversation patterns (assistant → assistant without user in between)
        # which cause OAuth Gateway crashes with Anthropic models
        if (
            len(truncated_messages) > 0 and
            isinstance(truncated_messages[-1], AIMessage) and
            (not hasattr(truncated_messages[-1], "tool_calls") or not truncated_messages[-1].tool_calls)
        ):
            # Last message is assistant without tool calls - this is already a final answer
            # Extract the content to include in response
            content = truncated_messages[-1].content or ""
            logger.info(
                "Agent node: Last message is assistant response without tool calls, treating as final answer",
                content_preview=content[:200]
            )

            return {
                "messages": [],  # Don't add more messages
                "agent_response": content,  # Store the assistant's message
                "total_usage": state.get("total_usage"),
                "iteration": state["iteration"],
                "status": "complete",
            }

        # Call LLM with tools
        response = await ToolCallingService.call_with_tools(
            config=self.llm_config,
            messages=messages,
            tools=self.tool_specs,
            temperature=0.1,
            max_tokens=4000,
        )

        # Track usage
        new_usage = self._aggregate_usage(state.get("total_usage"), response.usage)

        # Process response
        if response.has_tool_calls:
            # Check if we're already in complete status (from tool_node)
            # If execute_and_analyze or execute_sql already completed, don't allow more tool calls
            current_status = state.get("status")
            if current_status == "complete":
                logger.warning(
                    "Agent wants to call more tools after completion - forcing end",
                    requested_tools=[tc.name for tc in response.tool_calls],
                    current_iteration=state["iteration"]
                )
                # Return final answer without allowing more tool calls
                return {
                    "messages": [AIMessage(content="Analysis complete based on executed queries.")],
                    "status": "complete",
                    "total_usage": new_usage,
                    "iteration": state["iteration"] + 1,
                }

            # LLM wants to call tools (normal flow)
            tool_calls_msg = self._create_tool_calls_message(response)

            # Track tools used
            tools_used = list(state.get("tools_used", []))
            for tc in response.tool_calls:
                if tc.name not in tools_used:
                    tools_used.append(tc.name)

            return {
                "messages": [tool_calls_msg],
                "tools_used": tools_used,
                "tool_calls_count": state.get("tool_calls_count", 0) + len(response.tool_calls),
                "total_usage": new_usage,
                "iteration": state["iteration"] + 1,
                "status": "thinking",
                "consecutive_no_tools": 0,  # Reset counter when tools are called
                "iterations_without_execution": state.get("iterations_without_execution", 0) + 1,  # Increment exploration counter
            }
        else:
            # LLM provided final answer
            content = response.content or ""

            # Check if it contains SQL
            sql = self._extract_sql(content)

            if sql:
                return {
                    "messages": [AIMessage(content=content)],
                    "sql": sql,
                    "total_usage": new_usage,
                    "iteration": state["iteration"] + 1,
                    "status": "ready",
                }
            else:
                # No SQL found - check if we should continue or complete
                tools_used = state.get("tools_used", [])
                consecutive_no_tools = state.get("consecutive_no_tools", 0) + 1

                # If execute_sql was used, we're done
                # If we've had 2+ consecutive responses without tool calls, complete to avoid loops
                should_complete = (
                    "execute_sql" in tools_used or
                    consecutive_no_tools >= 2
                )

                if consecutive_no_tools >= 2:
                    logger.warning(
                        "Agent completing due to consecutive no-tool responses",
                        consecutive_no_tools=consecutive_no_tools,
                        iteration=state["iteration"],
                    )

                return {
                    "messages": [AIMessage(content=content)],
                    "total_usage": new_usage,
                    "iteration": state["iteration"] + 1,
                    "consecutive_no_tools": consecutive_no_tools if not should_complete else 0,
                    "status": "complete" if should_complete else "thinking",
                }

    async def tool_node(self, state: ReActState) -> dict:
        """
        Execute tool calls from the last message.

        Uses our ToolRegistry for execution.
        Enhances error messages with recovery guidance for the LLM.
        """
        last_message = state["messages"][-1]

        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            # Phase 2 Day 1: use the complete-state helper so we emit an
            # explicit terminal status instead of a partial no-op update.
            # Routing into tool_node without tool_calls is a contract
            # violation; surface it as error rather than silently looping.
            logger.warning(
                "tool_node entered without tool_calls — routing bug; terminating run",
                iteration=state.get("iteration"),
                status_in=state.get("status"),
            )
            return self._build_complete_state_update(
                dict(state),
                status="error",
                error="tool_node entered without tool_calls",
            ) | {"messages": []}

        tool_messages = []
        failed_attempts = state.get("failed_attempts", [])
        initial_failures_count = len(failed_attempts)  # Capture BEFORE mutating
        # Phase 2 Day 1: track SQL-tool failures this iteration so the
        # fall-through return at the bottom can increment
        # sql_attempts_failed correctly for the cases that don't return
        # early (success_field_check continue path, TimeoutError, generic
        # Exception on SQL tools).
        sql_failures_this_iter = 0
        SQL_EXEC_TOOLS = ("execute_sql", "execute_and_analyze")

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            logger.info(f"Executing tool: {tool_name}", args=tool_args)

            # PHASE 2A: Strip LIMIT clauses from SQL for both execute_sql and execute_and_analyze
            # The tool manages limits via the limit parameter, not SQL clauses
            if tool_name in ("execute_and_analyze", "execute_sql") and "sql" in tool_args:
                import re
                original_sql = tool_args["sql"]
                cleaned_sql = original_sql

                # Strip SQL LIMIT clause (e.g., "LIMIT 100")
                cleaned_sql = re.sub(r'\s+LIMIT\s+\d+\s*$', '', cleaned_sql, flags=re.IGNORECASE)

                # Strip MongoDB .limit() method (e.g., ".limit(100)")
                if '.limit(' in cleaned_sql:
                    cleaned_sql = re.sub(r'\.limit\(\d+\)', '', cleaned_sql)

                # Strip Cassandra CQL LIMIT
                cleaned_sql = re.sub(r'\s+LIMIT\s+\d+\s*;?\s*$', '', cleaned_sql, flags=re.IGNORECASE)

                if cleaned_sql != original_sql:
                    logger.warning(
                        f"tool_node: Stripped LIMIT from SQL for {tool_name}. "
                        f"Agent should not add LIMIT clauses - use limit parameter instead. "
                        f"Original: ...{original_sql[-80:]} → Cleaned: ...{cleaned_sql[-80:]}"
                    )
                    tool_args = {**tool_args, "sql": cleaned_sql}

            # Day 4: use a DB-type-aware timeout so data-lake queries that
            # routinely take minutes aren't killed by the 30s default meant
            # for transactional databases.
            #
            # Assigned OUTSIDE the try block so that if the helper itself
            # raises (e.g. a bug in _db_type_from_context), the exception
            # surfaces cleanly instead of being caught and masked by the
            # generic handler below. It also means the timeout-error path
            # can trust that ``tool_timeout`` is always bound.
            tool_timeout = _effective_tool_timeout(_db_type_from_context(self.tool_context))

            # Phase 2 Day 2: wrap the tool execution in an explicit
            # named task so a timeout can cancel it deterministically.
            # asyncio.wait_for already cancels its inner awaitable in
            # Python 3.10+, but by owning the task ourselves we:
            #   1. get a named entry in traceback / task introspection,
            #   2. can observe whether cancellation actually propagated
            #      (sync-DB drivers running on a ThreadPoolExecutor still
            #      run the underlying thread to completion — this is a
            #      Python limitation, fixed for data-lake DBs in Phase 3b
            #      which wires driver-native cancellation),
            #   3. prepare for Phase 3b per-driver cancellation hooks.
            tool_task = asyncio.create_task(
                ToolRegistry.execute(
                    tool_name,
                    self.tool_context,
                    **tool_args,
                ),
                name=f"tool_exec:{tool_name}:iter_{state['iteration']}",
            )
            try:
                # Execute via ToolRegistry with timeout
                result = await asyncio.wait_for(tool_task, timeout=tool_timeout)

                # Check for errors in result and enhance with recovery guidance.
                # Day 1a: `_is_error_result` also catches JSON envelopes with
                # `success: false` that the legacy string check missed.
                if _is_error_result(result):
                    enhanced_result = enhance_error_message(result, tool_name)

                    # Track failed attempt with error classification
                    error_info = classify_error(result, tool_name)
                    failed_attempts.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "error": result,
                        "error_info": error_info,
                    })

                    # If the classifier tagged this as COLUMN_NOT_FOUND,
                    # fire a fire-and-forget single-table schema
                    # refresh so the next get_table_schema call sees
                    # the fresh indexed copy. No-op when the SQL has
                    # no parseable FROM clause or the auto-refresh
                    # flag is disabled.
                    _maybe_schedule_schema_refresh_on_column_error(
                        error_info, tool_args, self.tool_context
                    )

                    tool_messages.append(ToolMessage(
                        content=enhanced_result,
                        tool_call_id=tool_call["id"],
                        name=tool_name,
                    ))
                else:
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call["id"],
                        name=tool_name,
                    ))

                    # Check if this was execute_sql success
                    if tool_name == "execute_sql":
                        # Parse the JSON result from execute_sql tool
                        import json
                        try:
                            parsed_result = json.loads(result)

                            # Day 1b: Defense-in-depth check.
                            # If the tool self-reports failure (success=False),
                            # route this result through the error path instead of
                            # forcing status="complete" and resetting counters.
                            # _is_error_result at the gate should already have
                            # caught this, but if anything ever bypasses it we
                            # still want the state machine to see the failure.
                            if (
                                isinstance(parsed_result, dict)
                                and parsed_result.get("success") is False
                            ):
                                try:
                                    from app.api.metrics import record_fix_event
                                    record_fix_event("success_field_check")
                                except Exception:
                                    pass

                                error_info = classify_error(result, tool_name)
                                failed_attempts.append({
                                    "tool": tool_name,
                                    "args": tool_args,
                                    "error": result,
                                    "error_info": error_info,
                                })
                                # Replace the optimistic tool_message (appended
                                # just above this block) with an enhanced error
                                # so the LLM sees accurate context for retry.
                                if tool_messages and tool_messages[-1].tool_call_id == tool_call["id"]:
                                    tool_messages[-1] = ToolMessage(
                                        content=enhance_error_message(result, tool_name),
                                        tool_call_id=tool_call["id"],
                                        name=tool_name,
                                    )
                                logger.warning(
                                    "tool_node: execute_sql self-reported failure; "
                                    "routed through error path",
                                    error=parsed_result.get("error"),
                                )
                                # Phase 2 Day 1: count this as a failed SQL
                                # attempt so the two-counter circuit breaker
                                # can trip after 3 successive SQL failures.
                                sql_failures_this_iter += 1
                                # Skip the early-return below; let the post-loop
                                # handler track consecutive_failures correctly.
                                continue

                            execution_result = {
                                "success": parsed_result.get("success", True),
                                "columns": parsed_result.get("columns", []),
                                "rows": parsed_result.get("rows", []),
                                "row_count": parsed_result.get("row_count", 0),
                                "raw_output": parsed_result.get("display", result),
                            }
                            # Debug: log what we parsed
                            logger.info(f"tools_node: execute_sql returned row_count={execution_result['row_count']}, rows_len={len(execution_result['rows'])}, columns={len(execution_result['columns'])}")
                        except (json.JSONDecodeError, TypeError) as e:
                            # Day 1 fix: when the result string cannot be
                            # parsed we have no structured data to report.
                            # Previously we set ``success: True`` with the
                            # raw string, which is the masking pattern
                            # Phase 1 exists to kill. Mark as failure
                            # instead and route through the error-counter
                            # path so the circuit breaker tracks it.
                            logger.warning(
                                f"tools_node: Failed to parse execute_sql result as JSON: {e}"
                            )
                            execution_result = {
                                "raw_output": result,
                                "success": False,
                                "error": f"Failed to parse tool result: {e}",
                            }
                            error_info = classify_error(str(e), tool_name)
                            failed_attempts.append({
                                "tool": tool_name,
                                "args": tool_args,
                                "error": str(e),
                                "error_info": error_info,
                            })

                        is_sql_success = bool(execution_result.get("success"))
                        return {
                            "messages": tool_messages,
                            "sql": tool_args.get("sql"),  # Capture the SQL that was executed
                            "execution_result": execution_result,
                            "failed_attempts": failed_attempts,
                            # Status reflects whether we actually got data back.
                            "status": "complete" if is_sql_success else "error",
                            # Only reset failure counters on real success.
                            "consecutive_failures": 0 if is_sql_success else state.get("consecutive_failures", 0) + 1,
                            "iterations_without_execution": 0,
                            # Phase 2 Day 1: independent SQL-failure counter.
                            # Resets on SQL success, increments on SQL failure.
                            "sql_attempts_failed": 0 if is_sql_success else state.get("sql_attempts_failed", 0) + 1,
                        }

                    # Check if this was execute_and_analyze (analysis with insights)
                    if tool_name == "execute_and_analyze":
                        # Parse the analysis result
                        import json
                        try:
                            parsed_result = json.loads(result)

                            # Day 1b: Defense-in-depth check.
                            # If the tool self-reports failure (success=False),
                            # route this result through the error path instead of
                            # forcing status="complete" and resetting counters.
                            # This is the exact bug that produced the "query
                            # returned no results" cascade on valid data.
                            if (
                                isinstance(parsed_result, dict)
                                and parsed_result.get("success") is False
                            ):
                                try:
                                    from app.api.metrics import record_fix_event
                                    record_fix_event("success_field_check")
                                except Exception:
                                    pass

                                error_info = classify_error(result, tool_name)
                                failed_attempts.append({
                                    "tool": tool_name,
                                    "args": tool_args,
                                    "error": result,
                                    "error_info": error_info,
                                })
                                if tool_messages and tool_messages[-1].tool_call_id == tool_call["id"]:
                                    tool_messages[-1] = ToolMessage(
                                        content=enhance_error_message(result, tool_name),
                                        tool_call_id=tool_call["id"],
                                        name=tool_name,
                                    )
                                logger.warning(
                                    "tool_node: execute_and_analyze self-reported failure; "
                                    "routed through error path",
                                    error=parsed_result.get("error"),
                                )
                                # Phase 2 Day 1: two-counter circuit breaker
                                sql_failures_this_iter += 1
                                continue

                            # Build execution_result with analysis data
                            execution_result = {
                                "success": parsed_result.get("success", True),
                                "columns": parsed_result.get("columns", []),
                                "rows": parsed_result.get("rows", []),  # Actual data for display
                                "row_count": parsed_result.get("row_count", parsed_result.get("analyzed_rows", 0)),
                                "execution_time_ms": parsed_result.get("execution_time_ms", 0),

                                # Analysis-specific fields (pre-computed)
                                "has_analysis": True,
                                "analyzed_rows": parsed_result.get("analyzed_rows", 0),
                                "insights": parsed_result.get("insights", []),
                                "statistics": parsed_result.get("statistics", {}),
                                "quality": parsed_result.get("quality", {}),
                                "chart": parsed_result.get("chart"),

                                # Phase 3a Day 3: aggregation-mode flags
                                "aggregated": parsed_result.get("aggregated", False),
                                "grouping_columns": parsed_result.get("grouping_columns", []),
                                "aggregate_columns": parsed_result.get("aggregate_columns", []),

                                # Phase 4.1: cache handle for the full row set.
                                # Frontend fetches via /api/v1/results/{rows_ref};
                                # LLM drills in via get_cached_rows /
                                # inspect_cached_result (Phase 4.2).
                                "rows_ref": parsed_result.get("rows_ref"),
                                "rows_cached": parsed_result.get("rows_cached", False),
                                "preview_row_count": parsed_result.get("preview_row_count"),

                                # Metadata
                                "raw_output": parsed_result.get("message", result),
                                "limit_applied": parsed_result.get("limit_applied", 0),
                                "has_more": parsed_result.get("has_more", False),
                            }

                            captured_sql = tool_args.get("sql")
                            logger.info(
                                f"tool_node: execute_and_analyze success - analyzed {execution_result['analyzed_rows']} rows, "
                                f"{len(execution_result['insights'])} insights, chart={execution_result['chart'] is not None}, "
                                f"sql_captured={bool(captured_sql)}, sql_preview={captured_sql[:100] if captured_sql else 'None'}..."
                            )

                            # Return with execution_result set and status complete
                            return {
                                "messages": tool_messages,
                                "sql": captured_sql,
                                "execution_result": execution_result,
                                "failed_attempts": failed_attempts,
                                "status": "complete",
                                "consecutive_failures": 0,  # Reset on successful execution
                                "iterations_without_execution": 0,  # Reset on SQL execution
                                "sql_attempts_failed": 0,  # Phase 2 Day 1: reset on SQL success
                            }

                        except (json.JSONDecodeError, TypeError, KeyError) as e:
                            logger.error(f"tool_node: Failed to parse execute_and_analyze result: {e}")
                            # Fallback: Strip control characters and retry parse before giving up
                            import re
                            cleaned = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', result) if isinstance(result, str) else result
                            try:
                                parsed_fallback = json.loads(cleaned)
                                execution_result = {
                                    "success": parsed_fallback.get("success", True),
                                    "has_analysis": True,
                                    "columns": parsed_fallback.get("columns", []),
                                    "rows": parsed_fallback.get("rows", []),
                                    "row_count": parsed_fallback.get("row_count", parsed_fallback.get("analyzed_rows", 0)),
                                    "insights": parsed_fallback.get("insights", []),
                                    "statistics": parsed_fallback.get("statistics", {}),
                                    "quality": parsed_fallback.get("quality", {}),
                                    "chart": parsed_fallback.get("chart"),
                                    "raw_output": parsed_fallback.get("message", cleaned),
                                }
                                logger.info("tool_node: Recovered execute_and_analyze result after stripping control characters")
                            except (json.JSONDecodeError, TypeError, KeyError) as fallback_err:
                                # Truly unparseable — mark as failure so the
                                # circuit breaker sees it. Previously this
                                # was set to ``success: True, row_count: 0``,
                                # which is the exact masking pattern Phase 1
                                # exists to kill.
                                execution_result = {
                                    "success": False,
                                    "has_analysis": False,
                                    "raw_output": result,
                                    "row_count": 0,
                                    "columns": [],
                                    "error": f"Failed to parse analysis result: {fallback_err}",
                                }
                                error_info = classify_error(
                                    f"Error parsing execute_and_analyze result: {fallback_err}",
                                    tool_name,
                                )
                                failed_attempts.append({
                                    "tool": tool_name,
                                    "args": tool_args,
                                    "error": str(fallback_err),
                                    "error_info": error_info,
                                })
                                logger.warning(
                                    f"tool_node: execute_and_analyze result unrecoverable after control-char strip, "
                                    f"result_len={len(result) if isinstance(result, str) else 'N/A'}"
                                )
                            fallback_sql = tool_args.get("sql")
                            is_success = execution_result.get("success", False)
                            return {
                                "messages": tool_messages,
                                "sql": fallback_sql,
                                "execution_result": execution_result,
                                "failed_attempts": failed_attempts,
                                # Only claim "complete" when the result was
                                # actually recovered; otherwise signal error.
                                "status": "complete" if is_success else "error",
                                "consecutive_failures": 0 if is_success else state.get("consecutive_failures", 0) + 1,
                                "iterations_without_execution": 0,
                                # Phase 2 Day 1: fallback parse path counts as SQL failure when unrecoverable
                                "sql_attempts_failed": 0 if is_success else state.get("sql_attempts_failed", 0) + 1,
                            }

            except asyncio.TimeoutError:
                # Phase 2 Day 2: explicitly cancel the task and await
                # its cancellation so that cancellation-aware drivers
                # get a chance to release their side of the query.
                # asyncio.wait_for already sends cancel(), but awaiting
                # tool_task here ensures any finally-blocks (e.g.
                # connection release) run before we record the timeout.
                cancel_succeeded = False
                if not tool_task.done():
                    tool_task.cancel()
                try:
                    await tool_task
                except asyncio.CancelledError:
                    cancel_succeeded = True
                except Exception:
                    # Task died with a different exception during
                    # cancellation cleanup; that's fine — we still
                    # want to surface the original TimeoutError.
                    pass
                if cancel_succeeded:
                    try:
                        from app.api.metrics import record_fix_event
                        record_fix_event("tool_task_cancelled_on_timeout")
                    except Exception:
                        pass

                # Log the *actual* timeout applied to this call (the
                # DB-type-aware extended value for data lakes, base
                # AGENT_TOOL_TIMEOUT for transactional DBs). tool_timeout
                # is guaranteed-bound because it's computed before the
                # try block enters.
                applied_timeout = tool_timeout
                timeout_context = {
                    "tool": tool_name,
                    "timeout_seconds": applied_timeout,
                    "iteration": state["iteration"],
                    "cancel_propagated": cancel_succeeded,
                    "args_summary": {
                        k: (v[:100] + "..." if isinstance(v, str) and len(v) > 100 else v)
                        for k, v in tool_args.items()
                    }
                }

                # Add SQL-specific context for query tools
                if tool_name in ["execute_sql", "execute_and_analyze"]:
                    sql_query = tool_args.get("sql", "")
                    timeout_context.update({
                        "sql_length": len(sql_query),
                        "sql_preview": sql_query[:200] + "..." if len(sql_query) > 200 else sql_query,
                        "limit": tool_args.get("limit", "default"),
                    })

                logger.error(
                    f"Tool {tool_name} timed out after {applied_timeout}s",
                    **timeout_context
                )

                # Track failed attempt with error classification
                error_msg = f"Tool timeout after {applied_timeout} seconds"
                error_info = classify_error(f"Error: {error_msg}", tool_name)
                failed_attempts.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "error": error_msg,
                    "error_info": error_info,
                    "timeout_context": timeout_context,  # Include context in tracking
                })

                enhanced_error = enhance_error_message(f"Error: {error_msg}", tool_name)
                tool_messages.append(ToolMessage(
                    content=enhanced_error,
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                ))

                # Phase 2 Day 1: a SQL-tool timeout is a SQL attempt that
                # failed — track it independently from consecutive_failures
                # so the breaker can trip on 3 successive SQL failures.
                if tool_name in SQL_EXEC_TOOLS:
                    sql_failures_this_iter += 1

            except Exception as e:
                # Enhanced logging with execution context
                error_context = {
                    "tool": tool_name,
                    "error_type": type(e).__name__,
                    "iteration": state["iteration"],
                    "args_summary": {
                        k: (v[:100] + "..." if isinstance(v, str) and len(v) > 100 else v)
                        for k, v in tool_args.items()
                    }
                }

                # Add SQL-specific context for query tools
                if tool_name in ["execute_sql", "execute_and_analyze"]:
                    sql_query = tool_args.get("sql", "")
                    error_context.update({
                        "sql_length": len(sql_query),
                        "sql_preview": sql_query[:200] + "..." if len(sql_query) > 200 else sql_query,
                    })

                logger.error(
                    f"Tool {tool_name} failed: {str(e)}",
                    **error_context
                )

                # Enhance exception with recovery guidance
                error_msg = f"Error: {str(e)}"
                enhanced_error = enhance_error_message(error_msg, tool_name)

                # Track failed attempt with error classification
                error_info = classify_error(error_msg, tool_name)
                failed_attempts.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "error": str(e),
                    "error_info": error_info,
                })

                tool_messages.append(ToolMessage(
                    content=enhanced_error,
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                ))

                # Phase 2 Day 1: generic exceptions on SQL tools also count
                # as failed SQL attempts for the two-counter breaker.
                if tool_name in SQL_EXEC_TOOLS:
                    sql_failures_this_iter += 1

        # Update consecutive_failures counter
        # If we got here, no execution tool succeeded (would have returned early)
        # Check if any tool failed in this iteration (compare to count captured before loop)
        current_failures_count = len(failed_attempts)
        had_failures_this_iteration = current_failures_count > initial_failures_count

        if had_failures_this_iteration:
            # At least one tool failed → increment consecutive failures
            consecutive_failures = state.get("consecutive_failures", 0) + 1
        else:
            # All tools succeeded (but none were execution tools) → reset counter
            consecutive_failures = 0

        # Phase 2 Day 1: sql_attempts_failed accumulates across iterations;
        # only the early-return paths (successful SQL execution) reset it.
        sql_attempts_failed = state.get("sql_attempts_failed", 0) + sql_failures_this_iter

        return {
            "messages": tool_messages,
            "failed_attempts": failed_attempts,
            "consecutive_failures": consecutive_failures,
            "sql_attempts_failed": sql_attempts_failed,
        }

    def _validate_tool_call_integrity(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Validate and repair tool call integrity in message list.

        Ensures that:
        1. Every assistant message with tool_calls has corresponding tool messages
        2. Every tool message has a matching tool_call in the preceding assistant message
        3. Orphaned messages are removed to prevent gateway "list index out of range" errors

        Returns:
            List of messages with proper tool call pairing
        """
        result: List[BaseMessage] = []
        pending_tool_call_ids: set = set()

        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage):
                # If we have pending tool calls from previous assistant message,
                # that's a problem - those tool messages were never provided
                if pending_tool_call_ids:
                    logger.warning(
                        "Orphaned tool calls detected (no tool messages followed)",
                        orphaned_ids=list(pending_tool_call_ids),
                    )
                    # Remove the previous assistant message with orphaned tool_calls
                    if result and isinstance(result[-1], AIMessage):
                        if hasattr(result[-1], "tool_calls") and result[-1].tool_calls:
                            # Replace with version without tool_calls to avoid gateway error
                            old_msg = result.pop()
                            result.append(AIMessage(content=old_msg.content or "(Agent was thinking...)"))
                    pending_tool_call_ids.clear()

                # Track new tool calls from this assistant message
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    pending_tool_call_ids = {tc["id"] for tc in msg.tool_calls}
                result.append(msg)

            elif isinstance(msg, ToolMessage):
                if msg.tool_call_id in pending_tool_call_ids:
                    pending_tool_call_ids.discard(msg.tool_call_id)
                    result.append(msg)
                else:
                    # This tool message doesn't match any pending tool call
                    logger.warning(
                        "Orphaned tool message (no matching tool_call)",
                        tool_call_id=msg.tool_call_id,
                        tool_name=getattr(msg, 'name', 'unknown'),
                    )
                    # Skip orphaned tool messages - they cause gateway errors
            else:
                # System/Human messages - clear pending since we shouldn't have
                # tool calls spanning non-tool messages
                if pending_tool_call_ids:
                    logger.warning(
                        f"Tool calls interrupted by {type(msg).__name__}",
                        pending_ids=list(pending_tool_call_ids),
                    )
                    # Find and fix the orphaned AIMessage with tool_calls
                    # It must be somewhere earlier in result (before any intervening ToolMessages)
                    for idx in range(len(result) - 1, -1, -1):
                        msg_at_idx = result[idx]
                        if isinstance(msg_at_idx, AIMessage):
                            if hasattr(msg_at_idx, "tool_calls") and msg_at_idx.tool_calls:
                                old_msg = msg_at_idx
                                result[idx] = AIMessage(
                                    content=old_msg.content or "(Agent was thinking...)"
                                )
                                break
                    pending_tool_call_ids.clear()
                result.append(msg)

        # Handle any remaining pending tool calls at end of list
        if pending_tool_call_ids:
            logger.warning(
                "Trailing orphaned tool calls at end of messages",
                orphaned_ids=list(pending_tool_call_ids),
            )
            if result and isinstance(result[-1], AIMessage):
                if hasattr(result[-1], "tool_calls") and result[-1].tool_calls:
                    old_msg = result.pop()
                    result.append(AIMessage(content=old_msg.content or "(Agent was thinking...)"))

        # Final validation pass: ensure no AIMessage with tool_calls lacks corresponding ToolMessages
        # This catches any edge cases that the above logic might have missed
        validated_result = self._final_tool_call_validation(result)

        return validated_result

    def _final_tool_call_validation(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Final validation pass to ensure no orphaned tool calls or results exist.

        This is a safety net that catches any edge cases missed by the primary validation.
        It performs a complete forward scan to verify:
        1. All tool calls have corresponding results
        2. All tool results have corresponding tool calls

        Args:
            messages: Messages that have been through primary validation

        Returns:
            Messages with any orphaned tool calls or results removed
        """
        result: List[BaseMessage] = []
        # Track which ToolMessages are valid (match a tool call from preceding AIMessage)
        valid_tool_message_indices: set = set()
        i = 0

        # First pass: Identify valid ToolMessages by scanning from each AIMessage
        for idx, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                # Found an AIMessage with tool_calls
                tool_call_ids = {tc["id"] for tc in msg.tool_calls}

                # Look ahead for matching ToolMessages
                j = idx + 1
                while j < len(messages) and isinstance(messages[j], ToolMessage):
                    tool_msg = messages[j]
                    if getattr(tool_msg, "tool_call_id", None) in tool_call_ids:
                        # This ToolMessage is valid
                        valid_tool_message_indices.add(j)
                    j += 1

        # Second pass: Build result with validation
        while i < len(messages):
            msg = messages[i]

            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                # Found an AIMessage with tool_calls
                # Scan ahead to count how many valid ToolMessages follow
                tool_call_ids = {tc["id"] for tc in msg.tool_calls}
                matched_tool_results = set()

                # Look ahead for matching ToolMessages
                j = i + 1
                while j < len(messages) and isinstance(messages[j], ToolMessage):
                    tool_msg = messages[j]
                    assert isinstance(tool_msg, ToolMessage)
                    if j in valid_tool_message_indices and tool_msg.tool_call_id in tool_call_ids:
                        matched_tool_results.add(tool_msg.tool_call_id)
                    j += 1

                # Check if all tool calls have results
                if matched_tool_results != tool_call_ids:
                    missing_ids = tool_call_ids - matched_tool_results
                    logger.error(
                        "CRITICAL: Final validation caught orphaned tool calls",
                        ai_message_position=i,
                        tool_call_ids=list(tool_call_ids),
                        matched_results=list(matched_tool_results),
                        missing_ids=list(missing_ids),
                        message="Removing tool_calls and associated tool results to prevent gateway error."
                    )
                    # Remove tool_calls to prevent gateway error
                    result.append(AIMessage(content=msg.content or "(Agent was thinking...)"))
                    # Also invalidate associated ToolMessages — they become orphaned
                    # tool_results without a matching tool_use when we strip tool_calls
                    j2 = i + 1
                    while j2 < len(messages) and isinstance(messages[j2], ToolMessage):
                        tm = messages[j2]
                        if j2 in valid_tool_message_indices and isinstance(tm, ToolMessage) and tm.tool_call_id in tool_call_ids:
                            valid_tool_message_indices.discard(j2)
                        j2 += 1
                else:
                    # All tool calls have results - safe to include
                    result.append(msg)
            elif isinstance(msg, ToolMessage):
                # Only append ToolMessages that were validated as matching a tool call
                if i in valid_tool_message_indices:
                    result.append(msg)
                else:
                    logger.warning(
                        "Final validation: Skipping orphaned ToolMessage",
                        tool_call_id=msg.tool_call_id,
                        tool_name=getattr(msg, 'name', 'unknown'),
                        message_index=i
                    )
            else:
                # System/Human messages - always safe
                result.append(msg)

            i += 1

        return result

    def _convert_messages(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        """Convert LangChain messages to LiteLLM format (OpenAI or Anthropic)."""
        # First validate tool call integrity to prevent gateway errors
        validated_messages = self._validate_tool_call_integrity(messages)

        result: List[Dict[str, Any]] = []

        if self.is_anthropic:
            # Anthropic format conversion
            for msg in validated_messages:
                if isinstance(msg, SystemMessage):
                    result.append({"role": "system", "content": msg.content or ""})
                elif isinstance(msg, HumanMessage):
                    result.append({"role": "user", "content": msg.content or ""})
                elif isinstance(msg, AIMessage):
                    # Anthropic format: use content array with text and tool_use blocks
                    content_blocks: List[Dict[str, Any]] = []

                    # Add text block if there's content
                    if msg.content:
                        # Handle both string and list content types
                        text_content = msg.content if isinstance(msg.content, str) else str(msg.content)
                        content_blocks.append({
                            "type": "text",
                            "text": text_content
                        })

                    # Add tool_use blocks for each tool call
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            content_blocks.append({
                                "type": "tool_use",
                                "id": tc.get("id") or tc["id"],
                                "name": tc["name"],
                                "input": tc["args"] if isinstance(tc["args"], dict) else {}
                            })

                    result.append({
                        "role": "assistant",
                        "content": content_blocks if content_blocks else [{"type": "text", "text": ""}]
                    })
                elif isinstance(msg, ToolMessage):
                    # Anthropic format: tool results go in user message with tool_result blocks
                    result.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content or ""
                        }]
                    })
        else:
            # OpenAI format conversion
            for msg in validated_messages:
                if isinstance(msg, SystemMessage):
                    result.append({"role": "system", "content": msg.content or ""})
                elif isinstance(msg, HumanMessage):
                    result.append({"role": "user", "content": msg.content or ""})
                elif isinstance(msg, AIMessage):
                    # Ensure content is never None - some gateways require this
                    content = msg.content if msg.content else ""
                    entry = {"role": "assistant", "content": content}
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        entry["tool_calls"] = [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else str(tc["args"]),
                                }
                            }
                            for tc in msg.tool_calls
                        ]
                    result.append(entry)
                elif isinstance(msg, ToolMessage):
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content or "",
                    }
                    # Include name field if available (helps OAuth Gateway convert to Anthropic)
                    if hasattr(msg, 'name') and msg.name:
                        tool_msg["name"] = msg.name
                    result.append(tool_msg)

        return result

    def _create_tool_calls_message(self, response) -> AIMessage:
        """
        Create AIMessage with tool calls from LLM response.

        Note: ToolCall.arguments (our dataclass attribute) is mapped to "args" key
        to match LangChain's AIMessage.tool_calls format which expects {"id", "name", "args"}.
        """
        tool_calls: list[ToolCall] = response.tool_calls
        return AIMessage(
            content=response.content or "",
            tool_calls=[
                {
                    "id": tc.id,
                    "name": tc.name,
                    "args": tc.arguments,  # ToolCall.arguments → "args" key for LangChain
                }
                for tc in tool_calls
            ]
        )

    def _extract_sql(self, content: str) -> Optional[str]:
        """Extract SQL from content if present.

        Only extracts valid SELECT/WITH queries to avoid extracting
        educational examples or non-executable SQL snippets.
        """
        content = content.strip()

        def is_valid_query(sql: str) -> bool:
            """Check if SQL is a valid executable query (SELECT or WITH/CTE)."""
            upper = sql.upper().lstrip()
            return upper.startswith("SELECT") or upper.startswith("WITH")

        # Check for markdown code blocks (```sql ... ```)
        if "```sql" in content.lower():
            start = content.lower().find("```sql") + 6
            end = content.find("```", start)
            if end > start:
                sql = content[start:end].strip()
                if is_valid_query(sql):
                    return sql

        # Check for generic code blocks (``` ... ```)
        if "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                sql = content[start:end].strip()
                if is_valid_query(sql):
                    return sql

        # Check if content is raw SQL
        if is_valid_query(content):
            # Find end of SQL (before any explanation)
            lines = content.split("\n")
            sql_lines = []
            for line in lines:
                if line.strip() and not line.strip().startswith(("#", "--", "//")):
                    sql_lines.append(line)
                elif sql_lines and not line.strip():
                    break
            return "\n".join(sql_lines)

        return None

    def _aggregate_usage(
        self,
        existing: Optional[Dict[str, Any]],
        new_usage: Optional[LLMUsageData],
    ) -> Dict[str, Any]:
        """Aggregate LLM usage data."""
        if not new_usage:
            return existing or {}

        new_dict = new_usage.to_dict() if hasattr(new_usage, "to_dict") else {}

        if not existing:
            return {**new_dict, "calls": 1}

        return {
            "prompt_tokens": existing.get("prompt_tokens", 0) + new_dict.get("prompt_tokens", 0),
            "completion_tokens": existing.get("completion_tokens", 0) + new_dict.get("completion_tokens", 0),
            "total_tokens": existing.get("total_tokens", 0) + new_dict.get("total_tokens", 0),
            "cost_usd": existing.get("cost_usd", 0.0) + new_dict.get("cost_usd", 0.0),
            "model": new_dict.get("model", existing.get("model", "")),
            "calls": existing.get("calls", 1) + 1,
        }


# ============================================================================
# ROUTING
# ============================================================================


def _aggregation_prompt_hint() -> str:
    """
    Phase 3c.2: prompt fragment that nudges the LLM toward GROUP BY for
    analytical questions.

    Legacy behaviour: the agent tends to emit ``SELECT *`` for every
    question, then relies on client-side sampling to keep result sets
    sane. That wastes bandwidth, breaks on billion-row tables, and
    produces worse insights because raw rows have more noise than
    pre-aggregated groups.

    Hint only appears when ``FIX_PROMPT_AGGREGATION_HINT`` is on and
    disappears cleanly when the flag is off — returning ``""`` is a
    no-op for ``base_prompt + hint``.
    """
    if not settings.FIX_PROMPT_AGGREGATION_HINT:
        return ""
    return """

## ANALYTICAL QUERY GUIDANCE (aggregation)

When the user's question asks for totals, averages, breakdowns,
distributions, concentrations, or trends over time — prefer a
``GROUP BY`` query that returns one row per group rather than
``SELECT *`` that returns raw rows. Signals the question is
analytical:

- Contains "total", "sum", "average", "mean", "count", "breakdown",
  "distribution", "top N", "per <dimension>", "by <dimension>",
  "trend", "over time", "share of".
- Asks for a comparison between categories or time periods.
- Answer would be easier to chart than to list.

For those questions, emit SQL like:

    SELECT <grouping_cols>, <aggregate_fn>(<metric>) AS <alias>
    FROM <table>
    GROUP BY <grouping_cols>
    ORDER BY <alias> DESC
    LIMIT <reasonable_n>

Use raw ``SELECT *`` only when the user explicitly wants example rows,
a lookup of a specific record, or forensic data-quality inspection.
"""


def _query_progress_event(
    elapsed_ms: int,
    bytes_scanned: Optional[int] = None,
    rows_read: Optional[int] = None,
    percent: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Phase 3b.2: build a ``query_progress`` SSE event.

    Emitted by async-native executors (BigQuery via ``QueryJob``'s
    ``total_bytes_processed``, Snowflake via query status polling)
    during long-running queries. The front-end uses it to render a
    "Running 2m 15s — 1.2 GB scanned" badge without interrupting the
    chat event stream.

    Only fields with a value are included in the payload so the UI
    doesn't have to null-check every one (BigQuery exposes
    bytes_scanned but not percent; Snowflake only exposes state).
    """
    event: Dict[str, Any] = {
        "event": "query_progress",
        "elapsed_ms": int(elapsed_ms),
    }
    if bytes_scanned is not None:
        event["bytes_scanned"] = int(bytes_scanned)
    if rows_read is not None:
        event["rows_read"] = int(rows_read)
    if percent is not None:
        event["percent"] = float(percent)
    return event


def _sse_heartbeat_event(elapsed_ms: int) -> Dict[str, Any]:
    """
    Phase 3a Day 2: build a heartbeat SSE event.

    Emitted every ``SSE_HEARTBEAT_INTERVAL`` seconds during quiet periods
    (e.g. multi-minute data-lake queries) to keep reverse proxies and
    browsers from closing the stream. Frontend should treat this as a
    no-op keepalive; the ``elapsed_ms`` payload enables "running for
    N seconds" status displays without any extra round-trip.
    """
    return {
        "event": "heartbeat",
        "elapsed_ms": int(elapsed_ms),
    }


SSE_HEARTBEAT_INTERVAL = 15.0  # seconds between heartbeats during quiet periods


async def _merge_stream_with_heartbeat(
    source: AsyncGenerator[Any, None],
    interval: float = SSE_HEARTBEAT_INTERVAL,
    start_time: Optional[float] = None,
    progress_queue: Optional[asyncio.Queue] = None,
) -> AsyncGenerator[Any, None]:
    """
    Phase 3a Day 2 / Phase 3b.2: wrap an async iterator and inject
    keepalive events during quiet periods.

    Two kinds of injected events:
      - ``heartbeat`` every ``interval`` seconds when the source is
        silent (keeps reverse proxies from closing the SSE stream).
      - ``query_progress`` drained from ``progress_queue`` whenever a
        native-async executor (Phase 3b.3+) pushes progress metrics via
        ``ToolContext.progress_emitter``.

    The underlying astream loop in LangGraph blocks between events. When
    a tool execution takes minutes, no events flow downstream and the
    SSE connection goes idle — some corporate proxies close streams
    after 60s idle, Chrome after ~120s. Emitting a heartbeat every 15s
    keeps the connection warm without polluting the user-visible chat
    history (frontend ignores ``event=heartbeat``).

    Implementation note: we drive the source via its async-iterator
    protocol directly so we can wrap ``__anext__`` in a timeout. This
    is roughly equivalent to a producer-task + asyncio.Queue merger
    but avoids the extra task overhead and GC pressure of spinning up
    a helper task per stream.
    """
    if start_time is None:
        start_time = time.monotonic()

    iterator = source.__aiter__()
    next_task: Optional[asyncio.Task] = None
    try:
        while True:
            # Keep one in-flight __anext__ task alive across heartbeats.
            # Using asyncio.wait_for here would cancel the coroutine on
            # timeout, corrupting the async generator's frame; asyncio.wait
            # leaves it pending so the source can keep running while we
            # emit heartbeats.
            if next_task is None:
                next_task = asyncio.create_task(iterator.__anext__())  # type: ignore[arg-type]

            done, _pending = await asyncio.wait({next_task}, timeout=interval)

            # Drain any queued progress events first (Phase 3b.2). These
            # were pushed via ToolContext.progress_emitter by a native-
            # async driver while the source was busy. Draining before
            # yielding the next source event keeps progress monotonic
            # with respect to the underlying driver's clock.
            if progress_queue is not None:
                while True:
                    try:
                        payload = progress_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    yield _query_progress_event(
                        elapsed_ms=elapsed_ms,
                        bytes_scanned=payload.get("bytes_scanned") if isinstance(payload, dict) else None,
                        rows_read=payload.get("rows_read") if isinstance(payload, dict) else None,
                        percent=payload.get("percent") if isinstance(payload, dict) else None,
                    )

            if next_task in done:
                try:
                    event = next_task.result()
                except StopAsyncIteration:
                    return
                next_task = None
                yield event
            else:
                # Source quiet for ``interval`` seconds → emit heartbeat.
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                yield _sse_heartbeat_event(elapsed_ms)
    finally:
        # Generator was closed mid-stream (client disconnect, error):
        # cancel any pending __anext__ so the source coroutine can clean
        # up rather than hang as a zombie task.
        if next_task is not None and not next_task.done():
            next_task.cancel()
            try:
                await next_task
            except (asyncio.CancelledError, Exception):
                pass


async def _background_lock_extender(
    lock: Any,
    interval: float,
    ttl: int,
    session_id: str,
) -> None:
    """
    Phase 2 Day 3: refresh the session's distributed lock TTL every
    ``interval`` seconds in a dedicated background task so that long
    tool executions (data-lake queries routinely run 2-5 min) don't
    let the lock's 120s TTL expire silently.

    Previously the extension ran inside the astream loop conditional on
    a per-iteration event arriving — an LLM call or long query kept the
    main loop idle, no event arrived, and the lock timed out mid-run.
    Spawning a dedicated task decouples extension from agent progress.

    The task exits on its own if ``lock.extend()`` returns False (lock
    was lost / stolen) so the main loop sees a stable "no extension"
    state rather than continuing with false confidence. Otherwise it
    runs until cancelled from the finally block of the caller.
    """
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                extended = await lock.extend(ttl)
            except Exception as e:
                logger.error(
                    f"Background lock extender: extend() raised for "
                    f"session {session_id}: {e}"
                )
                return
            if not extended:
                try:
                    from app.api.metrics import record_fix_event
                    record_fix_event("background_lock_extension_failure")
                except Exception:
                    pass
                logger.error(
                    f"Background lock extender: extension failed for "
                    f"session {session_id}; lock may have been stolen. "
                    f"Stopping extension task."
                )
                return
    except asyncio.CancelledError:
        logger.debug(
            f"Background lock extender: cancelled for session {session_id}"
        )
        raise


def _format_failure_context(failures: List[dict], max_items: int = 3) -> List[dict]:
    """Format recent failures for structured logging"""
    return [
        {
            "tool": f.get("tool"),
            "error_type": f.get("error_info", {}).get("error_type"),
            "failure_class": f.get("error_info", {}).get("failure_class"),
            "error_preview": str(f.get("error", ""))[:100]
        }
        for f in failures[-max_items:]
    ]


def should_continue(state: ReActState) -> Literal["tools", "agent", "end"]:
    """Decide next step based on state."""
    last_message = state["messages"][-1] if state["messages"] else None

    # Error state
    if state.get("status") == "error":
        return "end"

    # Max iterations
    if state["iteration"] >= state["max_iterations"]:
        return "end"

    # Wall-clock soft budget. Earlier checks bound the agent by
    # tool-call count and failure count; this one bounds wall time.
    # Without it, a slow query (data lake → 5 min/tool) × 10
    # iterations = 50 min worst case. Default 600 s sits above any
    # single-tool timeout, below the unguarded worst case. 0 disables.
    wall_clock_budget = state.get("wall_clock_budget_seconds", 0) or 0
    wall_clock_start = state.get("wall_clock_start", 0) or 0
    if wall_clock_budget > 0 and wall_clock_start > 0:
        elapsed = time.monotonic() - wall_clock_start
        if elapsed >= wall_clock_budget:
            logger.error(
                "Circuit breaker: wall-clock budget exceeded",
                elapsed_seconds=round(elapsed, 1),
                budget_seconds=wall_clock_budget,
                iteration=state["iteration"],
                question=state.get("question", "")[:100],
            )
            return "end"

    # Complete state
    if state.get("status") == "complete":
        return "end"

    # Circuit breaker: Check for excessive failures
    failed_attempts = state.get("failed_attempts", [])
    consecutive_failures = state.get("consecutive_failures", 0)
    iterations_without_execution = state.get("iterations_without_execution", 0)
    sql_attempts_failed = state.get("sql_attempts_failed", 0)

    # Count recent permanent errors (last 5 failures)
    recent_failures = failed_attempts[-5:] if len(failed_attempts) > 0 else []
    permanent_count = sum(
        1 for f in recent_failures
        if f.get("error_info", {}).get("failure_class") == "permanent"
    )

    # Stop if 3+ permanent errors (adjusted from 2 to prevent false positives)
    if permanent_count >= 3:
        # Check if same error type repeated (true loop vs. legitimate corrections)
        error_types = [
            f.get("error_info", {}).get("error_type")
            for f in recent_failures
            if f.get("error_info", {}).get("failure_class") == "permanent"
        ]

        failure_context = _format_failure_context(recent_failures)

        if len(set(error_types)) == 1 and len(error_types) >= 2:
            # Same error repeated twice → true loop
            logger.error(
                "Circuit breaker: repeated permanent error (true loop detected)",
                error_type=error_types[0],
                repetitions=len(error_types),
                total_failures=len(failed_attempts),
                recent_failures=failure_context,
                iteration=state["iteration"],
                question=state.get("question", "")[:100]
            )
            return "end"
        elif permanent_count >= 3:
            # Different errors but 3 total → still stop
            logger.error(
                "Circuit breaker: 3 permanent failures (multiple error types)",
                error_types=list(set(error_types)),
                total_failures=len(failed_attempts),
                recent_failures=failure_context,
                iteration=state["iteration"],
                question=state.get("question", "")[:100]
            )
            return "end"

    # Stop if 5+ consecutive transient failures
    if consecutive_failures >= 5:
        failure_context = _format_failure_context(failed_attempts[-5:])

        logger.error(
            "Circuit breaker: 5 consecutive failures",
            consecutive_count=consecutive_failures,
            total_failures=len(failed_attempts),
            recent_failures=failure_context,
            iteration=state["iteration"],
            question=state.get("question", "")[:100]
        )
        return "end"

    # Phase 2 Day 1: two-counter circuit breaker.
    #
    # The legacy single ``iterations_without_execution`` counter conflated
    # exploration (legitimate schema lookups) with SQL attempts that
    # failed. The audit splits these:
    #   - exploration threshold 10 (loosened from 7 for 3-table JOIN
    #     discovery which needs ~6 iterations)
    #   - SQL-failure threshold 3 (new, tracked in sql_attempts_failed)
    #
    # FIX_TWO_COUNTER_CIRCUIT_BREAKER=False reverts to the legacy
    # single-counter behaviour with threshold 7 for emergency rollback.
    if settings.FIX_TWO_COUNTER_CIRCUIT_BREAKER:
        exploration_limit = 10
        if sql_attempts_failed >= 3:
            try:
                from app.api.metrics import record_fix_event
                record_fix_event("two_counter_circuit_breaker")
            except Exception:
                pass
            logger.error(
                "Circuit breaker: 3+ SQL attempts failed",
                sql_attempts_failed=sql_attempts_failed,
                total_failures=len(failed_attempts),
                recent_failures=_format_failure_context(failed_attempts[-5:]),
                iteration=state["iteration"],
                question=state.get("question", "")[:100],
            )
            return "end"
    else:
        exploration_limit = 7

    if iterations_without_execution >= exploration_limit:
        # Get recent tool calls to understand what agent is doing
        recent_tools = [
            f.get("tool")
            for f in failed_attempts[-exploration_limit:]
            if f.get("tool")
        ]

        logger.warning(
            f"Circuit breaker: exploration loop detected after {exploration_limit} iterations",
            iterations_without_execution=iterations_without_execution,
            recent_tools=recent_tools,
            total_tools_used=len(state.get("tools_used", [])),
            iteration=state["iteration"],
            question=state.get("question", "")[:100]
        )
        return "end"

    # consecutive_no_tools belt-and-braces. agent_node already locally
    # sets status="complete" after the same ``>= 2`` threshold and
    # the router returns "end" on status=="complete" earlier. But if
    # status doesn't propagate (refactor regression, partial state
    # update), the agent could loop on no-tool responses until
    # max_iterations catches it. This explicit check fails fast in
    # the router so the contract is "I enforce termination" rather
    # than "I trust the field to have propagated".
    consecutive_no_tools = state.get("consecutive_no_tools", 0)
    if consecutive_no_tools >= 2:
        logger.warning(
            "Circuit breaker: 2+ consecutive no-tool responses (router safety net)",
            consecutive_no_tools=consecutive_no_tools,
            iteration=state["iteration"],
            question=state.get("question", "")[:100],
        )
        return "end"

    # Check if last message has tool calls
    if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # Check if we have SQL and execution result
    if state.get("sql") and state.get("execution_result"):
        return "end"

    # Continue with agent
    return "agent"


# ============================================================================
# AGENT CREATION
# ============================================================================


def create_react_agent(
    llm_config: LLMConfig,
    tool_context: ToolContext,
    max_iterations: int = 10,
    checkpointer: Optional[Any] = None,
):
    """
    Create a ReAct agent using LangGraph.

    Args:
        llm_config: LLM configuration
        tool_context: Tool execution context
        max_iterations: Maximum agent iterations
        checkpointer: Optional LangGraph checkpointer for state persistence

    Returns:
        Compiled LangGraph (with checkpointer if provided)
    """
    # Create tools
    tools = create_langchain_tools(tool_context)

    # Create nodes
    nodes = ReActAgentNodes(llm_config, tool_context, tools)

    # Build graph
    workflow = StateGraph(ReActState)

    # Add nodes
    workflow.add_node("agent", nodes.agent_node)
    workflow.add_node("tools", nodes.tool_node)

    # Set entry point
    workflow.set_entry_point("agent")

    # Add conditional edges
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "agent": "agent",
            "end": END,
        }
    )

    # Tools always go back to agent
    workflow.add_edge("tools", "agent")

    # Compile with optional checkpointer for state persistence
    if checkpointer:
        logger.info(f"Compiling graph with checkpointer ({get_checkpointer_backend()})")
        return workflow.compile(checkpointer=checkpointer)
    else:
        logger.debug("Compiling graph without checkpointer (state not persisted)")
        return workflow.compile()


# ============================================================================
# PUBLIC API
# ============================================================================


class ReActAgent:
    """
    ReAct Agent for Analyst mode with optional state persistence.

    Features:
    - Automatic checkpointing (when configured) for horizontal scaling
    - Resume capability for failed runs
    - Thread-based state isolation

    Usage:
        agent = ReActAgent(llm_config, db_config, session_id)
        result = await agent.run("Who are my top customers?")

        # Resume a specific run
        agent = ReActAgent(llm_config, db_config, session_id, run_id="prev-run-123")
        result = await agent.run("Continue analysis", resume=True)
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        db_config: DatabaseConfig,
        session_id: str,
        run_id: Optional[str] = None,
        max_iterations: int = 10,
    ):
        self.llm_config = llm_config
        self.db_config = db_config
        self.session_id = session_id
        self.max_iterations = max_iterations

        # Use session's conversation_thread_id for stable checkpoint resume within
        # a conversation. On "Fresh" start, reset_conversation() clears this field
        # so a new conversation gets a new thread ID automatically.
        session_data_pre = session_store.get(session_id) or {}
        existing_thread_id = session_data_pre.get("conversation_thread_id")
        if existing_thread_id:
            self.run_id = existing_thread_id
        else:
            self.run_id = run_id or str(int(time.time() * 1000))
            session_store.update(session_id, {"conversation_thread_id": self.run_id})

        # Generate thread_id for checkpointing
        self.thread_id = generate_thread_id(session_id, self.run_id)

        # Create tool context
        session_data = session_store.get(session_id) or {}
        self.tool_context = ToolContext.from_session(session_id, session_data)

        # Get checkpointer (may be None if not configured)
        self.checkpointer = get_checkpointer()

        # Create graph with checkpointer
        self.graph = create_react_agent(
            llm_config,
            self.tool_context,
            max_iterations,
            checkpointer=self.checkpointer,
        )

        # Log checkpointer status
        if self.checkpointer:
            logger.info(
                "ReActAgent initialized with checkpointing",
                thread_id=self.thread_id,
                backend=get_checkpointer_backend(),
            )
        else:
            logger.debug(
                "ReActAgent initialized without checkpointing",
                thread_id=self.thread_id,
            )

    def _build_contextual_system_prompt(
        self,
        conversation_context: Optional[List[Dict]] = None,
        data_dictionary_context: Optional[str] = None,
    ) -> str:
        """
        Build system prompt with conversation history and data dictionary context.

        Adds conversation history section and business terms to base prompt if available.
        Includes token limit protection to prevent context overflow.

        Args:
            conversation_context: List of previous conversation turns
            data_dictionary_context: Business terms and column descriptions from data dictionary

        Returns:
            System prompt string with optional context sections
        """
        base_prompt = SYSTEM_PROMPT  # Use existing static prompt as base
        # Phase 3c.2: optional conditional GROUP BY guidance. Empty when
        # FIX_PROMPT_AGGREGATION_HINT is off, so concatenation is a
        # no-op on rollback.
        base_prompt = base_prompt + _aggregation_prompt_hint()

        # Add database type context PROMINENTLY so agent uses correct syntax
        db_type = getattr(self.db_config, 'db_type', None)
        if db_type:
            db_type_lower = db_type.lower()
            db_type_section = f"\n\n## CURRENT DATABASE: {db_type.upper()}\n\n"

            if db_type_lower == 'mongodb':
                db_type_section += """**CRITICAL: Use MongoDB query syntax, NOT SQL.**

MongoDB Query Format:
- Use: `db.collection.find({filter})` or `db.collection.aggregate([pipeline])`
- Dates MUST use Extended JSON: `{"$date": "2024-01-15T00:00:00Z"}` (NOT JavaScript `new Date()`)
- Field references in aggregation: `"$fieldname"` (with quotes and dollar sign)

Example aggregation for grouping:
```
db.inventory.aggregate([
  {"$match": {"created_at": {"$gte": {"$date": "2024-01-01T00:00:00Z"}}}},
  {"$group": {"_id": "$fuel_type", "count": {"$sum": 1}, "avg_price": {"$avg": "$price"}}}
])
```

DO NOT use: SELECT, FROM, WHERE, GROUP BY, JOIN (these are SQL, not MongoDB)
"""
            elif db_type_lower == 'cassandra':
                db_type_section += """**CRITICAL: Use Cassandra CQL syntax.**
- Must include partition key in WHERE clause
- No JOINs allowed - denormalized data model
- Example: `SELECT * FROM keyspace.table WHERE partition_key = 'value'`
"""
            elif db_type_lower == 'dynamodb':
                db_type_section += """**CRITICAL: Use DynamoDB PartiQL syntax.**
- Must include partition key in queries
- Example: `SELECT * FROM table WHERE pk = 'value'`
"""
            else:
                db_type_section += f"Use standard {db_type.upper()} SQL syntax.\n"

            base_prompt = db_type_section + base_prompt

        # Add data dictionary context if available (business terms, column descriptions)
        if data_dictionary_context:
            base_prompt += "\n\n## Business Terms & Data Dictionary\n\n"
            base_prompt += "The following business terms and column descriptions are relevant to this query:\n\n"
            base_prompt += data_dictionary_context
            base_prompt += "\n\n**When generating SQL, prefer using these defined business terms and expressions.**"

        if not conversation_context or len(conversation_context) == 0:
            return base_prompt

        # Token limit protection (reserve ~2000 tokens for conversation context)
        MAX_CONTEXT_TOKENS = 2000
        CHARS_PER_TOKEN = 4  # Conservative estimate
        max_context_chars = MAX_CONTEXT_TOKENS * CHARS_PER_TOKEN

        # Build context section
        header = "\n\n## Conversation History\n\nPrevious queries in this conversation:\n\n"
        footer = """
**When handling follow-up questions:**
1. Reference prior queries when relevant
2. Build upon previous query patterns
3. Don't re-explain context the user already knows
4. If user says "that data" or "those results", use get_previous_result tool
"""

        turns_list: List[str] = []
        current_length = len(header) + len(footer)

        # Add turns from most recent to oldest, stopping at limit
        for turn in reversed(conversation_context):
            turn_number = turn.get("turn", "?")
            question = turn.get("question", "N/A")
            query = turn.get("generated_query", "")
            answer = turn.get("answer", "")
            findings = turn.get("key_findings", [])

            turn_text = f"**Turn {turn_number}:**\n"
            turn_text += f"- Question: {question}\n"
            if query:
                truncated_query = query[:200] + ("..." if len(query) > 200 else "")
                turn_text += f"- Query: `{truncated_query}`\n"
            if answer:
                truncated_answer = answer[:200] + ("..." if len(answer) > 200 else "")
                turn_text += f"- Answer: {truncated_answer}\n"
            if findings:
                for finding in findings[:2]:
                    f_text = str(finding)[:100]
                    turn_text += f"- Finding: {f_text}\n"
            turn_text += "\n"

            # Check if adding this turn exceeds limit
            if current_length + len(turn_text) > max_context_chars:
                if not turns_list:
                    # Always add at least one turn (most recent)
                    turns_list.append(turn_text)
                turns_list.append("... (earlier context truncated for token limits)\n\n")
                break

            turns_list.append(turn_text)
            current_length += len(turn_text)

        # Reverse to show oldest -> newest
        context_section = header + "".join(reversed(turns_list)) + footer

        return base_prompt + context_section

    async def run(
        self,
        question: str,
        on_event: Optional[Callable[[Dict], None]] = None,
        resume: bool = False,
        conversation_context: Optional[List[Dict]] = None,
        data_dictionary_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the agent to answer a question.

        Uses distributed locking to prevent concurrent agent runs for the same session.

        Args:
            question: User's natural language question
            data_dictionary_context: Business terms and column descriptions from data dictionary
            on_event: Optional callback for streaming events
            resume: If True, attempt to resume from last checkpoint
            conversation_context: Previous conversation turns for context

        Returns:
            Dict with sql, execution_result, tools_used, usage, etc.
        """
        start_time = time.time()

        # Acquire distributed lock to prevent concurrent runs for same session
        lock = DistributedLock(
            f"session:{self.session_id}:agent",
            ttl_seconds=600,  # 10 minute max for agent runs
            acquire_timeout=5.0,  # Don't wait long, reject if busy
        )

        try:
            acquired = await lock.acquire()
            if not acquired:
                logger.warning(
                    f"Agent run rejected: session {self.session_id[:8]} already has active agent"
                )
                return {
                    "success": False,
                    "error": "Another agent is already running for this session. Please wait.",
                    "thread_id": self.thread_id,
                    "total_time_ms": int((time.time() - start_time) * 1000),
                }

            # Build config for checkpointing
            config = get_checkpoint_config(self.thread_id) if self.checkpointer else None

            if resume and self.checkpointer and config:
                # Try to resume from checkpoint
                result = await self._resume_from_checkpoint(question, config, start_time)
                if result:
                    return result
                # If no checkpoint found, fall through to fresh run
                logger.info("No checkpoint found, starting fresh run")

            # Build contextual system prompt with conversation history and data dictionary
            system_prompt = self._build_contextual_system_prompt(
                conversation_context, data_dictionary_context
            )

            # Initial state for fresh run
            initial_state = ReActState(
                messages=[
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=question),
                ],
                question=question,
                sql=None,
                execution_result=None,
                tools_used=[],
                tool_calls_count=0,
                failed_attempts=[],
                total_usage=None,
                status="thinking",
                error=None,
                iteration=0,
                max_iterations=self.max_iterations,
                consecutive_no_tools=0,
                consecutive_failures=0,
                iterations_without_execution=0,
                sql_attempts_failed=0,
                # Start the wall-clock and bind the budget from
                # settings. should_continue checks elapsed against
                # this every iteration; 0 disables.
                wall_clock_start=time.monotonic(),
                wall_clock_budget_seconds=float(
                    settings.AGENT_WALL_CLOCK_BUDGET_SECONDS
                ),
            )

            # Run graph with config (for checkpointing)
            if config:
                final_state = await self.graph.ainvoke(initial_state, config)
            else:
                final_state = await self.graph.ainvoke(initial_state)

            return self._build_result(final_state, start_time)

        except Exception as e:
            logger.error("ReAct agent failed", error=str(e), exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "thread_id": self.thread_id,
                "total_time_ms": int((time.time() - start_time) * 1000),
            }
        finally:
            await lock.release()

    async def _resume_from_checkpoint(
        self,
        question: str,
        config: dict,
        start_time: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt to resume from a checkpoint.

        Returns:
            Result dict if resumed successfully, None if no checkpoint found
        """
        try:
            # Get the latest checkpoint state
            state = await self.graph.aget_state(config)

            if state and state.values:
                logger.info(
                    "Resuming from checkpoint",
                    thread_id=self.thread_id,
                    iteration=state.values.get("iteration", 0),
                )

                # Phase 2 Day 2: build a fresh state dict rather than
                # mutating the checkpointer's returned object. Prevents
                # double-append on concurrent resume of the same thread_id.
                resumed_state = ReActAgentNodes._safely_resume_state(
                    state.values, question
                )

                # Resume execution with resumed state (not None, which would reload stale checkpoint)
                final_state = await self.graph.ainvoke(resumed_state, config)
                return self._build_result(final_state, start_time, resumed=True)

            return None

        except Exception as e:
            logger.warning(f"Failed to resume from checkpoint: {e}")
            return None

    def _extract_chart_spec(self, final_state: dict) -> Optional[Dict[str, Any]]:
        """
        Extract chart specification from tool results.

        Looks for recommend_chart tool results in the message history.
        """
        messages = final_state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage) and msg.name == "recommend_chart":
                try:
                    # msg.content can be str or list - ensure it's a string
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    result = json.loads(content)
                    if "recommended_chart" in result:
                        return result
                except (json.JSONDecodeError, AttributeError, TypeError):
                    continue
        return None

    def _extract_insights(self, final_state: dict) -> Optional[List[Dict[str, Any]]]:
        """
        Extract insights from tool results.

        Looks for detect_insights tool results in the message history.
        """
        messages = final_state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage) and msg.name == "detect_insights":
                try:
                    # msg.content can be str or list - ensure it's a string
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    result = json.loads(content)
                    if "insights" in result and isinstance(result["insights"], list):
                        return result["insights"]
                except (json.JSONDecodeError, AttributeError, TypeError):
                    continue
        return None

    def _extract_suggested_followups(self, final_state: dict) -> Optional[List[Dict[str, Any]]]:
        """
        Extract suggested follow-up questions from tool results or generate from insights.

        Two-tier extraction:
        1. Primary: suggest_followups tool result in message history
        2. Fallback: auto-generate from execution_result insights via _generate_followups
        """
        # Primary: scan for suggest_followups tool result
        messages = final_state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage) and msg.name == "suggest_followups":
                try:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    result = json.loads(content)
                    if "suggestions" in result and isinstance(result["suggestions"], list):
                        return result["suggestions"]
                except (json.JSONDecodeError, AttributeError, TypeError):
                    continue

        # Fallback: generate from execution_result insights
        execution_result = final_state.get("execution_result")
        if execution_result and execution_result.get("insights"):
            try:
                question = final_state.get("question", "")
                followups = _generate_followups(
                    {"insights": execution_result["insights"]},
                    question,
                )
                if followups:
                    return followups
            except Exception:
                pass

        return None

    def _build_result(
        self,
        final_state: dict,
        start_time: float,
        resumed: bool = False,
    ) -> Dict[str, Any]:
        """Build the result dictionary from final state."""
        execution_result = final_state.get("execution_result")
        question = final_state.get("question", "")

        # Debug: Check what SQL is in the final state
        final_sql = final_state.get("sql")
        logger.info(f"_build_result: final_state.sql={bool(final_sql)}, preview={final_sql[:100] if final_sql else 'None'}...")

        # Debug logging
        if execution_result:
            logger.info(f"_build_result: execution_result keys: {list(execution_result.keys())}")
            logger.info(f"_build_result: row_count={execution_result.get('row_count', 'MISSING')}, rows_len={len(execution_result.get('rows', []))}")

        # Generate data-driven summary (more accurate than LLM hallucinations)
        data_summary = None
        agent_message = final_state.get("agent_response")  # Direct assistant response (e.g., refusals)

        if execution_result:
            data_summary = generate_data_summary(question, execution_result)
        elif agent_message:
            # Agent provided a text response without executing a query
            data_summary = agent_message
        else:
            # Extract last assistant message from conversation if available
            messages = final_state.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    # Handle both string and list content types
                    data_summary = msg.content if isinstance(msg.content, str) else str(msg.content)
                    break

        # Extract structured analyst content from tool results
        chart_spec = None
        insights_list = None
        suggested_followups = None

        # Extract from tool results in message history
        chart_spec = self._extract_chart_spec(final_state)
        insights_list = self._extract_insights(final_state)
        suggested_followups = self._extract_suggested_followups(final_state)

        result = {
            "success": final_state.get("status") != "error",
            "sql": final_state.get("sql"),
            "execution_result": execution_result,
            "data_summary": data_summary,  # Accurate summary from actual data OR agent message
            "agent_message": agent_message,  # Direct message from agent (refusals, explanations)
            "tools_used": final_state.get("tools_used", []),
            "tool_calls_count": final_state.get("tool_calls_count", 0),
            "failed_attempts": final_state.get("failed_attempts", []),
            "usage": final_state.get("total_usage"),
            "iterations": final_state.get("iteration", 0),
            "error": final_state.get("error"),
            "thread_id": self.thread_id,
            "resumed": resumed,
            "checkpointer_backend": get_checkpointer_backend(),
            "total_time_ms": int((time.time() - start_time) * 1000),
        }

        # Add analyst mode fields if present
        if chart_spec:
            result["chart"] = chart_spec
        if insights_list:
            result["insights"] = insights_list
        if suggested_followups:
            result["suggestions"] = suggested_followups

        return result

    async def get_state(self) -> Optional[Dict[str, Any]]:
        """
        Get the current checkpoint state for this thread.

        Returns:
            Current state dict or None if no checkpoint exists
        """
        if not self.checkpointer:
            return None

        try:
            config = get_checkpoint_config(self.thread_id)
            state = await self.graph.aget_state(config)
            return state.values if state else None
        except Exception as e:
            logger.warning(f"Failed to get checkpoint state: {e}")
            return None

    async def get_history(self) -> List[Dict[str, Any]]:
        """
        Get the checkpoint history for this thread.

        Returns:
            List of checkpoint states (most recent first)
        """
        if not self.checkpointer:
            return []

        try:
            config = get_checkpoint_config(self.thread_id)
            history = []
            async for state in self.graph.aget_state_history(config):
                history.append({
                    "iteration": state.values.get("iteration", 0),
                    "status": state.values.get("status"),
                    "tools_used": state.values.get("tools_used", []),
                    "checkpoint_id": state.config.get("configurable", {}).get("checkpoint_id"),
                })
            return history
        except Exception as e:
            logger.warning(f"Failed to get checkpoint history: {e}")
            return []

    async def run_streaming(
        self,
        question: str,
        resume: bool = False,
        conversation_context: Optional[List[Dict]] = None,
        data_dictionary_context: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent with real-time streaming of events.

        Uses distributed locking to prevent concurrent agent runs for the same session.

        Yields events as they happen:
        - {"event": "thinking", "content": "...", "iteration": N}
        - {"event": "tool_call", "tool_name": "...", "tool_args": {...}}
        - {"event": "tool_result", "tool_name": "...", "content": "..."}
        - {"event": "sql_generated", "sql": "..."}
        - {"event": "complete", "result": {...}}
        - {"event": "error", "error": "..."}

        Args:
            question: User's natural language question
            data_dictionary_context: Business terms and column descriptions from data dictionary
            resume: If True, attempt to resume from last checkpoint
            conversation_context: Previous conversation turns for context

        Yields:
            Event dictionaries compatible with ChatStreamEvent
        """
        start_time = time.time()

        # Acquire distributed lock to prevent concurrent runs for same session
        lock = DistributedLock(
            f"session:{self.session_id}:agent",
            ttl_seconds=600,  # 10 minute max for agent runs
            acquire_timeout=5.0,  # Don't wait long, reject if busy
        )

        acquired = await lock.acquire()
        if not acquired:
            logger.warning(
                f"Agent streaming rejected: session {self.session_id[:8]} already has active agent"
            )
            yield {
                "event": "error",
                "error": "Another agent is already running for this session. Please wait.",
                "thread_id": self.thread_id,
                "total_time_ms": int((time.time() - start_time) * 1000),
            }
            return

        # Build config for checkpointing
        config = get_checkpoint_config(self.thread_id) if self.checkpointer else None

        # Phase 2 Day 3: declared before the try so the finally block can
        # always reach it even if lock acquisition is the only thing that
        # happened before an exception.
        extender_task: Optional[asyncio.Task] = None

        try:
            # Handle resume case
            initial_state: Optional[Union[ReActState, Dict[Any, Any]]] = None
            actually_resuming = False  # Track if we found a checkpoint to resume

            if resume and self.checkpointer and config:
                try:
                    state = await self.graph.aget_state(config)
                    if state and state.values:
                        logger.info(
                            "Resuming from checkpoint",
                            thread_id=self.thread_id,
                            iteration=state.values.get("iteration", 0),
                        )
                        # Phase 2 Day 2: build a fresh state dict rather than
                        # mutating the checkpointer's returned object.
                        initial_state = ReActAgentNodes._safely_resume_state(
                            state.values, question
                        )
                        actually_resuming = True  # We found a checkpoint
                        yield {
                            "event": "thinking",
                            "content": "Resuming from previous state...",
                            "iteration": state.values.get("iteration", 0),
                        }
                    else:
                        logger.info("Resume requested but no checkpoint found, starting fresh")
                except Exception as e:
                    logger.warning(f"Failed to resume from checkpoint: {e}")

            # Fresh run if not resuming (or if resume was requested but no checkpoint found)
            if not actually_resuming:
                # Build contextual system prompt with conversation history and data dictionary
                system_prompt = self._build_contextual_system_prompt(
                    conversation_context, data_dictionary_context
                )

                initial_state = ReActState(
                    messages=[
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=question),
                    ],
                    question=question,
                    sql=None,
                    execution_result=None,
                    tools_used=[],
                    tool_calls_count=0,
                    failed_attempts=[],
                    total_usage=None,
                    status="thinking",
                    error=None,
                    iteration=0,
                    max_iterations=self.max_iterations,
                    consecutive_no_tools=0,
                    consecutive_failures=0,
                    iterations_without_execution=0,
                    sql_attempts_failed=0,
                    # Wall-clock budget on streaming runs (same
                    # behaviour as the non-streaming path; 0 disables).
                    wall_clock_start=time.monotonic(),
                    wall_clock_budget_seconds=float(
                        settings.AGENT_WALL_CLOCK_BUDGET_SECONDS
                    ),
                )

            yield {
                "event": "thinking",
                "content": "Analyzing your question...",
                "progress": 0.1,
            }

            # Track state for event generation
            last_iteration = 0
            emitted_tool_call_ids = set()  # Track emitted tool calls to avoid duplicates
            tool_calls_count = 0  # Track total tool calls for progress calculation
            final_state = {}  # Accumulate state updates (merge, don't replace)

            # Stream using LangGraph's astream
            # Note: We always pass initial_state (which is modified state if resuming)
            # Don't pass None as it would reload stale checkpoint, losing appended question
            stream_config = config if config else {}

            # Phase 2 Day 3: lock extension runs in a dedicated background
            # task rather than inline on every event. The event-driven
            # approach missed quiet periods (long LLM calls / multi-minute
            # data-lake queries) and let the 120s TTL expire silently.
            # Fall back to inline extension if the flag is off.
            last_extend_time = time.time()
            EXTEND_INTERVAL = 120  # Legacy inline extension interval
            if settings.FIX_BACKGROUND_LOCK_EXTENSION:
                extender_task = asyncio.create_task(
                    _background_lock_extender(
                        lock,
                        interval=60.0,  # Refresh every 60s — well inside the 120s TTL
                        ttl=300,        # Extend to 5 min each refresh
                        session_id=self.session_id,
                    ),
                    name=f"lock_extender:{self.session_id}",
                )

            # Phase 3a Day 2 + 3b.2: wrap the graph's async generator
            # with the heartbeat + progress merger so quiet periods
            # (tool executions running for minutes) don't leave the SSE
            # stream idle AND native-async drivers (BigQuery,
            # Snowflake) can push progress metrics through a queue on
            # the ToolContext. Some proxies close idle SSE after ~60s;
            # heartbeats every 15s keep the connection alive without
            # adding user-visible chat events.
            progress_queue: Optional[asyncio.Queue] = None
            if settings.FIX_QUERY_PROGRESS_EVENTS and self.tool_context is not None:
                progress_queue = asyncio.Queue()

                def _emit_progress(payload: Dict[str, Any]) -> None:
                    # put_nowait is safe from the executor's coroutine;
                    # an unbounded queue is fine because progress events
                    # are rate-limited by the driver itself (typically
                    # one per second).
                    try:
                        progress_queue.put_nowait(payload)
                    except Exception as e:
                        logger.warning(f"progress_emitter put_nowait failed: {e}")

                self.tool_context.progress_emitter = _emit_progress

            graph_stream = self.graph.astream(
                initial_state, stream_config, stream_mode="updates"
            )
            if settings.FIX_SSE_HEARTBEAT:
                stream_source = _merge_stream_with_heartbeat(
                    graph_stream,
                    interval=SSE_HEARTBEAT_INTERVAL,
                    start_time=time.monotonic(),
                    progress_queue=progress_queue,
                )
            else:
                stream_source = graph_stream

            async for event in stream_source:
                # Heartbeats and query_progress pass straight through:
                # they already have the right SSE shape and shouldn't
                # flow through the per-node processing below.
                if isinstance(event, dict) and event.get("event") in (
                    "heartbeat",
                    "query_progress",
                ):
                    yield event
                    continue

                # Legacy inline extension path when background task is disabled
                if (
                    not settings.FIX_BACKGROUND_LOCK_EXTENSION
                    and time.time() - last_extend_time > EXTEND_INTERVAL
                ):
                    extended = await lock.extend(300)
                    if not extended:
                        logger.error(f"Lock extension failed for session {self.session_id} - lock may have been stolen")
                        yield {"event": "error", "error": "Session lock lost during processing. Please retry."}
                        return
                    last_extend_time = time.time()

                # Background extender may have died (extend returned False).
                # Surface that before proceeding — otherwise we'd keep
                # running with no cross-worker protection.
                if extender_task is not None and extender_task.done():
                    exc = extender_task.exception()
                    if exc is not None and not isinstance(exc, asyncio.CancelledError):
                        logger.error(
                            f"Background lock extender failed for session "
                            f"{self.session_id}: {exc}"
                        )
                    yield {
                        "event": "error",
                        "error": "Session lock lost during processing. Please retry.",
                    }
                    return

                # event is a dict with node_name -> state_update
                for node_name, state_update in event.items():
                    if node_name == "agent":
                        # Agent node processed - check for tool calls or thinking
                        iteration = state_update.get("iteration", last_iteration)
                        status = state_update.get("status", "thinking")

                        # Check if agent provided a direct response (e.g., refusal, explanation)
                        agent_response = state_update.get("agent_response")
                        if agent_response:
                            yield {
                                "event": "thinking",
                                "content": agent_response,
                                "iteration": iteration,
                                "progress": 0.9,
                            }

                        # Check for new messages with tool calls
                        new_messages = state_update.get("messages", [])
                        for msg in new_messages:
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                # Emit tool_call events for each NEW tool being called
                                for tc in msg.tool_calls:
                                    tool_call_id = tc.get("id") or f"{tc.get('name')}_{iteration}_{tool_calls_count}"

                                    # Skip if already emitted (handles resume/replay scenarios)
                                    if tool_call_id in emitted_tool_call_ids:
                                        continue

                                    emitted_tool_call_ids.add(tool_call_id)
                                    tool_calls_count += 1

                                    # CLI-style step info
                                    tool_name = tc.get("name")
                                    tool_args = tc.get("args", {})
                                    description = get_tool_description(tool_name, tool_args)

                                    yield {
                                        "event": "tool_call",
                                        "tool_name": tool_name,
                                        "tool_args": tool_args,
                                        "step_number": tool_calls_count,
                                        "description": description,
                                        "iteration": iteration,
                                        "status": status,
                                        "progress": min(0.2 + iteration * 0.1, 0.7),
                                    }
                            elif msg.content and isinstance(msg, AIMessage):
                                # AI thinking/reasoning - keep brief
                                content_preview = msg.content[:150] + "..." if len(msg.content) > 150 else msg.content
                                yield {
                                    "event": "thinking",
                                    "content": content_preview,
                                    "iteration": iteration,
                                    "progress": min(0.2 + iteration * 0.1, 0.7),
                                }

                        # Check if SQL was generated
                        sql = state_update.get("sql")
                        if sql:
                            yield {
                                "event": "sql_generated",
                                "sql": sql,
                                "progress": 0.8,
                            }

                        last_iteration = iteration

                    elif node_name == "tools":
                        # Tool node processed - emit tool_result events
                        logger.debug(f"stream: tools node update keys: {list(state_update.keys())}")
                        logger.debug(f"stream: tools node sql in update: {bool(state_update.get('sql'))}")
                        new_messages = state_update.get("messages", [])
                        for msg in new_messages:
                            if isinstance(msg, ToolMessage):
                                tool_name = msg.name or "unknown"
                                # Handle both string and list content types
                                raw_content = msg.content
                                content_str = raw_content if isinstance(raw_content, str) else str(raw_content)

                                # Create CLI-style summary of result
                                summary = format_tool_result_summary(tool_name, content_str)

                                # Truncate full content for streaming
                                stream_limit = settings.AGENT_STREAM_TOOL_OUTPUT
                                if len(content_str) > stream_limit:
                                    content_str = content_str[:stream_limit] + "...[truncated]"

                                yield {
                                    "event": "tool_result",
                                    "tool_name": tool_name,
                                    "summary": summary,  # CLI-style brief result
                                    "content": content_str,  # Full content (truncated)
                                    "progress": min(0.3 + last_iteration * 0.1, 0.7),
                                }

                        # Check if SQL was set by execute_sql tool
                        sql = state_update.get("sql")
                        if sql:
                            yield {
                                "event": "sql_generated",
                                "sql": sql,
                                "progress": 0.8,
                            }

                        # Check for execution result
                        exec_result = state_update.get("execution_result")
                        if exec_result and exec_result.get("success"):
                            row_count = exec_result.get("row_count", 0)
                            yield {
                                "event": "executed",
                                "content": f"Query returned {row_count} rows",
                                "row_count": row_count,
                                "progress": 0.85,
                            }

                    # Update tracking - merge state updates to accumulate all fields
                    if state_update:
                        final_state.update(state_update)

            # Get final state for result (prefer full checkpointer state if available)
            accumulated_exec_result = final_state.get("execution_result") if final_state else None
            logger.info(f"Streaming: accumulated state has exec_result={accumulated_exec_result is not None}")

            if config:
                try:
                    full_state = await self.graph.aget_state(config)
                    if full_state and full_state.values:
                        checkpointer_exec_result = full_state.values.get("execution_result")
                        logger.info(f"Streaming: checkpointer state has exec_result={checkpointer_exec_result is not None}")
                        # Merge: prefer accumulated exec_result if checkpointer doesn't have it
                        if accumulated_exec_result and not checkpointer_exec_result:
                            logger.info("Using accumulated exec_result (checkpointer missing it)")
                            full_state.values["execution_result"] = accumulated_exec_result
                        final_state = full_state.values
                except Exception as e:
                    logger.warning(f"Failed to get checkpointer state: {e}")

            # Build final result
            if final_state:
                result = self._build_result(final_state, start_time)

                # Generate data-driven summary from actual results
                exec_result = final_state.get("execution_result")
                logger.info(f"Streaming final: exec_result exists={exec_result is not None}, "
                            f"success={exec_result.get('success') if exec_result else None}, "
                            f"row_count={exec_result.get('row_count') if exec_result else None}, "
                            f"rows_len={len(exec_result.get('rows', [])) if exec_result else 0}")

                agent_message = final_state.get("agent_response")
                if exec_result and exec_result.get("success"):
                    result["data_summary"] = generate_data_summary(question, exec_result)
                elif agent_message:
                    # Agent provided a direct response (e.g., refusal, explanation)
                    result["data_summary"] = agent_message
                    logger.info("Using agent_response as data_summary")
                elif exec_result:
                    logger.warning(f"exec_result exists but success={exec_result.get('success')}")
                    result["data_summary"] = "Query execution failed. Check the SQL and try again."
                else:
                    # Try to extract last assistant message
                    messages = final_state.get("messages", [])
                    for msg in reversed(messages):
                        if isinstance(msg, AIMessage) and msg.content:
                            result["data_summary"] = msg.content
                            logger.info("Extracted data_summary from last AIMessage")
                            break
                    else:
                        logger.warning("No exec_result, agent_response, or AIMessage found")
                        result["data_summary"] = "No query was executed."

                # Include total steps for CLI display
                result["total_steps"] = tool_calls_count

                yield {
                    "event": "complete",
                    "result": result,
                    "total_steps": tool_calls_count,
                    "progress": 1.0,
                }
            else:
                yield {
                    "event": "error",
                    "error": "Agent completed without final state",
                    "progress": 1.0,
                }

        except Exception as e:
            logger.error("ReAct agent streaming failed", error=str(e), exc_info=True)
            yield {
                "event": "error",
                "error": str(e),
                "thread_id": self.thread_id,
                "total_time_ms": int((time.time() - start_time) * 1000),
            }
        finally:
            # Phase 2 Day 3: stop the background lock extender before
            # releasing the lock so it doesn't race with the release.
            if extender_task is not None and not extender_task.done():
                extender_task.cancel()
                try:
                    await extender_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(
                        f"Background lock extender cleanup raised for "
                        f"session {self.session_id}: {e}"
                    )
            await lock.release()


async def run_react_agent(
    question: str,
    llm_config: LLMConfig,
    db_config: DatabaseConfig,
    session_id: str,
    max_iterations: int = 10,
    on_event: Optional[Callable[[Dict], None]] = None,
    resume: bool = False,
    conversation_context: Optional[List[Dict]] = None,
    data_dictionary_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience function to run the ReAct agent.

    Args:
        question: User's natural language question
        llm_config: LLM configuration
        db_config: Database configuration
        session_id: Session ID
        max_iterations: Maximum iterations
        on_event: Optional event callback
        resume: Whether to resume from checkpoint (for follow-ups)
        conversation_context: Previous conversation turns for context
        data_dictionary_context: Business terms and column descriptions from data dictionary

    Returns:
        Agent result dict
    """
    agent = ReActAgent(
        llm_config=llm_config,
        db_config=db_config,
        session_id=session_id,
        max_iterations=max_iterations,
    )

    return await agent.run(
        question,
        on_event,
        resume=resume,
        conversation_context=conversation_context,
        data_dictionary_context=data_dictionary_context,
    )


