"""
Comparison Analysis Engine

Handles temporal and segment comparisons.
Can automatically fetch previous period data for time-based comparisons.
"""

import re
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Union, cast

import sqlparse

ComparisonType = Literal["MoM", "YoY", "QoQ", "WoW", "segment_vs_avg"]


def compare_periods(
    current_data: List[Dict[str, Any]],
    comparison_type: ComparisonType,
    previous_data: Optional[List[Dict[str, Any]]] = None,
    original_sql: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compare current period data with previous period or segments.

    Args:
        current_data: Current period data
        comparison_type: Type of comparison (MoM, YoY, QoQ, WoW, segment_vs_avg)
        previous_data: Optional previous period data (if not provided, will need SQL to fetch)
        original_sql: Original SQL query (used to modify for fetching previous period)

    Returns:
        - comparisons: List[Dict] (comparison results)
        - needs_previous_fetch: bool (whether previous data needs to be fetched)
        - modified_sql: Optional[str] (SQL to fetch previous period data)
    """
    if not current_data:
        return {
            "comparisons": [],
            "needs_previous_fetch": False,
            "modified_sql": None
        }

    # If this is segment comparison, handle differently
    if comparison_type == "segment_vs_avg":
        return _compare_segments(current_data)

    # For temporal comparisons, we need previous period data
    if previous_data is None:
        # Need to fetch previous period data
        if original_sql:
            modified_sql = _modify_sql_for_previous_period(original_sql, comparison_type)
            return {
                "comparisons": [],
                "needs_previous_fetch": True,
                "modified_sql": modified_sql,
                "comparison_type": comparison_type
            }
        else:
            # Can't fetch without SQL
            return {
                "comparisons": [],
                "needs_previous_fetch": True,
                "modified_sql": None,
                "error": "Cannot fetch previous period: original SQL not provided"
            }

    # We have both current and previous data - perform comparison
    comparisons = _perform_temporal_comparison(
        current_data,
        previous_data,
        comparison_type
    )

    return {
        "comparisons": comparisons,
        "needs_previous_fetch": False,
        "modified_sql": None
    }


def _perform_temporal_comparison(
    current_data: List[Dict[str, Any]],
    previous_data: List[Dict[str, Any]],
    comparison_type: str
) -> List[Dict[str, Any]]:
    """Perform temporal comparison between two periods."""
    comparisons = []

    # Get numeric columns
    numeric_cols = _get_numeric_columns(current_data)

    for col in numeric_cols:
        # Filter and ensure we have numeric values (int or float)
        current_values: List[Union[int, float]] = cast(
            List[Union[int, float]],
            [row.get(col) for row in current_data if _is_numeric(row.get(col))]
        )
        previous_values: List[Union[int, float]] = cast(
            List[Union[int, float]],
            [row.get(col) for row in previous_data if _is_numeric(row.get(col))]
        )

        if not current_values or not previous_values:
            continue

        # Calculate aggregates
        current_sum = sum(current_values)
        previous_sum = sum(previous_values)

        current_avg = statistics.mean(current_values)
        previous_avg = statistics.mean(previous_values)

        # Calculate changes
        if previous_sum != 0:
            change_pct = ((current_sum - previous_sum) / abs(previous_sum)) * 100
        else:
            change_pct = 0.0

        if previous_avg != 0:
            avg_change_pct = ((current_avg - previous_avg) / abs(previous_avg)) * 100
        else:
            avg_change_pct = 0.0

        # Interpret the change
        interpretation = _interpret_change(change_pct, comparison_type)
        significance = _assess_significance(change_pct)

        comparisons.append({
            "type": comparison_type,
            "metric": col,
            "current": round(current_sum, 2),
            "previous": round(previous_sum, 2),
            "change_absolute": round(current_sum - previous_sum, 2),
            "change_pct": round(change_pct, 1),
            "current_avg": round(current_avg, 2),
            "previous_avg": round(previous_avg, 2),
            "avg_change_pct": round(avg_change_pct, 1),
            "interpretation": interpretation,
            "significance": significance,
            "direction": "increase" if change_pct > 0 else "decrease" if change_pct < 0 else "stable"
        })

    return comparisons


def _compare_segments(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare segments/categories against overall average."""
    comparisons = []

    # Find categorical columns
    categorical_cols = _get_categorical_columns(data)
    numeric_cols = _get_numeric_columns(data)

    if not categorical_cols or not numeric_cols:
        return {
            "comparisons": [],
            "needs_previous_fetch": False,
            "modified_sql": None
        }

    # For each categorical x numeric combination
    for cat_col in categorical_cols:
        for num_col in numeric_cols:
            # Group by category
            groups: Dict[Any, List[Union[int, float]]] = {}
            for row in data:
                category = row.get(cat_col)
                value = row.get(num_col)

                if category is not None and _is_numeric(value):
                    if category not in groups:
                        groups[category] = []
                    groups[category].append(value)  # type: ignore[arg-type]

            if len(groups) < 2:
                continue

            # Calculate overall average
            all_values = [v for vals in groups.values() for v in vals]
            overall_avg = statistics.mean(all_values)

            # Compare each group to average
            segment_comparisons = []
            for segment, values in groups.items():
                segment_avg = statistics.mean(values)

                if overall_avg != 0:
                    pct_diff = ((segment_avg - overall_avg) / abs(overall_avg)) * 100
                else:
                    pct_diff = 0

                segment_comparisons.append({
                    "segment": segment,
                    "value": round(segment_avg, 2),
                    "overall_avg": round(overall_avg, 2),
                    "pct_diff_from_avg": round(pct_diff, 1),
                    "direction": "above" if pct_diff > 0 else "below" if pct_diff < 0 else "at",
                    "significance": _assess_significance(pct_diff)
                })

            # Sort by absolute difference
            segment_comparisons.sort(key=lambda x: abs(x["pct_diff_from_avg"]), reverse=True)

            comparisons.append({
                "type": "segment_vs_avg",
                "dimension": cat_col,
                "metric": num_col,
                "segments": segment_comparisons
            })

    return {
        "comparisons": comparisons,
        "needs_previous_fetch": False,
        "modified_sql": None
    }


def _modify_sql_for_previous_period(sql: str, comparison_type: str) -> str:
    """
    Modify SQL to fetch previous period data by shifting date ranges.

    Uses sqlparse to intelligently modify date literals in WHERE clauses.

    Handles common patterns:
    - WHERE date >= '2024-01-01' AND date < '2024-02-01'
    - WHERE created_at BETWEEN '2024-01-01' AND '2024-01-31'
    - WHERE year = 2024 AND month = 1

    Args:
        sql: Original SQL query
        comparison_type: MoM, YoY, QoQ, WoW

    Returns:
        Modified SQL with shifted date range
    """
    sql = sql.strip()

    # Parse SQL
    try:
        parsed = sqlparse.parse(sql)[0]
    except Exception:
        # Fallback: return original SQL with comment
        return f"-- Could not parse SQL for period comparison\n{sql}"

    # Find date literals in the SQL
    date_literals = []
    for token in parsed.flatten():
        if token.ttype in (sqlparse.tokens.String.Single, sqlparse.tokens.String):
            # Check if it looks like a date
            value = token.value.strip("'\"")
            if _looks_like_date_string(value):
                date_literals.append((token.value, value))

    if not date_literals:
        # No dates found, return original
        return f"-- No date literals found for period comparison\n{sql}"

    # Determine shift amount based on comparison type
    shifts = {
        "WoW": timedelta(days=7),
        "MoM": timedelta(days=30),  # Approximate month
        "QoQ": timedelta(days=90),  # Approximate quarter
        "YoY": timedelta(days=365),  # Approximate year
    }

    shift_delta = shifts.get(comparison_type, timedelta(days=30))

    # Modify SQL by replacing date literals
    modified_sql = sql
    for original_token, date_str in date_literals:
        try:
            # Parse the date
            parsed_date = _parse_date_flexible(date_str)
            if parsed_date:
                # Shift the date
                shifted_date = parsed_date - shift_delta

                # Format based on original format
                if "T" in date_str or " " in date_str:
                    # Datetime format
                    new_date_str = shifted_date.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # Date only
                    new_date_str = shifted_date.strftime("%Y-%m-%d")

                # Replace in SQL (preserve quotes)
                quote_char = original_token[0]
                new_token = f"{quote_char}{new_date_str}{quote_char}"
                modified_sql = modified_sql.replace(original_token, new_token, 1)
        except Exception:
            # Skip this date if parsing fails
            continue

    return modified_sql


def _looks_like_date_string(value: str) -> bool:
    """Check if a string looks like a date."""
    # Common date patterns
    date_patterns = [
        r"\d{4}-\d{2}-\d{2}",  # YYYY-MM-DD
        r"\d{4}/\d{2}/\d{2}",  # YYYY/MM/DD
        r"\d{2}/\d{2}/\d{4}",  # MM/DD/YYYY
        r"\d{4}-\d{2}-\d{2}T",  # ISO datetime
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}",  # YYYY-MM-DD HH:MM
    ]

    return any(re.match(pattern, value) for pattern in date_patterns)


