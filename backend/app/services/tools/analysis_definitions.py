"""
Analysis Tool Definitions

JSON Schema definitions for analysis tools.
These descriptions guide the LLM agent on WHEN and HOW to use each tool.
"""

from app.services.tools.registry import ToolDefinition

# =============================================================================
# ANALYSIS TOOLS - For intelligent data analysis
# =============================================================================

DETECT_INSIGHTS = ToolDefinition(
    name="detect_insights",
    description="""Find patterns, trends, anomalies, and risks in query results.

Use this tool AFTER executing SQL to discover:
- **Concentration risks** (top-N queries: Are top customers/products driving most value?)
- **Trends** (time series: Is it growing? Accelerating? Declining?)
- **Anomalies** (outliers: Which values are unusual, >3σ from mean?)
- **Comparisons** (segments: Do groups differ significantly?)

WHEN TO USE:
- Top-N queries (e.g., "top 10 customers") → check concentration
- Time series data (e.g., "monthly sales") → detect trends
- Large datasets (>100 rows) → find anomalies
- Segment analysis (e.g., "by region") → compare groups

Parameters:
- data: JSON string of query results (from execute_sql)
- analysis_types: Optional list ["concentration", "trend", "anomaly", "comparison"] or ["all"]

Returns: JSON with list of insights, each containing:
  - type: str (concentration, trend, anomaly, comparison)
  - severity: str (high, medium, low)
  - title: str (short description)
  - description: str (detailed explanation)
  - metrics: dict (supporting data)
  - recommendations: list (suggested actions)

Example:
  detect_insights(data=results, analysis_types=["concentration"])
  → Finds "Top 3 customers = 40% of revenue (concentration risk)"
    """,
    parameters={
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "JSON string of query results (list of row dictionaries)"
            },
            "analysis_types": {
                "type": "array",
                "items": {"type": "string", "enum": ["concentration", "trend", "anomaly", "comparison", "all"]},
                "description": "Types of analysis to run (default: all)",
                "default": ["all"]
            }
        },
        "required": ["data"]
    }
)


ANALYZE_STATISTICS = ToolDefinition(
    name="analyze_statistics",
    description="""Compute advanced statistics beyond basic aggregations (sum, avg, min, max).

Use this tool when:
- User asks about **distribution, spread, or variability**
- Need **percentiles** (median, quartiles, P90, P95, P99)
- Want to **quantify patterns** (std dev, IQR, coefficient of variation)
- Checking **concentration** (Gini coefficient, HHI, top-N percentages)
- Understanding **data characteristics** (skewness, outliers)

Returns comprehensive statistics for numeric columns:
- Central tendency: mean, median
- Dispersion: std_dev, variance, range, IQR
- Distribution: skewness, percentiles (P10, P25, P50, P75, P90, P95, P99)
- Concentration: Gini coefficient, HHI, top 10/20/50% values

WHEN TO USE:
- Questions about "how spread out" data is
- Need to report percentiles (e.g., "P95 latency")
- Analyzing inequality or concentration
- Understanding if distribution is normal or skewed

Example:
  analyze_statistics(data=results, columns=["revenue", "profit"])
  → Returns percentiles, std_dev, Gini, concentration metrics
    """,
    parameters={
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "JSON string of query results"
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column names to analyze (default: all numeric columns)"
            }
        },
        "required": ["data"]
    }
)


CHECK_DATA_QUALITY = ToolDefinition(
    name="check_data_quality",
    description="""Assess data quality and completeness of query results.

Use this tool BEFORE making strong claims:
- Large result sets (>50 rows) → check quality first
- Before reporting insights with high confidence
- When you see potential data issues (nulls, outliers)
- To explain confidence level in analysis

Reports:
- **Overall quality score** (0-100)
- **Completeness**: percentage of non-null values
- **Duplicates**: number of duplicate rows detected
- **Outliers**: extreme values that may affect analysis
- **Issues**: List of quality problems by severity (high, medium, low)
- **Per-column quality**: null percentage, unique values, data type

WHEN TO USE:
- Before making definitive statements ("revenue is $X")
- Large datasets where quality matters
- When you suspect data issues
- To be transparent about data limitations

Example:
  check_data_quality(data=results)
  → Returns: {"overall_score": 92, "completeness": 98%, "issues": [...]}
    """,
    parameters={
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "JSON string of query results"
            }
        },
        "required": ["data"]
    }
)


