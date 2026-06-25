"""
Insight Detection Engine

Detects patterns, trends, concentration, and anomalies in query results.
"""

import logging
import re
import statistics
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

# Day 2c: column-name patterns that identify ID columns. Case-insensitive.
# ``_id`` / ``^id`` / ``_pk`` are the canonical shapes; we only exclude a
# column if BOTH the name matches AND the column is all-unique in the sample.
_ID_COLUMN_PATTERN = re.compile(r"(?i)(^id$|_id$|_pk$|^pk_)")


def _parse_date_to_ordinal(val: Any) -> Optional[int]:
    """
    Parse a value into a date ordinal (days since year 1, Jan 1).

    Handles:
    - ``datetime`` and ``date`` objects directly
    - ISO-8601 strings such as ``"2024-01-15"``, ``"2024-01-15T10:30:00"``,
      ``"2024-01-15T10:30:00Z"``, and timezone-aware variants
    - Integers/floats (treated as already-ordinal values — caller's choice)

    Returns None if the value cannot be parsed. Callers should skip such
    rows rather than substitute row-index, which is the bug this replaces.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.toordinal()
    if isinstance(val, date):
        return val.toordinal()
    if isinstance(val, (int, float)):
        # Pre-parsed ordinal from another code path; accept as-is.
        try:
            return int(val)
        except (ValueError, OverflowError):
            return None
    if isinstance(val, str):
        # Python 3.11+ fromisoformat is permissive; earlier versions need the
        # "Z" suffix swapped for an explicit offset.
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.toordinal()
        except (ValueError, AttributeError):
            return None
    return None


def detect_insights(
    data: List[Dict[str, Any]],
    analysis_types: Optional[List[str]] = None,
    aggregated: bool = False,
) -> List[Dict[str, Any]]:
    """
    Detect patterns and insights in query results.

    Args:
        data: List of row dictionaries from query results
        analysis_types: List of analysis types to run:
            - "concentration": Pareto analysis, top-N concentration
            - "trend": Linear trends, growth rates, acceleration
            - "anomaly": Outliers, unusual values (z-score)
            - "comparison": Segment comparisons
            - "all": Run all analyses

    Returns:
        List of insights, each with:
            - type: str (concentration, trend, anomaly, comparison)
            - severity: str (high, medium, low)
            - title: str (short description)
            - description: str (detailed explanation)
            - metrics: Dict[str, Any] (supporting data)
            - recommendations: List[str] (suggested actions)
    """
    if not data:
        return []

    if analysis_types is None or "all" in analysis_types:
        analysis_types = ["concentration", "trend", "anomaly", "comparison"]

    insights = []

    # Phase 3c.1: aggregated-mode flag flows into every detector via a
    # kwarg so each can apply its own threshold recalibration. Gated by
    # FIX_AGGREGATED_MODE_THRESHOLDS — off reverts to the legacy
    # raw-only thresholds for emergency rollback.
    agg = aggregated and settings.FIX_AGGREGATED_MODE_THRESHOLDS

    if "concentration" in analysis_types:
        insights.extend(_detect_concentration(data, aggregated=agg))

    if "trend" in analysis_types:
        insights.extend(_detect_trends(data, aggregated=agg))

    if "anomaly" in analysis_types:
        insights.extend(_detect_anomalies(data, aggregated=agg))

    if "comparison" in analysis_types:
        insights.extend(_detect_comparisons(data, aggregated=agg))

    # Sort by severity first (high > medium > low) so the dedup step below
    # keeps the highest-severity insight per (type, column_name) pair.
    severity_order = {"high": 0, "medium": 1, "low": 2}
    insights.sort(key=lambda x: severity_order.get(x.get("severity", ""), 3))

    # Day 2b: deduplicate by (type, column_name). Common source: the trend
    # detector's ``date_cols x numeric_cols`` loop emits the same insight
    # once per date column (the exact "policy_id trend shown twice" user
    # complaint). Flag amnesty 2026-05-12: FIX_INSIGHT_DEDUPLICATION and
    # FIX_COLUMN_NAME_FIELD rollback paths removed; dedup is now permanent.
    #
    # Keep the highest-severity insight per (type, column_name). The prior
    # severity sort puts "high" before "medium" before "low", so we track
    # the minimum (best) severity rank per key.
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    best: Dict[tuple, Dict[str, Any]] = {}
    dup_drops = 0
    for insight in insights:
        key = (
            insight.get("type", ""),
            insight.get("column_name", ""),
        )
        incoming_rank = severity_rank.get(insight.get("severity", ""), 3)
        if key in best:
            existing_rank = severity_rank.get(best[key].get("severity", ""), 3)
            if incoming_rank < existing_rank:
                best[key] = insight
            dup_drops += 1
        else:
            best[key] = insight
    if dup_drops:
        try:
            from app.api.metrics import record_fix_event
            for _ in range(dup_drops):
                record_fix_event("insight_deduplication")
        except Exception:
            pass
        logger.debug(
            "detect_insights: dedup dropped %d duplicate insight(s)",
            dup_drops,
        )
    # Preserve severity ordering: sort the survivors the same way.
    insights = sorted(
        best.values(),
        key=lambda x: severity_rank.get(x.get("severity", ""), 3),
    )

    return insights


def _detect_concentration(
    data: List[Dict[str, Any]],
    aggregated: bool = False,
) -> List[Dict[str, Any]]:
    """
    Detect concentration risk - Pareto principle analysis.

    Checks if a small number of items drive most of the value.

    Phase 3c.1: ``aggregated=True`` doesn't change the minimum-row
    floor (5 is already a reasonable minimum for Pareto on groups),
    but is reserved for future threshold tuning.
    """
    insights: List[Dict[str, Any]] = []

    # Need at least 5 rows for meaningful concentration analysis
    if len(data) < 5:
        return insights

    # Find numeric columns (potential value columns)
    numeric_cols = _get_numeric_columns(data)

    for col in numeric_cols:
        values = [row.get(col, 0) for row in data if _is_numeric(row.get(col))]

        if not values or len(values) < 5:
            continue

        # Sort descending
        sorted_values = sorted(values, reverse=True)
        total = sum(sorted_values)

        if total == 0:
            continue

        # Calculate top-N percentages
        top_3_sum = sum(sorted_values[:3])
        top_5_sum = sum(sorted_values[:5])
        top_10_sum = sum(sorted_values[:min(10, len(sorted_values))])

        top_3_pct = (top_3_sum / total) * 100
        top_5_pct = (top_5_sum / total) * 100
        top_10_pct = (top_10_sum / total) * 100

        # Gini coefficient (0 = perfect equality, 1 = perfect inequality)
        gini = _calculate_gini(sorted_values)

        # Determine severity based on concentration
        insight: Optional[Dict[str, Any]] = None
        if top_3_pct > 50:
            insight = {
                "type": "concentration",
                "severity": "high",
                "title": f"High Concentration Risk in {col}",
                "description": f"Top 3 items represent {top_3_pct:.1f}% of total {col}",
                "metrics": {
                    "top_3_pct": round(top_3_pct, 1),
                    "top_5_pct": round(top_5_pct, 1),
                    "gini_coefficient": round(gini, 2),
                    "total_items": len(values),
                },
                "recommendations": [
                    f"Diversify: Top 3 items are {top_3_pct:.0f}% of {col}",
                    "Analyze dependency on these key items",
                    "Consider risk mitigation strategies",
                ],
            }
        elif top_5_pct > 60:
            insight = {
                "type": "concentration",
                "severity": "medium",
                "title": f"Moderate Concentration in {col}",
                "description": f"Top 5 items represent {top_5_pct:.1f}% of total {col}",
                "metrics": {
                    "top_5_pct": round(top_5_pct, 1),
                    "top_10_pct": round(top_10_pct, 1),
                    "gini_coefficient": round(gini, 2),
                    "total_items": len(values),
                },
                "recommendations": [
                    f"Monitor: Top 5 items drive {top_5_pct:.0f}% of {col}",
                    "Track changes in top performers over time",
                ],
            }

        if insight is not None:
            # Day 2a: attach column reference for dedup + ColumnClassifier.
            # (Flag amnesty 2026-05-12: FIX_COLUMN_NAME_FIELD always-on.)
            insight["column_name"] = col
            try:
                from app.api.metrics import record_fix_event
                record_fix_event("column_name_field")
            except Exception:
                pass
            insights.append(insight)

    return insights


def _detect_trends(
    data: List[Dict[str, Any]],
    aggregated: bool = False,
) -> List[Dict[str, Any]]:
    """
    Detect trends in time series data.

    Looks for linear trends, growth rates, acceleration/deceleration.

    Phase 3c.1: aggregated mode requires >= 5 groups (was 3 for raw).
    Slope fitting on 3-4 group points is noise — any monotonic 3-point
    sequence shows "100% up-trend" even if it's nothing interesting.
    """
    insights: List[Dict[str, Any]] = []

    min_points = 5 if aggregated else 3
    if len(data) < min_points:
        return insights

    # Try to find date/time columns
    date_cols = _get_date_columns(data)
    numeric_cols = _get_numeric_columns(data)

    if not date_cols or not numeric_cols:
        return insights

    # Day 2c: use real date ordinals as the x-axis. The legacy path used
    # ``enumerate()`` as the x-axis, which produces misleading slopes for
    # any non-uniform time series (and absurd results for numeric columns
    # that happen to be sorted by value, such as IDs).
    # (Flag amnesty 2026-05-12: FIX_DATE_BASED_TRENDS rollback removed;
    # use_date_axis is now an effective constant. The variable is kept to
    # preserve the local conditional structure pending a follow-up
    # cleanup PR.)
    use_date_axis = True

    # Analyze each numeric column over time
    for date_col in date_cols:
        for value_col in numeric_cols:
            # Extract time series
            time_series: List[Tuple[float, float]] = []
            parsed_from_dates = False  # were any rows mapped via real dates?

            for i, row in enumerate(data):
                date_val = row.get(date_col)
                num_val = row.get(value_col)

                if not _is_numeric(num_val):
                    continue

                if use_date_axis:
                    ordinal = _parse_date_to_ordinal(date_val)
                    if ordinal is None:
                        # Unparseable or missing date — skip this row rather
                        # than substitute the row index (which is the bug
                        # we're fixing).
                        continue
                    time_series.append((float(ordinal), float(num_val)))  # type: ignore[arg-type]
                    parsed_from_dates = True
                else:
                    if date_val is None:
                        continue
                    time_series.append((float(i), float(num_val)))  # type: ignore[arg-type]

            if len(time_series) < min_points:
                continue

            # Day 2c: sort by x-coordinate so regression sees points in true
            # temporal order regardless of how the query returned rows.
            time_series.sort(key=lambda pair: pair[0])

            if use_date_axis and parsed_from_dates:
                try:
                    from app.api.metrics import record_fix_event
                    record_fix_event("date_based_trends")
                except Exception:
                    pass

            # Linear regression on sorted series
            x_vals = [x for x, _ in time_series]
            y_vals = [y for _, y in time_series]

            slope, intercept, r_squared = _linear_regression(x_vals, y_vals)

            # Determine trend strength
            if r_squared < 0.5:
                continue  # Weak trend, skip

            # Calculate growth rate
            if len(y_vals) > 0 and y_vals[0] != 0:
                total_growth = ((y_vals[-1] - y_vals[0]) / abs(y_vals[0])) * 100
            else:
                total_growth = 0.0

            # Determine trend direction and acceleration
            trend_direction = "increasing" if slope > 0 else "decreasing"

            # Check for acceleration (compare first half vs second half growth)
            mid = len(y_vals) // 2
            first_half_vals = [v for v in y_vals[:mid] if v is not None]
            second_half_vals = [v for v in y_vals[mid:] if v is not None]

            acceleration = "steady"
            if first_half_vals and second_half_vals:
                first_half_avg = statistics.mean(first_half_vals)
                second_half_avg = statistics.mean(second_half_vals)

                if first_half_avg != 0 and abs((second_half_avg - first_half_avg) / first_half_avg) > 0.1:
                    if (slope > 0 and second_half_avg > first_half_avg) or \
                       (slope < 0 and second_half_avg < first_half_avg):
                        acceleration = "accelerating"
                    else:
                        acceleration = "decelerating"

            severity = "medium" if abs(total_growth) > 20 else "low"

            # Day 2c: when using the date axis, x_vals are day-ordinals. The
            # slope is therefore "per day" and we can report the time span
            # explicitly in the recommendation. Legacy path reports "per row".
            if use_date_axis:
                period_days = int(x_vals[-1] - x_vals[0]) if x_vals else 0
                slope_label = "per day"
                growth_label = (
                    f"Growth rate: {total_growth:.1f}% over {period_days} days"
                )
            else:
                period_days = None
                slope_label = "per row"
                growth_label = f"Growth rate: {total_growth:.1f}% over period"

            insight: Dict[str, Any] = {
                "type": "trend",
                "severity": severity,
                "title": f"{value_col} is {trend_direction} ({acceleration})",
                "description": f"{value_col} shows a {trend_direction} trend of {total_growth:.1f}% ({acceleration})",
                "metrics": {
                    "slope": round(slope, 4),
                    "slope_unit": slope_label,
                    "r_squared": round(r_squared, 3),
                    "total_growth_pct": round(total_growth, 1),
                    "direction": trend_direction,
                    "acceleration": acceleration,
                    "data_points": len(time_series),
                },
                "recommendations": [
                    f"Trend equation: y = {slope:.4f}x + {intercept:.2f} (R²={r_squared:.3f})",
                    growth_label,
                    f"Pattern: {acceleration} {trend_direction}",
                ],
            }
            if period_days is not None:
                insight["metrics"]["time_period_days"] = period_days

            # Day 2a: attach the value column for dedup + ColumnClassifier use.
            # (Flag amnesty 2026-05-12: FIX_COLUMN_NAME_FIELD always-on.)
            insight["column_name"] = value_col
            try:
                from app.api.metrics import record_fix_event
                record_fix_event("column_name_field")
            except Exception:
                pass

            insights.append(insight)

    return insights


def _detect_anomalies(
    data: List[Dict[str, Any]],
    aggregated: bool = False,
) -> List[Dict[str, Any]]:
    """
    Detect outliers using z-score method.

    Flags values that are >3 standard deviations from mean.

    Phase 3c.1: aggregated mode tightens the z-score floor from 3 to 2.
    Reason: with fewer data points (typically 5-30 group rows), the
    sample stdev is biased low and thin tails mean a 3-sigma value is
    essentially never observed — the legacy threshold silently hides
    genuine outliers in aggregated queries. Raw mode keeps z=3 so we
    don't swamp the UI with noisy outliers on 1000-row result sets.
    """
    insights: List[Dict[str, Any]] = []

    # Need at least 5 rows for meaningful outlier detection
    if len(data) < 5:
        return insights

    z_threshold = 2.0 if aggregated else 3.0

    numeric_cols = _get_numeric_columns(data)

    for col in numeric_cols:
        values = [row.get(col, 0) for row in data if _is_numeric(row.get(col))]

        if len(values) < 5:
            continue

        mean = statistics.mean(values)

        try:
            stdev = statistics.stdev(values)
        except statistics.StatisticsError:
            continue  # All values are the same

        if stdev == 0:
            continue

        # Find outliers (z-score > threshold; 3.0 raw, 2.0 aggregated).
        outliers = []
        for i, row in enumerate(data):
            val = row.get(col)
            if _is_numeric(val):
                z_score = (val - mean) / stdev
                if abs(z_score) > z_threshold:
                    # Try to get identifier column
                    identifier = _get_row_identifier(row, data)
                    outliers.append({
                        "value": val,
                        "z_score": round(z_score, 2),
                        "identifier": identifier,
                        "row_index": i
                    })

        if outliers:
            insight = {
                "type": "anomaly",
                "severity": "medium",
                "title": f"{len(outliers)} outlier(s) detected in {col}",
                "description": f"Found {len(outliers)} value(s) >3σ from mean in {col}",
                "metrics": {
                    "outlier_count": len(outliers),
                    "mean": round(mean, 2),
                    "std_dev": round(stdev, 2),
                    "outliers": outliers[:3],  # Limit to first 3
                },
                "recommendations": [
                    "Verify data quality for outlier values",
                    "Investigate if outliers are data errors or legitimate edge cases",
                    "Consider impact on aggregate statistics",
                ],
            }
            # Day 2a: attach column reference for dedup + ColumnClassifier.
            # (Flag amnesty 2026-05-12: FIX_COLUMN_NAME_FIELD always-on.)
            insight["column_name"] = col
            try:
                from app.api.metrics import record_fix_event
                record_fix_event("column_name_field")
            except Exception:
                pass
            insights.append(insight)

    return insights


def _detect_comparisons(
    data: List[Dict[str, Any]],
    aggregated: bool = False,
) -> List[Dict[str, Any]]:
    """
    Compare segments or categories in the data.

    Identifies significant differences between groups.

    Phase 3c.1: ``aggregated`` is accepted for consistency; segment
    comparison already operates on grouped subsets and its thresholds
    don't need recalibration. The parameter is reserved for future
    tuning (e.g. different max-ratio floors for pre-aggregated inputs).
    """
    insights: List[Dict[str, Any]] = []

    # Need at least 4 rows for meaningful comparison
    if len(data) < 4:
        return insights

    # Find categorical columns (potential segment columns)
    categorical_cols = _get_categorical_columns(data)
    numeric_cols = _get_numeric_columns(data)

    if not categorical_cols or not numeric_cols:
        return insights

    # Compare each categorical column against numeric columns
    for cat_col in categorical_cols:
        for num_col in numeric_cols:
            # Group by category
            groups: Dict[Any, List[float]] = {}
            for row in data:
                category = row.get(cat_col)
                value = row.get(num_col)

                if category is not None and value is not None and _is_numeric(value):
                    if category not in groups:
                        groups[category] = []
                    groups[category].append(float(value))

            # Need at least 2 groups with 2+ values each
            valid_groups = {k: v for k, v in groups.items() if len(v) >= 2}
            if len(valid_groups) < 2:
                continue

            # Calculate means for each group
            group_means = {k: statistics.mean(v) for k, v in valid_groups.items()}
            overall_mean = statistics.mean([v for vals in valid_groups.values() for v in vals])

            # Find groups significantly different from average (>30%)
            significant_diffs = []
            for group, mean_val in group_means.items():
                if overall_mean != 0:
                    pct_diff = ((mean_val - overall_mean) / abs(overall_mean)) * 100
                    if abs(pct_diff) > 30:
                        significant_diffs.append({
                            "group": group,
                            "mean": round(mean_val, 2),
                            "pct_diff_from_avg": round(pct_diff, 1)
                        })

            if significant_diffs:
                insight = {
                    "type": "comparison",
                    "severity": "medium",
                    "title": f"Significant variation in {num_col} by {cat_col}",
                    "description": f"Some {cat_col} groups differ significantly from average {num_col}",
                    "metrics": {
                        "overall_mean": round(overall_mean, 2),
                        "group_count": len(valid_groups),
                        "significant_differences": significant_diffs,
                    },
                    "recommendations": [
                        f"Investigate why certain {cat_col} groups differ",
                        "Consider segment-specific strategies",
                    ],
                }
                # Day 2a: attach the numeric column as the primary reference
                # (the one being compared across categories). Also record the
                # category column for completeness.
                # (Flag amnesty 2026-05-12: FIX_COLUMN_NAME_FIELD always-on.)
                insight["column_name"] = num_col
                insight["category_column"] = cat_col
                try:
                    from app.api.metrics import record_fix_event
                    record_fix_event("column_name_field")
                except Exception:
                    pass
                insights.append(insight)

    return insights


# ============================================================================
# Helper Functions
# ============================================================================

def _get_numeric_columns(data: List[Dict[str, Any]]) -> List[str]:
    """
    Identify numeric columns.

    Phase 2 Day 5: delegates to the unified ``column_classifier`` so
    smart-ID exclusion semantics are shared across all analysis engines.
    """
    from app.services.analysis_engines.column_classifier import (
        ColumnType,
        classify_columns,
    )

    classified = classify_columns(data)
    # Report the smart_id_exclusion fix event for any column the
    # classifier marked as ID-heuristic (preserves the Phase 1 metric).
    id_hits = [c for c in classified.values() if c.is_id_heuristic]
    if id_hits:
        try:
            from app.api.metrics import record_fix_event

            for _ in id_hits:
                record_fix_event("smart_id_exclusion")
        except Exception:
            pass

    return [c.name for c in classified.values() if c.type is ColumnType.NUMERIC]


def _get_date_columns(data: List[Dict[str, Any]]) -> List[str]:
    """
    Identify date/time columns.

    Phase 2 Day 5: delegates to the unified classifier.
    """
    from app.services.analysis_engines.column_classifier import (
        date_columns as _classifier_date,
    )

    return _classifier_date(data)


def _get_categorical_columns(data: List[Dict[str, Any]]) -> List[str]:
    """
    Identify categorical columns.

    Phase 2 Day 5: delegates to the unified classifier.
    """
    from app.services.analysis_engines.column_classifier import (
        categorical_columns as _classifier_categorical,
    )

    return _classifier_categorical(data)


def _is_numeric(val: Any) -> bool:
    """Check if a value is numeric."""
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _is_date(val: Any) -> bool:
    """Check if a value is a date/datetime object."""
    return isinstance(val, (datetime,))


def _looks_like_date(col_name: str) -> bool:
    """Check if column name suggests it's a date."""
    date_keywords = ["date", "time", "timestamp", "created", "updated", "month", "year", "day"]
    col_lower = col_name.lower()
    return any(keyword in col_lower for keyword in date_keywords)


