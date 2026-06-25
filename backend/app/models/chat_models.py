"""
QueryfyAI - Unified Chat Models

Single unified chat endpoint that handles all query interactions:
- Standard SQL generation
- AI Analyst mode with insights
- Follow-up questions (automatic via session context)
- Streaming responses

Everything goes through POST /chat
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMode(str, Enum):
    """Response mode for chat endpoint."""
    STANDARD = "standard"  # Returns SQL query only
    ANALYST = "analyst"    # Returns insight-rich answer with SQL


class ChatRequest(BaseModel):
    """
    Unified chat request for all query interactions.

    Examples:
        # Standard SQL generation
        {"session_id": "abc", "message": "Show top 10 customers"}

        # Analyst mode
        {"session_id": "abc", "message": "Who are my best customers?", "mode": "analyst"}

        # Follow-up (just send another message - context from session)
        {"session_id": "abc", "message": "Break that down by region", "mode": "analyst"}

        # Streaming
        {"session_id": "abc", "message": "Monthly sales", "stream": true}
    """
    session_id: str = Field(
        description="Active session ID for database connection"
    )
    message: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="Natural language question or request"
    )
    mode: ChatMode = Field(
        default=ChatMode.STANDARD,
        description="Response mode: 'standard' (SQL only) or 'analyst' (insights + SQL)"
    )
    stream: bool = Field(
        default=False,
        description="Stream response via Server-Sent Events"
    )
    include_reasoning: bool = Field(
        default=False,
        description="Include reasoning/thought process in response (analyst mode)"
    )
    include_chart: bool = Field(
        default=True,
        description="Auto-generate chart if data is suitable (analyst mode)"
    )

    # === Conversation Control ===
    continue_conversation: bool = Field(
        default=True,
        description="Continue from previous conversation context. Set to False to start fresh."
    )


class ChartSpec(BaseModel):
    """Chart specification for frontend visualization."""
    chart_type: str = Field(description="Type: bar, line, pie, scatter, area")
    title: Optional[str] = None
    x_axis: str = Field(description="Column for X axis")
    y_axis: str = Field(description="Column for Y axis")
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    data: List[Dict[str, Any]] = Field(default_factory=list)
    series: Optional[List[str]] = None
    options: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """
    Unified chat response for all modes.

    Standard mode populates: sql, is_valid, query_type, explanation
    Analyst mode adds: answer, key_findings, confidence, chart, raw_result

    Frontend determines display by checking if 'answer' is present.
    """

    # === Response Status ===
    success: bool = Field(default=True, description="Whether request succeeded")
    mode: ChatMode = Field(description="Mode used for this response")

    # === SQL Generation (present on success) ===
    sql: Optional[str] = Field(default=None, description="Generated SQL query")
    is_valid: bool = Field(default=True, description="SQL syntax validity")
    query_type: Optional[str] = Field(default=None, description="Query type: SELECT, INSERT, etc.")
    explanation: Optional[str] = Field(default=None, description="SQL explanation")

    # === Analyst Mode Fields ===
    answer: Optional[str] = Field(
        default=None,
        description="Natural language answer (analyst mode only)"
    )
    key_findings: List[str] = Field(
        default_factory=list,
        description="Bullet point insights (analyst mode only)"
    )
    insights: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Structured insights for the frontend's InsightCard "
            "renderer — each entry has type/severity/title/description/"
            "recommendations/metrics/column_name. Includes LLM "
            "business_insight(s) and statistical-detector findings. "
            "``key_findings`` is a flattened string view of the same "
            "data kept for backward compat; this field is the rich one."
        ),
    )
    narrator_status: Optional[str] = Field(
        default=None,
        description=(
            "Observability signal from execute_and_analyze. One of: "
            "'ran_successfully', 'ran_but_empty', 'skipped_no_llm_config', "
            "'ran_without_question_anchor'. Lets the UI distinguish "
            "'no patterns were found' from silent narrator degradation "
            "(missing LLM config, parse failure, prompt-less narration) "
            "and render an honest fallback instead of a blank insights "
            "section."
        ),
    )
    insights_type: Optional[str] = Field(
        default=None,
        description=(
            "'llm_business_plus_detectors' when the LLM narrator "
            "produced business insights on top of statistical detectors; "
            "'statistical_only' when only deterministic detector "
            "findings are present."
        ),
    )
    sampling_used: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Sampling metadata hoisted out of the insights list. "
            "``None`` when the full result was "
            "analysed. When sampling fired: "
            "{used: True, sample_size, total_rows, stats_on_full_dataset, "
            "warnings: [...], recommendation: str|None}. Frontend "
            "renders this as its own banner so real insights don't "
            "compete visually with meta-commentary."
        ),
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score 0-1 (analyst mode only)"
    )
    chart: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Chart specification (analyst mode only)"
    )
    raw_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Query execution results: {columns, rows, row_count}"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Reasoning trace when include_reasoning=true"
    )
    data_quality: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Data quality assessment (analyst mode): {overall_score, completeness, issues}"
    )
    suggestions: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Follow-up question suggestions (analyst mode only)"
    )

    # === Tool Usage (Phase 2) ===
    tools_used: List[str] = Field(
        default_factory=list,
        description="List of tools used during generation (e.g., search_tables, lookup_business_term)"
    )

    # === Metadata ===
    query_id: Optional[str] = Field(default=None, description="Unique query identifier")
    sql_hash: Optional[str] = Field(default=None, description="SQL hash for verification")
    # tool_calls_count, execution_time_ms, and usage were produced
    # but never consumed by any client. Dropped from the response;
    # internal accounting still lives on LLMMetricsTracker and the
    # structured cache logs.

    # === Conversation Metadata ===
    is_follow_up: bool = Field(
        default=False,
        description="Whether this query was detected as a follow-up to previous query"
    )
    conversation_turn: int = Field(
        default=1,
        description="Turn number in the current conversation (incremental)"
    )

    # === Errors ===
    error: Optional[str] = Field(default=None, description="Error message if failed")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings")


class ChatStreamEvent(BaseModel):
    """
    Server-Sent Event for streaming chat responses.

    Event flow:
    - Standard: thinking -> sql_chunk* -> sql_complete -> done
    - Analyst: thinking -> tool_call* -> tool_result* -> sql -> executing -> analyzing -> done

    Event types:
    - thinking: Agent is processing/reasoning
    - sql_chunk: Partial SQL text (for progressive display during generation)
    - sql_complete: Full SQL after validation (standard mode)
    - sql: Full SQL (analyst mode, after agent completes)
    - tool_call: Agent is calling a tool (includes tool name and arguments)
    - tool_result: Tool returned a result (includes truncated result)
    - executing: Running the SQL query
    - analyzing: Generating insights from results
    - done: Complete response with full metadata
    - error: Error occurred
    """
    event: str = Field(
        description="Event type: thinking, sql_chunk, sql_complete, sql, tool_call, tool_result, executing, analyzing, done, error"
    )
    content: Optional[str] = Field(default=None, description="Event content/message")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Event data payload")
    progress: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Progress 0-1")
    tool_name: Optional[str] = Field(default=None, description="Tool name (for tool_call/tool_result events)")
    tool_args: Optional[Dict[str, Any]] = Field(default=None, description="Tool arguments (for tool_call events)")
    step_number: Optional[int] = Field(default=None, description="Step number in agent workflow (for tool_call events)")
    description: Optional[str] = Field(default=None, description="Human-readable step description (for tool_call events)")
    summary: Optional[str] = Field(default=None, description="Tool result summary (for tool_result events)")
