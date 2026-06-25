"""
Analysis Tool Handlers

Agent-callable tools for intelligent data analysis.
These tools wrap the analysis engines and make them available to the ReAct agent.
"""

import json
import time
from typing import Any, Dict, List, Optional, cast

from app.services.analysis_engines import (
    assess_data_quality,
    compute_statistics,
    detect_insights,
    recommend_chart,
)
from app.services.analysis_engines import compare_periods as engine_compare_periods
from app.services.analysis_engines import (
    prepare_chart_data as engine_prepare_chart_data,
)
from app.services.security import ErrorSanitizer
from app.services.analysis_engines.chart_intelligence import ChartGoal
from app.services.analysis_engines.comparisons import ComparisonType
from app.services.analysis_engines.validator import (
    log_analysis_tool_output,
    validate_chart_spec,
    validate_insights_accuracy,
)
from app.services.tools.registry import ToolContext
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# ============================================================================
# Tool 1: detect_insights
# ============================================================================

async def detect_insights_handler(
    context: ToolContext,
    data: str,
    analysis_types: Optional[List[str]] = None
) -> str:
    """
    Agent-callable tool to detect patterns and insights in query results.

    Args:
        context: Tool execution context
        data: JSON string of query results (list of row dictionaries)
        analysis_types: Optional list of analysis types
            ["concentration", "trend", "anomaly", "comparison", "all"]

    Returns:
        JSON string with list of insights + validation results
    """
    start_time = time.time()

    try:
        # Parse input data
        parsed_data = json.loads(data)

        if not isinstance(parsed_data, list):
            return json.dumps({
                "error": "Data must be a list of row dictionaries",
                "insights": []
            })

        # Run insight detection
        insights = detect_insights(parsed_data, analysis_types)

        # Validate accuracy
        validation = validate_insights_accuracy(insights, parsed_data)

        # Log tool output for monitoring
        execution_time_ms = (time.time() - start_time) * 1000
        log_analysis_tool_output(
            tool_name="detect_insights",
            input_data={"data_rows": len(parsed_data), "analysis_types": analysis_types},
            output={"insights": insights, "validation": validation},
            execution_time_ms=execution_time_ms
        )

        result = {
            "insights": insights,
            "validation": {
                "accurate": validation["accurate"],
                "accuracy_score": validation["accuracy_score"],
                "discrepancies": validation["discrepancies"]
            }
        }

        return json.dumps(result)

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON data: {e.msg} at line {e.lineno} column {e.colno}",
            "insights": []
        })
    except Exception as e:
        return json.dumps({
            "error": f"Insight detection failed: {ErrorSanitizer.sanitize_error(e)}",
            "insights": []
        })


# ============================================================================
# Tool 2: analyze_statistics
# ============================================================================

async def analyze_statistics_handler(
    context: ToolContext,
    data: str,
    columns: Optional[List[str]] = None
) -> str:
    """
    Agent-callable tool to compute advanced statistics.

    Args:
        context: Tool execution context
        data: JSON string of query results
        columns: Optional list of column names to analyze (default: all numeric)

    Returns:
        JSON string with statistics by column
    """
    try:
        parsed_data = json.loads(data)

        if not isinstance(parsed_data, list):
            return json.dumps({
                "error": "Data must be a list of row dictionaries",
                "statistics": {}
            })

        # Compute statistics
        stats = compute_statistics(parsed_data, columns)

        return json.dumps({"statistics": stats})

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON data: {e.msg} at line {e.lineno} column {e.colno}",
            "statistics": {}
        })
    except Exception as e:
        return json.dumps({
            "error": f"Statistics computation failed: {ErrorSanitizer.sanitize_error(e)}",
            "statistics": {}
        })


# ============================================================================
# Tool 3: check_data_quality
# ============================================================================

async def check_data_quality_handler(
    context: ToolContext,
    data: str
) -> str:
    """
    Agent-callable tool to assess data quality.

    Args:
        context: Tool execution context
        data: JSON string of query results

    Returns:
        JSON string with quality assessment
    """
    try:
        parsed_data = json.loads(data)

        if not isinstance(parsed_data, list):
            return json.dumps({
                "error": "Data must be a list of row dictionaries",
                "overall_score": 0
            })

        # Assess quality
        quality = assess_data_quality(parsed_data)

        return json.dumps(quality)

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON data: {e.msg} at line {e.lineno} column {e.colno}",
            "overall_score": 0
        })
    except Exception as e:
        return json.dumps({
            "error": f"Quality assessment failed: {ErrorSanitizer.sanitize_error(e)}",
            "overall_score": 0
        })