def _get_row_identifier(row: Dict[str, Any], data: List[Dict[str, Any]]) -> str:
    """Try to find an identifier for this row (name, id, etc.)."""
    # Common identifier column names
    id_columns = ["name", "id", "customer", "product", "user", "account"]

    for col in id_columns:
        for key in row.keys():
            if col in key.lower():
                return f"{key}={row[key]}"

    # Fallback: use first column
    if row:
        first_col = list(row.keys())[0]
        return f"{first_col}={row[first_col]}"

    return "unknown"


def _calculate_gini(values: List[float]) -> float:
    """
    Calculate Gini coefficient (inequality measure).

    0 = perfect equality, 1 = perfect inequality
    """
    if not values or sum(values) == 0:
        return 0.0

    sorted_values = sorted(values)
    n = len(sorted_values)
    cumsum = []
    total = 0.0
    for val in sorted_values:
        total += val
        cumsum.append(total)

    sum_of_absolute_diffs = sum(
        abs(cumsum[i] - cumsum[j])
        for i in range(n)
        for j in range(n)
    )

    gini = sum_of_absolute_diffs / (2 * n * sum(sorted_values))
    return gini


def _linear_regression(x: List[float], y: List[float]) -> tuple:
    """
    Simple linear regression: y = mx + b

    Returns: (slope, intercept, r_squared)
    """
    n = len(x)
    if n < 2:
        return 0, 0, 0

    x_mean = statistics.mean(x)
    y_mean = statistics.mean(y)

    # Calculate slope
    numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return 0, y_mean, 0

    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    # Calculate R²
    y_pred = [slope * x[i] + intercept for i in range(n)]
    ss_res = sum((y[i] - y_pred[i]) ** 2 for i in range(n))
    ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))

    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

    return slope, intercept, r_squared
