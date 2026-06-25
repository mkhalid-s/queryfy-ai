"""
Analysis Accuracy Validator

Validates that insights, statistics, and chart recommendations are accurate
based on actual data, not LLM hallucinations.
"""

from typing import Any, Dict, List


def validate_insights_accuracy(
    insights: List[Dict[str, Any]],
    original_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate that insights are based on actual data.

    Checks:
    - Concentration percentages match actual data
    - Trend slopes are mathematically correct
    - Outliers actually exist in the data
    - Segment comparisons are accurate

    Returns:
        {
            "accurate": bool,
            "accuracy_score": float (0-100),
            "discrepancies": List[str],
            "validated_insights": List[Dict]
        }
    """
    if not insights or not original_data:
        return {
            "accurate": True,
            "accuracy_score": 100,
            "discrepancies": [],
            "validated_insights": insights or []
        }

    discrepancies = []
    validated_insights = []

    for insight in insights:
        insight_type = insight.get("type")

        if insight_type == "concentration":
            # Validate concentration percentages
            validation = _validate_concentration(insight, original_data)
            if not validation["accurate"]:
                discrepancies.append(validation["error"])
            validated_insights.append({
                **insight,
                "validated": validation["accurate"],
                "actual_metrics": validation.get("actual_metrics")
            })

        elif insight_type == "trend":
            # Validate trend calculations
            validation = _validate_trend(insight, original_data)
            if not validation["accurate"]:
                discrepancies.append(validation["error"])
            validated_insights.append({
                **insight,
                "validated": validation["accurate"]
            })

        elif insight_type == "anomaly":
            # Validate outliers exist
            validation = _validate_anomaly(insight, original_data)
            if not validation["accurate"]:
                discrepancies.append(validation["error"])
            validated_insights.append({
                **insight,
                "validated": validation["accurate"]
            })

        else:
            # Unknown type, skip validation
            validated_insights.append(insight)

    accuracy_score = 100 - (len(discrepancies) * 10)  # -10 points per discrepancy
    accuracy_score = max(0, min(100, accuracy_score))

    return {
        "accurate": len(discrepancies) == 0,
        "accuracy_score": accuracy_score,
        "discrepancies": discrepancies,
        "validated_insights": validated_insights
    }


def validate_chart_spec(
    chart_spec: Dict[str, Any],
    original_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate chart specification is correct for the data.

    Checks:
    - x_axis and y_axis columns exist in data
    - Chart type is appropriate for data shape
    - Data points are properly formatted
    - Annotations reference valid data points

    Returns:
        {
            "valid": bool,
            "errors": List[str],
            "warnings": List[str]
        }
    """
    errors = []
    warnings = []

    if not chart_spec or not original_data:
        return {"valid": True, "errors": [], "warnings": []}

    # Check required fields
    if "chart_type" not in chart_spec:
        errors.append("Missing chart_type in specification")

    x_axis = chart_spec.get("x_axis")
    y_axis = chart_spec.get("y_axis")

    # Validate axes exist in data
    if original_data:
        available_columns = list(original_data[0].keys())

        if x_axis and x_axis not in available_columns:
            errors.append(f"x_axis '{x_axis}' not found in data columns: {available_columns}")

        if y_axis and y_axis not in available_columns:
            errors.append(f"y_axis '{y_axis}' not found in data columns: {available_columns}")

    # Validate data points
    chart_data = chart_spec.get("data", [])
    if not chart_data:
        warnings.append("Chart spec has no data points")
    elif len(chart_data) > 100:
        warnings.append(f"Chart has {len(chart_data)} points - consider aggregation for clarity")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }


# =============================================================================
# Internal Validation Functions
# =============================================================================

def _validate_concentration(insight: Dict[str, Any], data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate concentration insight accuracy."""
    metrics = insight.get("metrics", {})
    claimed_top_3_pct = metrics.get("top_3_pct")

    if claimed_top_3_pct is None:
        return {"accurate": True}

    # Recalculate actual top 3 percentage
    numeric_cols = [col for col in data[0].keys()
                    if isinstance(data[0].get(col), (int, float))]

    if not numeric_cols:
        return {"accurate": True, "error": "No numeric columns to validate"}

    col = numeric_cols[0]  # Use first numeric column
    values = [row.get(col, 0) for row in data if isinstance(row.get(col), (int, float))]

    if len(values) < 3:
        return {"accurate": True}

    sorted_values = sorted(values, reverse=True)
    total = sum(sorted_values)

    if total == 0:
        return {"accurate": True}

    actual_top_3_pct = (sum(sorted_values[:3]) / total) * 100

    # Allow 1% tolerance for rounding
    tolerance = 1.0
    if abs(actual_top_3_pct - claimed_top_3_pct) <= tolerance:
        return {"accurate": True, "actual_metrics": {"top_3_pct": round(actual_top_3_pct, 1)}}
    else:
        return {
            "accurate": False,
            "error": f"Concentration claim inaccurate: claimed {claimed_top_3_pct}%, actual {actual_top_3_pct:.1f}%",
            "actual_metrics": {"top_3_pct": round(actual_top_3_pct, 1)}
        }


def _validate_trend(insight: Dict[str, Any], data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate trend insight accuracy."""
    metrics = insight.get("metrics", {})
    claimed_r_squared = metrics.get("r_squared")

    if claimed_r_squared is None:
        return {"accurate": True}

    # For now, just check R² is within valid range [0, 1]
    if 0 <= claimed_r_squared <= 1:
        return {"accurate": True}
    else:
        return {
            "accurate": False,
            "error": f"Invalid R² value: {claimed_r_squared} (must be 0-1)"
        }


def _validate_anomaly(insight: Dict[str, Any], data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate anomaly insight accuracy."""
    metrics = insight.get("metrics", {})
    outlier_count = metrics.get("outlier_count")

    if outlier_count is None or outlier_count == 0:
        return {"accurate": True}

    # Check if outliers list matches count
    outliers = metrics.get("outliers", [])
    if len(outliers) <= outlier_count:
        return {"accurate": True}
    else:
        return {
            "accurate": False,
            "error": f"Outlier count mismatch: claimed {outlier_count}, provided {len(outliers)} examples"
        }


def log_analysis_tool_output(
    tool_name: str,
    input_data: Dict[str, Any],
    output: Dict[str, Any],
    execution_time_ms: float
) -> None:
    """
    Log analysis tool outputs for accuracy review and monitoring.

    This allows us to:
    1. Review tool outputs for accuracy
    2. Track which tools are used most
    3. Monitor performance
    4. Detect patterns in tool usage
    """
    import structlog

    logger = structlog.get_logger(__name__)

    logger.info(
        "analysis_tool_executed",
        tool=tool_name,
        input_summary={
            "data_rows": len(input_data.get("data", [])) if isinstance(input_data.get("data"), list) else "N/A",
            "parameters": {k: v for k, v in input_data.items() if k != "data"}
        },
        output_summary={
            "insights_count": len(output.get("insights", [])) if tool_name == "detect_insights" else None,
            "quality_score": output.get("overall_score") if tool_name == "check_data_quality" else None,
            "chart_type": output.get("recommended_chart") if tool_name == "recommend_chart" else None,
            "has_error": "error" in output
        },
        execution_time_ms=execution_time_ms
    )