# ============================================================================
# Tool 4: compare_periods
# ============================================================================

async def compare_periods_handler(
    context: ToolContext,
    current_data: str,
    comparison_type: str,
    previous_data: Optional[str] = None,
    original_sql: Optional[str] = None
) -> str:
    """
    Agent-callable tool for temporal/segment comparisons.

    Args:
        context: Tool execution context
        current_data: JSON string of current period data
        comparison_type: Type of comparison (MoM, YoY, QoQ, WoW, segment_vs_avg)
        previous_data: Optional JSON string of previous period data
        original_sql: Optional original SQL query (for fetching previous data)

    Returns:
        JSON string with comparison results
    """
    try:
        parsed_current = json.loads(current_data)

        parsed_previous = None
        if previous_data:
            parsed_previous = json.loads(previous_data)

        # Run comparison
        result = engine_compare_periods(
            current_data=parsed_current,
            comparison_type=cast(ComparisonType, comparison_type),
            previous_data=parsed_previous,
            original_sql=original_sql
        )

        return json.dumps(result)

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON data: {e.msg} at line {e.lineno} column {e.colno}",
            "comparisons": []
        })
    except Exception as e:
        return json.dumps({
            "error": f"Comparison failed: {ErrorSanitizer.sanitize_error(e)}",
            "comparisons": []
        })


# ============================================================================
# Tool 5: suggest_followups
# ============================================================================

async def suggest_followups_handler(
    context: ToolContext,
    insights: str,
    query_context: str
) -> str:
    """
    Agent-callable tool to suggest smart follow-up questions.

    Args:
        context: Tool execution context
        insights: JSON string from detect_insights
        query_context: Original question, SQL, etc.

    Returns:
        JSON string with follow-up suggestions
    """
    try:
        parsed_insights = json.loads(insights)

        # Generate follow-ups based on insights
        suggestions = _generate_followups(parsed_insights, query_context)

        return json.dumps({"suggestions": suggestions})

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON insights: {e.msg} at line {e.lineno} column {e.colno}",
            "suggestions": []
        })
    except Exception as e:
        return json.dumps({
            "error": f"Follow-up generation failed: {ErrorSanitizer.sanitize_error(e)}",
            "suggestions": []
        })


def _generate_followups(insights: Dict[str, Any], query_context: str) -> List[Dict[str, Any]]:
    """Generate smart follow-up questions based on insights."""
    suggestions: List[Dict[str, Any]] = []

    if "insights" not in insights:
        return suggestions

    for insight in insights["insights"]:
        insight_type = insight.get("type")

        if insight_type == "concentration":
            # Suggest drilling into top items
            suggestions.append({
                "question": "Show detailed breakdown for top 3 items",
                "rationale": insight.get("description", "High concentration detected"),
                "priority": "high",
                "category": "drill_down"
            })

        elif insight_type == "trend":
            # Suggest period comparison
            suggestions.append({
                "question": "Compare to same period last year",
                "rationale": insight.get("description", "Trend detected"),
                "priority": "medium",
                "category": "comparison"
            })

        elif insight_type == "anomaly":
            # Suggest investigating outliers
            suggestions.append({
                "question": "What caused the outlier values?",
                "rationale": insight.get("description", "Outliers detected"),
                "priority": "medium",
                "category": "investigation"
            })

        elif insight_type == "comparison":
            # Suggest diving into specific segments
            suggestions.append({
                "question": "Show trend for each segment",
                "rationale": insight.get("description", "Segment differences found"),
                "priority": "medium",
                "category": "drill_down"
            })

    # Limit to top 5 suggestions
    return suggestions[:5]


# ============================================================================
# Tool 6: recommend_chart (NEW: Chart Intelligence)
# ============================================================================