COMPARE_PERIODS = ToolDefinition(
    name="compare_periods",
    description="""Compare time periods or segments to show change over time.

Use this tool for:
- **Time series analysis**: MoM, YoY, QoQ, WoW comparisons
- **Growth analysis**: Calculate percentage changes
- **Segment comparisons**: Compare groups to overall average

Comparison types:
- "MoM": Month-over-Month
- "YoY": Year-over-Year
- "QoQ": Quarter-over-Quarter
- "WoW": Week-over-Week
- "segment_vs_avg": Compare segments to average

Returns for each metric:
- Current and previous values
- Absolute and percentage change
- Interpretation (e.g., "Strong growth YoY", "Concerning decline MoM")
- Significance level (not_significant, moderate, significant, highly_significant)

WHEN TO USE:
- Questions with "change", "growth", "trend", "vs last year"
- After detecting trends with detect_insights
- To quantify and interpret temporal changes

Example:
  compare_periods(current_data=results, comparison_type="YoY")
  → Returns: {"change_pct": 23.5, "interpretation": "Strong growth YoY", "significance": "significant"}
    """,
    parameters={
        "type": "object",
        "properties": {
            "current_data": {
                "type": "string",
                "description": "JSON string of current period data"
            },
            "comparison_type": {
                "type": "string",
                "enum": ["MoM", "YoY", "QoQ", "WoW", "segment_vs_avg"],
                "description": "Type of comparison to perform"
            },
            "previous_data": {
                "type": "string",
                "description": "Optional JSON string of previous period data (if already fetched)"
            },
            "original_sql": {
                "type": "string",
                "description": "Optional original SQL query (to fetch previous period if needed)"
            }
        },
        "required": ["current_data", "comparison_type"]
    }
)


SUGGEST_FOLLOWUPS = ToolDefinition(
    name="suggest_followups",
    description="""Generate smart follow-up questions based on insights discovered.

Use this tool AFTER finding interesting patterns with detect_insights:
- High concentration → suggest drilling into top items
- Trends detected → suggest period comparisons
- Anomalies found → suggest investigating outliers
- Segment differences → suggest analyzing each segment

Generates 3-5 follow-up suggestions, each with:
- question: Specific natural language question
- rationale: Why this question is relevant (based on insights)
- priority: high, medium, low
- category: drill_down, comparison, investigation

WHEN TO USE:
- After detect_insights finds high/medium severity issues
- To help user explore data more deeply
- End of analysis to suggest next steps

Example:
  suggest_followups(insights=insights_json, query_context="top customers query")
  → Returns: [{"question": "Show monthly trend for top 3 customers", "priority": "high"}]
    """,
    parameters={
        "type": "object",
        "properties": {
            "insights": {
                "type": "string",
                "description": "JSON string from detect_insights tool"
            },
            "query_context": {
                "type": "string",
                "description": "Original question and context"
            }
        },
        "required": ["insights", "query_context"]
    }
)


RECOMMEND_CHART = ToolDefinition(
    name="recommend_chart",
    description="""Intelligently recommend the BEST chart type for the data.

Use this tool when you need to visualize data:
- After executing SQL and analyzing results
- To choose appropriate chart type (not just any chart)
- Before creating visualization for user

Intelligence features:
- **Time series detection** → Line/Area chart
- **High cardinality** (>50 categories) → Top-N bar + "Other" OR scatter
- **Part-to-whole** → Pie (only if ≤8 categories) OR Treemap
- **Comparison** → Bar (vertical/horizontal based on label length)
- **Correlation** → Scatter with trend line
- **Single value** → Gauge or KPI card

Returns:
- recommended_chart: str (line, bar, pie, scatter, area, horizontal_bar, gauge)
- rationale: str (WHY this chart type)
- config: dict (chart configuration: axes, labels, options)
- alternatives: list (other chart types with scores and reasons)
- warnings: list (potential issues like "Too many data points")

WHEN TO USE:
- Every time you want to show a chart
- Let the tool decide the best visualization
- Don't guess chart types - use this tool!

Example:
  recommend_chart(data=results, analysis_goal="show_trend")
  → {"recommended_chart": "line", "rationale": "Time series with 12 points. Line shows trend best."}
    """,
    parameters={
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "JSON string of query results"
            },
            "insights": {
                "type": "string",
                "description": "Optional JSON from detect_insights (helps choose chart type)"
            },
            "analysis_goal": {
                "type": "string",
                "enum": ["show_trend", "compare_segments", "show_distribution", "show_composition", "show_relationship", "show_single_value"],
                "description": "Optional hint about visualization goal"
            }
        },
        "required": ["data"]
    }
)


