"""
Chart Intelligence Engine

Intelligently recommends chart types and prepares data for visualization.
Handles aggregation, grouping, outlier treatment, and optimization.
"""

import statistics
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

ChartGoal = Literal[
    "show_trend",
    "compare_segments",
    "show_distribution",
    "show_composition",
    "show_relationship",
    "show_single_value"
]


def recommend_chart(
    data: List[Dict[str, Any]],
    insights: Optional[Dict[str, Any]] = None,
    analysis_goal: Optional[ChartGoal] = None,
    aggregated: bool = False,
) -> Dict[str, Any]:
    """
    Intelligently recommend the best chart type for the data.

    Args:
        data: Query results
        insights: Optional insights from detect_insights
        analysis_goal: Optional hint about what to show
        aggregated: True when ``data`` is the result of a GROUP BY
            (Phase 3a.3 detection). In aggregated mode the recommender
            biases toward bar / column charts over scatter / histogram
            because each row is a group total rather than a raw
            observation. The ``aggregated_mode`` flag is included in
            the returned dict so the chart-render layer can also
            choose appropriate axis labels.

    Returns:
        - recommended_chart: str (chart type)
        - rationale: str (why this chart type)
        - config: Dict (chart configuration)
        - alternatives: List[Dict] (alternative chart types with scores)
        - warnings: List[str] (potential issues)
        - aggregated_mode: bool (echoed for downstream consumers)
    """
    if not data:
        return {
            "recommended_chart": None,
            "rationale": "No data to visualize",
            "config": {},
            "alternatives": [],
            "warnings": ["No data returned from query"],
            "aggregated_mode": aggregated,
        }

    warnings = []

    # Analyze data characteristics
    characteristics = _analyze_data_characteristics(data)

    # Phase 4 cross-phase wiring: hint the chooser that this is
    # group-aggregated data so it prefers bar / column over scatter /
    # histogram (which assume row-level observations). The chooser
    # ignores unknown keys, so this is forward-compatible — when the
    # chooser learns the hint it'll act on it; until then we just
    # surface the flag in the response.
    characteristics["aggregated_mode"] = aggregated

    # Determine chart type based on characteristics and goal
    chart_recommendation = _determine_chart_type(
        characteristics,
        analysis_goal,
        insights
    )

    # Add warnings based on data characteristics
    if characteristics["row_count"] > 100:
        warnings.append(f"Large dataset ({characteristics['row_count']} rows). Consider aggregation for clarity.")

    if characteristics["cardinality_max"] > 50:
        warnings.append(f"High cardinality ({characteristics['cardinality_max']} unique values). Top-N + Other recommended.")

    if characteristics["has_nulls"]:
        warnings.append("Data contains null values. Consider how to handle in visualization.")

    return {
        "recommended_chart": chart_recommendation["type"],
        "rationale": chart_recommendation["rationale"],
        "config": chart_recommendation["config"],
        "alternatives": chart_recommendation["alternatives"],
        "warnings": warnings,
        "aggregated_mode": aggregated,
    }


def prepare_chart_data(
    data: List[Dict[str, Any]],
    chart_type: str,
    max_points: int = 50,
    handle_outliers: bool = True
) -> Dict[str, Any]:
    """
    Transform data intelligently for visualization.

    Args:
        data: Raw query results
        chart_type: Target chart type
        max_points: Maximum data points (aggregate if more)
        handle_outliers: Whether to cap outliers

    Returns:
        - transformed_data: List[Dict] (ready for charting)
        - transformations_applied: List[str] (what was done)
        - metadata: Dict (info about transformations)
    """
    if not data:
        return {
            "transformed_data": [],
            "transformations_applied": [],
            "metadata": {}
        }

    transformed_data = data.copy()
    transformations = []
    metadata = {}

    # 1. Handle outliers if requested
    if handle_outliers:
        outlier_result = _handle_outliers(transformed_data)
        transformed_data = outlier_result["data"]
        if outlier_result["outliers_capped"] > 0:
            transformations.append(
                f"Capped {outlier_result['outliers_capped']} outliers at 95th percentile"
            )
            metadata["outliers_capped"] = outlier_result["outliers_capped"]

    # 2. Aggregate if too many points
    if len(transformed_data) > max_points:
        agg_result = _aggregate_data(transformed_data, max_points)
        transformed_data = agg_result["data"]
        transformations.append(
            f"Aggregated {len(data)} points to {len(transformed_data)} for clarity"
        )
        metadata["aggregation_method"] = agg_result["method"]
        metadata["original_points"] = len(data)
        metadata["final_points"] = len(transformed_data)

    # 3. Handle high cardinality (for categorical charts)
    if chart_type in ["bar", "pie", "horizontal_bar"]:
        cardinality_result = _handle_high_cardinality(transformed_data, max_categories=20)
        if cardinality_result["grouped"]:
            transformed_data = cardinality_result["data"]
            transformations.append(
                f"Grouped {cardinality_result['categories_grouped']} small categories into 'Other'"
            )
            metadata["categories_grouped"] = cardinality_result["categories_grouped"]

    # 4. Sort data appropriately
    sorted_result = _sort_data_for_chart(transformed_data, chart_type)
    transformed_data = sorted_result["data"]
    if sorted_result["sorted"]:
        transformations.append(f"Sorted by {sorted_result['sort_key']}")
        metadata["sort_key"] = sorted_result["sort_key"]

    return {
        "transformed_data": transformed_data,
        "transformations_applied": transformations,
        "metadata": metadata
    }