async def recommend_chart_handler(
    context: ToolContext,
    data: str,
    insights: Optional[str] = None,
    analysis_goal: Optional[str] = None
) -> str:
    """
    Agent-callable tool to recommend optimal chart type.

    Args:
        context: Tool execution context
        data: JSON string of query results
        insights: Optional JSON string from detect_insights
        analysis_goal: Optional hint (show_trend, compare_segments, etc.)

    Returns:
        JSON string with chart recommendation + validation
    """
    start_time = time.time()

    try:
        parsed_data = json.loads(data)

        parsed_insights = None
        if insights:
            parsed_insights = json.loads(insights)

        # Get chart recommendation
        recommendation = recommend_chart(
            data=parsed_data,
            insights=parsed_insights,
            analysis_goal=cast(Optional[ChartGoal], analysis_goal)
        )

        # Validate chart config matches data
        chart_config = recommendation.get("config", {})
        basic_chart_spec = {
            "chart_type": recommendation.get("recommended_chart"),
            "x_axis": chart_config.get("x_axis"),
            "y_axis": chart_config.get("y_axis"),
            "data": parsed_data[:10]  # Sample for validation
        }

        validation = validate_chart_spec(basic_chart_spec, parsed_data)

        # Log for monitoring
        execution_time_ms = (time.time() - start_time) * 1000
        log_analysis_tool_output(
            tool_name="recommend_chart",
            input_data={"data_rows": len(parsed_data), "analysis_goal": analysis_goal},
            output=recommendation,
            execution_time_ms=execution_time_ms
        )

        # Add validation to response
        recommendation["validation"] = {
            "valid": validation["valid"],
            "errors": validation["errors"],
            "warnings": validation["warnings"]
        }

        return json.dumps(recommendation)

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON data: {e.msg} at line {e.lineno} column {e.colno}",
            "recommended_chart": None
        })
    except Exception as e:
        return json.dumps({
            "error": f"Chart recommendation failed: {ErrorSanitizer.sanitize_error(e)}",
            "recommended_chart": None
        })


# ============================================================================
# Tool 7: prepare_chart_data (NEW: Data Transformation for Charts)
# ============================================================================

async def prepare_chart_data_handler(
    context: ToolContext,
    data: str,
    chart_type: str,
    max_points: int = 50,
    handle_outliers: bool = True
) -> str:
    """
    Agent-callable tool to prepare data for visualization.

    Args:
        context: Tool execution context
        data: JSON string of query results
        chart_type: Target chart type
        max_points: Maximum data points (aggregate if more)
        handle_outliers: Whether to cap outliers

    Returns:
        JSON string with transformed data
    """
    try:
        parsed_data = json.loads(data)

        # Prepare data
        result = engine_prepare_chart_data(
            data=parsed_data,
            chart_type=chart_type,
            max_points=max_points,
            handle_outliers=handle_outliers
        )

        return json.dumps(result)

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON data: {e.msg} at line {e.lineno} column {e.colno}",
            "transformed_data": []
        })
    except Exception as e:
        return json.dumps({
            "error": f"Data preparation failed: {ErrorSanitizer.sanitize_error(e)}",
            "transformed_data": []
        })


# ============================================================================
# Tool 8: annotate_chart (Full Implementation)
# ============================================================================

async def annotate_chart_handler(
    context: ToolContext,
    chart_spec: str,
    insights: Optional[str] = None,
    statistics: Optional[str] = None,
    comparisons: Optional[str] = None
) -> str:
    """
    Agent-callable tool to add intelligent annotations to charts.

    Features:
    - Trend lines with equations (y = mx + b, R²)
    - Benchmark lines (average, median, previous period)
    - Outlier markers with tooltips
    - High-severity insight callouts

    Args:
        context: Tool execution context
        chart_spec: JSON string of chart specification
        insights: Optional JSON string from detect_insights
        statistics: Optional JSON string from analyze_statistics
        comparisons: Optional JSON string from compare_periods

    Returns:
        JSON string with enhanced chart spec including annotations
    """
    # Structured invocation signal so operators can confirm the LLM
    # is still discovering this tool after the prompt was slimmed
    # down to remove explicit enumeration of the analysis chain.
    # If this log line never fires in production, the SYSTEM_PROMPT
    # likely needs a sentence back about the chain.
    logger.info(
        "annotate_chart.invoked",
        extra={
            "has_insights": bool(insights),
            "has_statistics": bool(statistics),
            "has_comparisons": bool(comparisons),
        },
    )
    try:
        parsed_chart = json.loads(chart_spec)

        # Initialize annotations list
        parsed_chart["annotations"] = []

        # Add trend line for time series charts
        if parsed_chart.get("chart_type") in ["line", "area", "scatter"]:
            trend_annotation = _add_trend_line_annotation(parsed_chart, insights)
            if trend_annotation:
                parsed_chart["annotations"].append(trend_annotation)

        # Add benchmark lines from statistics
        if statistics:
            benchmark_annotations = _add_benchmark_annotations(parsed_chart, statistics)
            parsed_chart["annotations"].extend(benchmark_annotations)

        # Add comparison reference lines
        if comparisons:
            comparison_annotations = _add_comparison_annotations(parsed_chart, comparisons)
            parsed_chart["annotations"].extend(comparison_annotations)

        # Add outlier markers
        outlier_annotations = _add_outlier_markers(parsed_chart, insights)
        parsed_chart["annotations"].extend(outlier_annotations)

        # Add callouts for high-severity insights
        if insights:
            parsed_insights = json.loads(insights)
            for insight in parsed_insights.get("insights", []):
                if insight.get("severity") == "high":
                    parsed_chart["annotations"].append({
                        "type": "callout",
                        "text": insight.get("title", ""),
                        "description": insight.get("description", ""),
                        "severity": "high"
                    })

        return json.dumps(parsed_chart)

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON: {e.msg} at line {e.lineno} column {e.colno}"
        })
    except Exception as e:
        return json.dumps({
            "error": f"Annotation failed: {ErrorSanitizer.sanitize_error(e)}"
        })