def _parse_date_flexible(date_str: str) -> Optional[datetime]:
    """Parse a date string in various formats."""
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


def _interpret_change(change_pct: float, comparison_type: str) -> str:
    """Interpret the meaning of the change."""
    abs_change = abs(change_pct)

    if abs_change < 5:
        return f"Relatively stable {comparison_type}"
    elif change_pct > 0:
        if abs_change < 15:
            return f"Moderate growth {comparison_type}"
        elif abs_change < 30:
            return f"Strong growth {comparison_type}"
        else:
            return f"Exceptional growth {comparison_type}"
    else:
        if abs_change < 15:
            return f"Slight decline {comparison_type}"
        elif abs_change < 30:
            return f"Concerning decline {comparison_type}"
        else:
            return f"Significant decline {comparison_type}"


def _assess_significance(pct_change: float) -> str:
    """Assess the significance of a percentage change."""
    abs_change = abs(pct_change)

    if abs_change < 5:
        return "not_significant"
    elif abs_change < 15:
        return "moderate"
    elif abs_change < 30:
        return "significant"
    else:
        return "highly_significant"


def _get_numeric_columns(data: List[Dict[str, Any]]) -> List[str]:
    """
    Identify numeric columns.

    Phase 2 Day 5: delegates to the unified ``column_classifier``. See
    the rationale in statistics._get_numeric_columns.
    """
    from app.services.analysis_engines.column_classifier import (
        numeric_columns as _classifier_numeric,
    )

    return _classifier_numeric(data)


