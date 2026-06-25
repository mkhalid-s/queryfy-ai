"""
QueryfyAI - AI Data Analyst Models

Models for the AI Data Analyst feature that provides insight-rich answers
instead of just SQL queries.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ============== Analysis Models ==============
class Insight(BaseModel):
    """Model for a single insight detected in query results."""
    type: Literal["concentration", "trend", "anomaly", "comparison"] = Field(
        description="Type of insight"
    )
    severity: Literal["high", "medium", "low"] = Field(
        description="Severity level of the insight"
    )
    title: str = Field(
        description="Short description of the insight"
    )
    description: str = Field(
        description="Detailed explanation"
    )
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Supporting metrics and data"
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="Suggested actions based on this insight"
    )


class DataQualityReport(BaseModel):
    """Model for data quality assessment."""
    overall_score: int = Field(
        ge=0,
        le=100,
        description="Overall quality score (0-100)"
    )
    completeness: float = Field(
        ge=0.0,
        le=100.0,
        description="Percentage of non-null values"
    )
    null_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="Percentage of null values"
    )
    duplicate_count: int = Field(
        ge=0,
        description="Number of duplicate rows"
    )
    outlier_count: int = Field(
        ge=0,
        description="Number of outlier values"
    )
    issues: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of quality issues detected"
    )
    column_quality: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-column quality metrics"
    )


class Comparison(BaseModel):
    """Model for period/segment comparison results."""
    type: str = Field(
        description="Type of comparison (MoM, YoY, QoQ, segment_vs_avg, etc.)"
    )
    metric: str = Field(
        description="The metric being compared"
    )
    current: float = Field(
        description="Current period value"
    )
    previous: Optional[float] = Field(
        default=None,
        description="Previous period value (for temporal comparisons)"
    )
    change_pct: float = Field(
        description="Percentage change"
    )
    interpretation: str = Field(
        description="Human-readable interpretation of the change"
    )
    significance: Literal["not_significant", "moderate", "significant", "highly_significant"] = Field(
        description="Statistical significance of the change"
    )
    direction: Literal["increase", "decrease", "stable"] = Field(
        description="Direction of change"
    )


class ChartRecommendation(BaseModel):
    """Model for chart type recommendation."""
    recommended_chart: str = Field(
        description="Recommended chart type"
    )
    rationale: str = Field(
        description="Explanation of why this chart type"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Chart configuration (axes, labels, options)"
    )
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Alternative chart types with scores"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Potential issues or warnings"
    )


class ChartAnnotation(BaseModel):
    """Model for chart annotation."""
    type: Literal["trend_line", "benchmark", "outlier", "callout", "reference_area", "arrow"] = Field(
        description="Type of annotation"
    )
    text: Optional[str] = Field(
        default=None,
        description="Annotation text"
    )
    description: Optional[str] = Field(
        default=None,
        description="Detailed description"
    )
    position: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Position information (x, y coordinates, etc.)"
    )
    style: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Styling information (color, size, etc.)"
    )


# ============== Chart Specification ==============
class ChartType(str, Enum):
    """Supported chart types for visualization."""
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    AREA = "area"
    HORIZONTAL_BAR = "horizontal_bar"


class ChartSpec(BaseModel):
    """
    Chart specification for frontend rendering.

    Compatible with the existing ChartView component.
    """
    chart_type: ChartType = Field(
        description="Type of chart to render"
    )
    title: Optional[str] = Field(
        default=None,
        description="Chart title"
    )
    x_axis: str = Field(
        description="Column name for X axis"
    )
    y_axis: str = Field(
        description="Column name for Y axis"
    )
    x_label: Optional[str] = Field(
        default=None,
        description="Display label for X axis"
    )
    y_label: Optional[str] = Field(
        default=None,
        description="Display label for Y axis"
    )
    data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Chart data points"
    )
    series: Optional[List[str]] = Field(
        default=None,
        description="Multiple series/columns for multi-line charts"
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional chart options (colors, legends, etc.)"
    )


# ============== Analyst Request ==============
class AnalystRequest(BaseModel):
    """
    Request for AI Data Analyst mode.

    Extends the standard query with analyst-specific options.
    """
    session_id: str = Field(
        description="Active session ID"
    )
    question: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="Natural language question"
    )

    # Mode options
    include_chart: bool = Field(
        default=True,
        description="Auto-generate chart if data is suitable"
    )
    include_reasoning: bool = Field(
        default=False,
        description="Include reasoning trace in response"
    )

    # Advanced options (Phase 3)
    allow_python: bool = Field(
        default=False,
        description="Enable Python sandbox for advanced analytics"
    )


# ============== Analyst Response ==============
class AnalystResponse(BaseModel):
    """
    AI Data Analyst response - answer-centric, not SQL-centric.

    The primary output is a natural language answer with key findings.
    SQL and raw data are secondary, available in collapsible tabs.
    """

    # === Primary Output (Always shown in UI) ===
    answer: str = Field(
        description="Natural language answer to the user's question"
    )
    key_findings: List[str] = Field(
        default_factory=list,
        description="3-5 bullet point insights from the data"
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score (0-1) in the answer"
    )

    # === Visualization (When applicable) ===
    chart: Optional[ChartSpec] = Field(
        default=None,
        description="Auto-generated chart specification"
    )

    # === Secondary (Collapsible tabs in UI) ===
    sql: Optional[str] = Field(
        default=None,
        description="Generated SQL query"
    )
    raw_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full query results (columns, rows, row_count)"
    )
    data_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Summary statistics (min, max, avg, etc.)"
    )

    # === Reasoning (For transparency) ===
    reasoning: Optional[str] = Field(
        default=None,
        description="How the answer was derived (if include_reasoning=True)"
    )
    tools_used: List[str] = Field(
        default_factory=list,
        description="Which tools were called during analysis"
    )

    # === Metadata ===
    query_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for this query"
    )
    sql_hash: Optional[str] = Field(
        default=None,
        description="Hash for SQL integrity verification"
    )
    execution_time_ms: Optional[int] = Field(
        default=None,
        description="Total execution time in milliseconds"
    )
    usage: Optional[Dict[str, Any]] = Field(
        default=None,
        description="LLM token usage and cost data"
    )

    # === Error handling ===
    error: Optional[str] = Field(
        default=None,
        description="Error message if analysis failed"
    )
    warnings: Optional[List[str]] = Field(
        default=None,
        description="Non-fatal warnings during analysis"
    )


# ============== Streaming Events ==============
class AnalystStreamEvent(BaseModel):
    """
    SSE event for streaming analyst responses.

    Provides real-time updates during multi-step analysis.
    """
    event_type: Literal[
        "thinking",      # Agent is reasoning
        "tool_call",     # Calling a tool
        "tool_result",   # Tool returned result
        "sql",           # SQL generated
        "executing",     # Executing query
        "result",        # Query results ready
        "answering",     # Generating answer
        "chart",         # Chart generated
        "done",          # Analysis complete
        "error"          # Error occurred
    ] = Field(description="Type of streaming event")

    content: Optional[str] = Field(
        default=None,
        description="Event content (message, SQL, etc.)"
    )
    tool_name: Optional[str] = Field(
        default=None,
        description="Name of tool being called (for tool_call events)"
    )
    progress: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Progress indicator (0-1)"
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional event data"
    )