# ============================================================================
# Internal Functions
# ============================================================================

def _analyze_data_characteristics(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze data to determine appropriate chart type."""
    if not data:
        return {}

    columns = list(data[0].keys())
    row_count = len(data)

    # Classify columns
    numeric_cols = []
    date_cols = []
    categorical_cols = []

    for col in columns:
        col_type = _classify_column(data, col)
        if col_type == "numeric":
            numeric_cols.append(col)
        elif col_type == "date":
            date_cols.append(col)
        elif col_type == "categorical":
            categorical_cols.append(col)

    # Calculate cardinality
    cardinality = {}
    for col in columns:
        unique_values = len(set(row.get(col) for row in data if row.get(col) is not None))
        cardinality[col] = unique_values

    cardinality_max = max(cardinality.values()) if cardinality else 0

    # Check for nulls
    has_nulls = any(
        any(row.get(col) is None for col in columns)
        for row in data
    )

    return {
        "row_count": row_count,
        "column_count": len(columns),
        "numeric_cols": numeric_cols,
        "date_cols": date_cols,
        "categorical_cols": categorical_cols,
        "cardinality": cardinality,
        "cardinality_max": cardinality_max,
        "has_nulls": has_nulls,
        "is_time_series": len(date_cols) > 0 and len(numeric_cols) > 0
    }


def _determine_chart_type(
    characteristics: Dict[str, Any],
    analysis_goal: Optional[ChartGoal],
    insights: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Determine the best chart type based on data characteristics."""
    # Time series detection
    if characteristics.get("is_time_series"):
        return {
            "type": "line",
            "rationale": f"Time series detected with {characteristics['row_count']} data points. Line chart best shows trends over time.",
            "config": {
                "x_axis": characteristics["date_cols"][0],
                "y_axis": characteristics["numeric_cols"][0],
                "show_trend_line": characteristics["row_count"] >= 5,
                "show_data_labels": characteristics["row_count"] <= 10
            },
            "alternatives": [
                {"type": "area", "score": 0.85, "reason": "Emphasizes cumulative trend"},
                {"type": "bar", "score": 0.7, "reason": "Good for period comparisons"}
            ]
        }

    # Single numeric value
    if characteristics["row_count"] == 1 and len(characteristics["numeric_cols"]) == 1:
        return {
            "type": "gauge",
            "rationale": "Single value - gauge or KPI card is most appropriate",
            "config": {
                "value": characteristics["numeric_cols"][0],
                "show_as_kpi": True
            },
            "alternatives": []
        }

    # Part-to-whole (pie chart) - only if ≤8 categories
    if (len(characteristics["categorical_cols"]) == 1 and
        len(characteristics["numeric_cols"]) == 1 and
        characteristics["row_count"] <= 8):
        return {
            "type": "pie",
            "rationale": f"Part-to-whole relationship with {characteristics['row_count']} categories (≤8). Pie chart shows composition.",
            "config": {
                "category": characteristics["categorical_cols"][0],
                "value": characteristics["numeric_cols"][0],
                "show_percentages": True
            },
            "alternatives": [
                {"type": "bar", "score": 0.9, "reason": "Better for precise value comparison"},
                {"type": "treemap", "score": 0.8, "reason": "Hierarchical composition view"}
            ]
        }

    # High cardinality → Top-N bar chart
    if (characteristics["cardinality_max"] > 20 and
        len(characteristics["categorical_cols"]) >= 1 and
        len(characteristics["numeric_cols"]) >= 1):
        return {
            "type": "horizontal_bar",
            "rationale": f"High cardinality ({characteristics['cardinality_max']} categories). Top-N bar chart with horizontal layout.",
            "config": {
                "x_axis": characteristics["numeric_cols"][0],
                "y_axis": characteristics["categorical_cols"][0],
                "show_top_n": 20,
                "show_data_labels": True
            },
            "alternatives": [
                {"type": "scatter", "score": 0.6, "reason": "Shows all points without aggregation"}
            ]
        }

    # Comparison (bar chart)
    if (len(characteristics["categorical_cols"]) >= 1 and
        len(characteristics["numeric_cols"]) >= 1):
        return {
            "type": "bar",
            "rationale": f"Categorical comparison with {characteristics['row_count']} categories. Bar chart for easy comparison.",
            "config": {
                "x_axis": characteristics["categorical_cols"][0],
                "y_axis": characteristics["numeric_cols"][0],
                "show_data_labels": characteristics["row_count"] <= 15
            },
            "alternatives": [
                {"type": "horizontal_bar", "score": 0.9, "reason": "Better for long category names"},
                {"type": "line", "score": 0.5, "reason": "If categories have order"}
            ]
        }

    # Multiple numeric columns → scatter or grouped bar
    if len(characteristics["numeric_cols"]) >= 2:
        return {
            "type": "scatter",
            "rationale": f"Multiple numeric columns. Scatter plot shows relationships between {characteristics['numeric_cols'][0]} and {characteristics['numeric_cols'][1]}.",
            "config": {
                "x_axis": characteristics["numeric_cols"][0],
                "y_axis": characteristics["numeric_cols"][1],
                "show_trend_line": True
            },
            "alternatives": [
                {"type": "bar", "score": 0.8, "reason": "Grouped bars for discrete comparison"}
            ]
        }

    # Default fallback
    return {
        "type": "bar",
        "rationale": "Default bar chart for general data visualization",
        "config": {},
        "alternatives": []
    }


def _classify_column(data: List[Dict[str, Any]], col: str) -> str:
    """Classify a column as numeric, date, or categorical."""
    sample_values = [row.get(col) for row in data[:100] if row.get(col) is not None]

    if not sample_values:
        return "unknown"

    sample = sample_values[0]

    if isinstance(sample, (int, float)) and not isinstance(sample, bool):
        return "numeric"
    elif isinstance(sample, (datetime, date)):
        return "date"
    else:
        # Check cardinality for categorical
        unique_count = len(set(sample_values))
        if unique_count < len(sample_values) * 0.5:  # <50% unique
            return "categorical"
        else:
            return "text"


def _handle_outliers(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cap outliers at 95th percentile."""
    numeric_cols = [col for col in data[0].keys()
                    if any(_is_numeric(row.get(col)) for row in data)]

    outliers_capped = 0
    modified_data = []

    for row in data:
        new_row = row.copy()
        for col in numeric_cols:
            # Filter to only numeric values, casting to float
            numeric_values: List[float] = [
                float(r.get(col))  # type: ignore[arg-type]
                for r in data
                if _is_numeric(r.get(col))
            ]
            if len(numeric_values) < 5:
                continue

            p95 = _percentile(sorted(numeric_values), 95)
            val = new_row.get(col)

            if _is_numeric(val) and float(val) > p95:  # type: ignore[arg-type]
                new_row[col] = p95
                outliers_capped += 1

        modified_data.append(new_row)

    return {
        "data": modified_data,
        "outliers_capped": outliers_capped
    }


def _aggregate_data(data: List[Dict[str, Any]], target_points: int) -> Dict[str, Any]:
    """Aggregate data to reduce number of points."""
    # Simple bucketing aggregation
    # In production, would use more sophisticated methods based on data type

    bucket_size = len(data) // target_points
    if bucket_size < 2:
        return {"data": data, "method": "none"}

    aggregated = []
    for i in range(0, len(data), bucket_size):
        bucket = data[i:i + bucket_size]
        agg_row = _aggregate_bucket(bucket)
        aggregated.append(agg_row)

    return {
        "data": aggregated,
        "method": f"bucket_average_{bucket_size}"
    }


def _aggregate_bucket(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a bucket of rows."""
    if not bucket:
        return {}

    agg_row: Dict[str, Any] = {}
    columns = list(bucket[0].keys())

    for col in columns:
        values = [row.get(col) for row in bucket if row.get(col) is not None]

        if not values:
            agg_row[col] = None
        elif _is_numeric(values[0]):
            # Filter to only numeric values for mean calculation
            numeric_vals = [float(v) for v in values if _is_numeric(v)]  # type: ignore[arg-type]
            agg_row[col] = statistics.mean(numeric_vals)
        else:
            # For non-numeric, take first value
            agg_row[col] = values[0]

    return agg_row


def _handle_high_cardinality(data: List[Dict[str, Any]], max_categories: int = 20) -> Dict[str, Any]:
    """
    Group small categories into 'Other'.

    Implementation:
    1. Identify categorical column with high cardinality
    2. Sort categories by value (descending)
    3. Keep top N categories
    4. Group remaining into 'Other' category with combined value
    """
    if not data:
        return {"data": data, "grouped": False, "categories_grouped": 0}

    # Find categorical columns
    categorical_cols = [col for col in data[0].keys()
                        if not _is_numeric(data[0].get(col))]

    # Find numeric columns (for aggregation values)
    numeric_cols = [col for col in data[0].keys()
                    if _is_numeric(data[0].get(col))]

    if not categorical_cols or not numeric_cols:
        return {"data": data, "grouped": False, "categories_grouped": 0}

    # Check if we need to group (more than max_categories)
    if len(data) <= max_categories:
        return {"data": data, "grouped": False, "categories_grouped": 0}

    # Use the first categorical column and first numeric column
    cat_col = categorical_cols[0]
    num_col = numeric_cols[0]

    # Sort data by numeric value descending
    sorted_data = sorted(data, key=lambda x: x.get(num_col, 0) or 0, reverse=True)

    # Keep top N categories
    top_n = sorted_data[:max_categories]

    # Group the rest into "Other"
    others = sorted_data[max_categories:]

    if not others:
        return {"data": data, "grouped": False, "categories_grouped": 0}

    # Calculate "Other" aggregate
    other_row: Dict[str, Any] = {cat_col: "Other"}

    # Sum numeric columns
    for col in numeric_cols:
        numeric_sum = sum(row.get(col, 0) or 0 for row in others)
        other_row[col] = numeric_sum

    # Copy non-numeric, non-categorical columns from first "other" row
    if others:
        for col in others[0].keys():
            if col not in numeric_cols and col != cat_col:
                col_value = others[0].get(col)
                other_row[col] = col_value

    # Combine top N + Other
    result_data = top_n + [other_row]

    return {
        "data": result_data,
        "grouped": True,
        "categories_grouped": len(others),
        "other_total": other_row.get(num_col, 0)
    }


def _sort_data_for_chart(data: List[Dict[str, Any]], chart_type: str) -> Dict[str, Any]:
    """Sort data appropriately for the chart type."""
    if not data:
        return {"data": data, "sorted": False, "sort_key": None}

    # Find numeric column to sort by
    numeric_cols = [col for col in data[0].keys()
                    if _is_numeric(data[0].get(col))]

    if not numeric_cols:
        return {"data": data, "sorted": False, "sort_key": None}

    # Sort descending by first numeric column for bar/pie charts
    if chart_type in ["bar", "pie", "horizontal_bar"]:
        sorted_data = sorted(data, key=lambda x: x.get(numeric_cols[0], 0), reverse=True)
        return {"data": sorted_data, "sorted": True, "sort_key": numeric_cols[0]}

    return {"data": data, "sorted": False, "sort_key": None}


def _percentile(sorted_values: List[float], p: float) -> float:
    """Calculate percentile."""
    if not sorted_values:
        return 0.0

    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    k = (n - 1) * (p / 100)
    f = int(k)
    c = k - f

    if f + 1 < n:
        return sorted_values[f] + c * (sorted_values[f + 1] - sorted_values[f])
    else:
        return sorted_values[f]


def _is_numeric(val: Any) -> bool:
    """Check if a value is numeric."""
    return isinstance(val, (int, float)) and not isinstance(val, bool)