PREPARE_CHART_DATA = ToolDefinition(
    name="prepare_chart_data",
    description="""Transform data intelligently for visualization (aggregation, grouping, outlier handling).

Use this tool AFTER recommend_chart to prepare data:
- Raw data has **too many points** (>100) → aggregate for clarity
- **High cardinality** → group small categories into "Other"
- **Outliers** → cap extreme values, add annotations
- Need **smart aggregation** (daily → weekly/monthly)

Transformations applied:
- **Auto-aggregation**: 365 daily points → 52 weekly OR 12 monthly
- **Top-N grouping**: 100 categories → Top 20 + "Other (80 items)"
- **Outlier capping**: Cap at 95th percentile, mark with annotations
- **Smart binning**: Continuous data → histogram bins
- **Sorting**: Order data appropriately for chart type

Returns:
- transformed_data: list (ready for charting)
- transformations_applied: list (what was done, with explanations)
- metadata: dict (original_points, final_points, aggregation_method, etc.)

WHEN TO USE:
- After recommend_chart, before showing visualization
- When raw data has >50 points
- When categories are too granular
- To make charts clear and readable

Example:
  prepare_chart_data(data=results, chart_type="line", max_points=50)
  → {"transformed_data": [...], "transformations_applied": ["Aggregated 180 daily → 26 weekly"]}
    """,
    parameters={
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "JSON string of query results"
            },
            "chart_type": {
                "type": "string",
                "description": "Target chart type (from recommend_chart)"
            },
            "max_points": {
                "type": "integer",
                "description": "Maximum data points (default: 50). Aggregate if more.",
                "default": 50
            },
            "handle_outliers": {
                "type": "boolean",
                "description": "Whether to cap outliers at 95th percentile (default: true)",
                "default": True
            }
        },
        "required": ["data", "chart_type"]
    }
)


ANNOTATE_CHART = ToolDefinition(
    name="annotate_chart",
    description="""Add trend lines, benchmark markers, outlier highlights, or callouts to an existing chart spec.

WHEN TO USE (call this when ANY are true):
- `prepare_chart_data` just produced a chart AND detectors surfaced a trend, concentration, or outlier
- `detect_insights` returned a `trend` / `outlier` / `concentration` finding worth showing visually
- `compare_periods` produced a MoM/YoY/QoQ delta that belongs on the chart
- Statistical significance (p-value, R², std-dev band) would help the user read the chart faster
- The chart alone doesn't answer the user's question — add an annotation that does

What you can add:
- **Trend lines** — best-fit line with equation (y = mx + b, R²)
- **Benchmark lines** — average, median, previous-period, or target lines
- **Outlier markers** — highlight + tooltip on anomalous points
- **Callouts** — text boxes pointing to key insights
- **Reference areas** — shaded zones (e.g., "Target Range", "Risk Zone")
- **Axis enhancements** — units, context labels

Example:
  annotate_chart(chart_spec=chart_json, insights=insights_json, statistics=stats_json)
  → chart enhanced with trend line, average line, outlier markers
    """,
    parameters={
        "type": "object",
        "properties": {
            "chart_spec": {
                "type": "string",
                "description": "JSON string of chart specification"
            },
            "insights": {
                "type": "string",
                "description": "Optional JSON from detect_insights"
            },
            "statistics": {
                "type": "string",
                "description": "Optional JSON from analyze_statistics"
            },
            "comparisons": {
                "type": "string",
                "description": "Optional JSON from compare_periods"
            }
        },
        "required": ["chart_spec"]
    }
)


# =============================================================================
# ALL ANALYSIS TOOLS - For iteration
# =============================================================================

ALL_ANALYSIS_TOOLS = [
    DETECT_INSIGHTS,
    ANALYZE_STATISTICS,
    CHECK_DATA_QUALITY,
    COMPARE_PERIODS,
    SUGGEST_FOLLOWUPS,
    RECOMMEND_CHART,
    PREPARE_CHART_DATA,
    ANNOTATE_CHART,
]


def get_analysis_tool_by_name(name: str) -> ToolDefinition:
    """Get an analysis tool definition by name."""
    for tool in ALL_ANALYSIS_TOOLS:
        if tool.name == name:
            return tool
    raise ValueError(f"Unknown analysis tool: {name}")