def _add_trend_line_annotation(chart_spec: Dict[str, Any], insights: Optional[str]) -> Optional[Dict[str, Any]]:
    """Add trend line annotation with equation."""
    if not insights:
        return None

    try:
        parsed_insights = json.loads(insights)
        for insight in parsed_insights.get("insights", []):
            if insight.get("type") == "trend":
                metrics = insight.get("metrics", {})
                slope = metrics.get("slope")
                r_squared = metrics.get("r_squared")

                if slope is not None and r_squared is not None:
                    direction = metrics.get("direction", "")
                    acceleration = metrics.get("acceleration", "")

                    return {
                        "type": "trend_line",
                        "slope": slope,
                        "r_squared": r_squared,
                        "equation": f"y = {slope:.4f}x + intercept (R²={r_squared:.3f})",
                        "description": f"{direction.capitalize()} trend ({acceleration})"
                    }
    except Exception:
        pass

    return None


def _add_benchmark_annotations(chart_spec: Dict[str, Any], statistics: str) -> List[Dict[str, Any]]:
    """Add benchmark lines (average, median) from statistics."""
    annotations = []

    try:
        parsed_stats = json.loads(statistics)
        stats_dict = parsed_stats.get("statistics", {})

        # Add average and median lines for the first numeric column
        for col, col_stats in stats_dict.items():
            mean_val = col_stats.get("mean")
            median_val = col_stats.get("median")

            if mean_val is not None:
                annotations.append({
                    "type": "benchmark",
                    "subtype": "average",
                    "value": mean_val,
                    "label": f"Average: {mean_val:.2f}",
                    "style": {"color": "blue", "dashArray": "5,5"}
                })

            if median_val is not None:
                annotations.append({
                    "type": "benchmark",
                    "subtype": "median",
                    "value": median_val,
                    "label": f"Median: {median_val:.2f}",
                    "style": {"color": "green", "dashArray": "3,3"}
                })

            # Only add benchmarks for the first column
            break

    except Exception:
        pass

    return annotations


def _add_comparison_annotations(chart_spec: Dict[str, Any], comparisons: str) -> List[Dict[str, Any]]:
    """Add comparison reference lines (previous period)."""
    annotations = []

    try:
        parsed_comp = json.loads(comparisons)
        comparison_list = parsed_comp.get("comparisons", [])

        for comp in comparison_list:
            previous_val = comp.get("previous")
            comp_type = comp.get("type")

            if previous_val is not None:
                annotations.append({
                    "type": "benchmark",
                    "subtype": "previous_period",
                    "value": previous_val,
                    "label": f"Previous {comp_type}: {previous_val:.2f}",
                    "style": {"color": "orange", "dashArray": "2,2"}
                })

    except Exception:
        pass

    return annotations


def _add_outlier_markers(chart_spec: Dict[str, Any], insights: Optional[str]) -> List[Dict[str, Any]]:
    """Add markers for outlier data points."""
    annotations: List[Dict[str, Any]] = []

    if not insights:
        return annotations

    try:
        parsed_insights = json.loads(insights)
        for insight in parsed_insights.get("insights", []):
            if insight.get("type") == "anomaly":
                metrics = insight.get("metrics", {})
                outliers = metrics.get("outliers", [])

                for outlier in outliers[:3]:  # Limit to first 3 outliers
                    annotations.append({
                        "type": "outlier",
                        "value": outlier.get("value"),
                        "z_score": outlier.get("z_score"),
                        "identifier": outlier.get("identifier"),
                        "description": f"Outlier: {outlier.get('value')} (z={outlier.get('z_score')})"
                    })

    except Exception:
        pass

    return annotations