def _get_categorical_columns(data: List[Dict[str, Any]]) -> List[str]:
    """
    Identify categorical columns.

    Phase 2 Day 5: delegates to the unified ``column_classifier``.
    """
    from app.services.analysis_engines.column_classifier import (
        categorical_columns as _classifier_categorical,
    )

    return _classifier_categorical(data)


def _is_numeric(val: Any) -> bool:
    """Check if a value is numeric."""
    return isinstance(val, (int, float)) and not isinstance(val, bool)


# ============================================================================
# Growth Rate Analysis
# ============================================================================

def calculate_growth_rates(
    time_series: List[Dict[str, Any]],
    value_column: str,
    date_column: str
) -> Dict[str, Any]:
    """
    Calculate various growth rate metrics for a time series.

    Returns:
        - cagr: Compound Annual Growth Rate
        - period_growth_rates: List of period-over-period growth rates
        - average_growth_rate: Average growth rate across periods
        - growth_acceleration: Whether growth is accelerating or decelerating
    """
    if not time_series or len(time_series) < 2:
        return {
            "cagr": 0,
            "period_growth_rates": [],
            "average_growth_rate": 0,
            "growth_acceleration": "unknown"
        }

    # Sort by date
    sorted_data = sorted(time_series, key=lambda x: x.get(date_column, ""))

    # Filter and ensure we have numeric values (int or float)
    values: List[Union[int, float]] = cast(
        List[Union[int, float]],
        [row.get(value_column) for row in sorted_data if _is_numeric(row.get(value_column))]
    )

    if len(values) < 2:
        return {
            "cagr": 0,
            "period_growth_rates": [],
            "average_growth_rate": 0,
            "growth_acceleration": "unknown"
        }

    # Period-over-period growth rates
    growth_rates = []
    for i in range(1, len(values)):
        if values[i - 1] != 0:
            growth_rate = ((values[i] - values[i - 1]) / abs(values[i - 1])) * 100
            growth_rates.append(round(growth_rate, 2))

    # Average growth rate
    avg_growth = statistics.mean(growth_rates) if growth_rates else 0.0

    # CAGR (Compound Annual Growth Rate)
    # CAGR = (Ending Value / Beginning Value) ^ (1 / Number of Periods) - 1
    if values[0] != 0 and values[-1] > 0:
        n_periods = len(values) - 1
        cagr = ((values[-1] / values[0]) ** (1 / n_periods) - 1) * 100
    else:
        cagr = 0.0

    # Growth acceleration (compare first half vs second half)
    mid = len(growth_rates) // 2
    if mid > 0:
        first_half_avg = statistics.mean(growth_rates[:mid])
        second_half_avg = statistics.mean(growth_rates[mid:])

        if second_half_avg > first_half_avg:
            growth_acceleration = "accelerating"
        elif second_half_avg < first_half_avg:
            growth_acceleration = "decelerating"
        else:
            growth_acceleration = "steady"
    else:
        growth_acceleration = "unknown"

    return {
        "cagr": round(cagr, 2),
        "period_growth_rates": growth_rates,
        "average_growth_rate": round(avg_growth, 2),
        "growth_acceleration": growth_acceleration,
        "total_periods": len(values)
    }
