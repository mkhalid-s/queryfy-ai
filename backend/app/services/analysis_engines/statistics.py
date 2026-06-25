"""
Statistical Analysis Engine

Computes advanced statistics beyond basic aggregations (sum, avg, min, max).
Provides percentiles, standard deviation, IQR, skewness, Gini coefficient, etc.
"""

import statistics
from typing import Any, Dict, List, Optional


def compute_statistics(
    data: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    aggregated: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute comprehensive statistics for numeric columns.

    Args:
        data: List of row dictionaries from query results
        columns: Optional list of column names to analyze (default: all numeric)
        aggregated: True when ``data`` is the result of a GROUP BY (Phase
            3a.3 detection). In aggregated mode, concentration metrics
            (Gini / HHI / top-20%) are SUPPRESSED — they describe
            inequality of group totals, not inequality of underlying
            row-level values, and labelling them the same way is
            misleading. The other stats remain meaningful (e.g. "median
            sales per region" is a valid statement about 5 region rows).

    Returns:
        Dictionary keyed by column name. Same shape as before, except
        ``concentration`` is ``None`` and a new ``concentration_skipped_reason``
        marker is added when ``aggregated=True``.
    """
    if not data:
        return {}

    # Auto-detect numeric columns if not specified
    if columns is None:
        columns = _get_numeric_columns(data)

    result = {}

    for col in columns:
        raw_values = [row.get(col) for row in data if _is_numeric(row.get(col))]

        if not raw_values:
            continue

        # Convert to float list, filtering None
        values = [float(v) for v in raw_values if v is not None]
        stats = _compute_column_statistics(values, aggregated=aggregated)
        result[col] = stats

    return result


def _compute_column_statistics(
    values: List[float],
    aggregated: bool = False,
) -> Dict[str, Any]:
    """Compute statistics for a single column's values."""
    if not values:
        return {}

    n = len(values)
    sorted_values = sorted(values)

    # Basic stats
    mean_val = statistics.mean(values)
    median_val = statistics.median(values)
    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val

    # Variance and standard deviation
    try:
        variance = statistics.variance(values) if n > 1 else 0
        std_dev = statistics.stdev(values) if n > 1 else 0
    except statistics.StatisticsError:
        variance = 0
        std_dev = 0

    # Quartiles
    q1 = _percentile(sorted_values, 25)
    q3 = _percentile(sorted_values, 75)
    iqr = q3 - q1

    # Coefficient of variation (normalized std dev)
    cv = (std_dev / mean_val) if mean_val != 0 else 0

    # Skewness (measure of asymmetry)
    skewness = _calculate_skewness(values, mean_val, std_dev)

    # Concentration metrics — Phase 4 cross-phase fix: in aggregated
    # mode the values are already group-level totals, so Gini/HHI/top-
    # 20% measure inequality OF AGGREGATES which is a different
    # semantic. Suppress to avoid misleading "concentration" callouts.
    if aggregated:
        concentration = None
        concentration_skipped = "aggregated_mode"
    else:
        concentration = _calculate_concentration(sorted_values)
        concentration_skipped = None

    return {
        "count": n,
        "mean": round(mean_val, 2),
        "median": round(median_val, 2),
        "std_dev": round(std_dev, 2),
        "variance": round(variance, 2),
        "min": round(min_val, 2),
        "max": round(max_val, 2),
        "q1": round(q1, 2),
        "q3": round(q3, 2),
        "iqr": round(iqr, 2),
        "range": round(range_val, 2),
        "skewness": round(skewness, 2),
        "cv": round(cv, 2),
        "concentration": concentration,
        "concentration_skipped_reason": concentration_skipped,
        "percentiles": {
            "p10": round(_percentile(sorted_values, 10), 2),
            "p25": round(q1, 2),
            "p50": round(median_val, 2),
            "p75": round(q3, 2),
            "p90": round(_percentile(sorted_values, 90), 2),
            "p95": round(_percentile(sorted_values, 95), 2),
            "p99": round(_percentile(sorted_values, 99), 2),
        }
    }


def _percentile(sorted_values: List[float], p: float) -> float:
    """
    Calculate the p-th percentile of sorted values.

    Args:
        sorted_values: List of values sorted in ascending order
        p: Percentile to calculate (0-100)

    Returns:
        The value at the p-th percentile
    """
    if not sorted_values:
        return 0.0

    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    # Linear interpolation method
    k = (n - 1) * (p / 100)
    f = int(k)
    c = k - f

    if f + 1 < n:
        return sorted_values[f] + c * (sorted_values[f + 1] - sorted_values[f])
    else:
        return sorted_values[f]


def _calculate_skewness(values: List[float], mean: float, std_dev: float) -> float:
    """
    Calculate skewness (Fisher-Pearson coefficient of skewness).

    Skewness measures the asymmetry of the distribution:
    - 0: Symmetric (normal distribution)
    - > 0: Right-skewed (long tail on the right)
    - < 0: Left-skewed (long tail on the left)
    """
    if not values or std_dev == 0:
        return 0.0

    n = len(values)
    m3 = sum((x - mean) ** 3 for x in values) / n
    skewness = m3 / (std_dev ** 3)

    return skewness


def _calculate_concentration(sorted_values: List[float]) -> Dict[str, Any]:
    """
    Calculate concentration metrics.

    Returns:
        - gini: Gini coefficient (0 = equal, 1 = concentrated)
        - hhi: Herfindahl-Hirschman Index
        - top_10_pct: Percentage of total in top 10%
        - top_20_pct: Percentage of total in top 20%
        - top_50_pct: Percentage of total in top 50%
    """
    if not sorted_values:
        return {
            "gini": 0,
            "hhi": 0,
            "top_10_pct": 0,
            "top_20_pct": 0,
            "top_50_pct": 0
        }

    # Reverse to descending order for top-N calculations
    desc_values = sorted(sorted_values, reverse=True)
    total = sum(desc_values)

    if total == 0:
        return {
            "gini": 0,
            "hhi": 0,
            "top_10_pct": 0,
            "top_20_pct": 0,
            "top_50_pct": 0
        }

    n = len(desc_values)

    # Gini coefficient
    gini = _calculate_gini(sorted_values)

    # HHI (Herfindahl-Hirschman Index)
    # Sum of squared market shares (0 = many small, 10000 = monopoly)
    hhi = sum((val / total * 100) ** 2 for val in desc_values)

    # Top-N percentages
    top_10_idx = max(1, int(n * 0.1))
    top_20_idx = max(1, int(n * 0.2))
    top_50_idx = max(1, int(n * 0.5))

    top_10_pct = (sum(desc_values[:top_10_idx]) / total) * 100
    top_20_pct = (sum(desc_values[:top_20_idx]) / total) * 100
    top_50_pct = (sum(desc_values[:top_50_idx]) / total) * 100

    return {
        "gini": round(gini, 3),
        "hhi": round(hhi, 1),
        "top_10_pct": round(top_10_pct, 1),
        "top_20_pct": round(top_20_pct, 1),
        "top_50_pct": round(top_50_pct, 1)
    }


def _calculate_gini(sorted_values: List[float]) -> float:
    """
    Calculate Gini coefficient (inequality measure).

    0 = perfect equality, 1 = perfect inequality
    """
    if not sorted_values:
        return 0.0

    total = sum(sorted_values)
    if total == 0:
        return 0.0

    n = len(sorted_values)
    cumsum = []
    running_total = 0.0
    for val in sorted_values:
        running_total += val
        cumsum.append(running_total)

    # Calculate Gini using the formula:
    # G = (2 * sum(i * y_i)) / (n * sum(y_i)) - (n + 1) / n
    weighted_sum = sum((i + 1) * sorted_values[i] for i in range(n))
    gini = (2 * weighted_sum) / (n * total) - (n + 1) / n

    return max(0.0, min(1.0, gini))  # Clamp to [0, 1]


def _get_numeric_columns(data: List[Dict[str, Any]]) -> List[str]:
    """
    Identify numeric columns.

    Phase 2 Day 5: delegates to the unified ``column_classifier`` so that
    all analysis engines produce the same answer. The legacy inline
    implementation did not honour the Day 2c smart-ID exclusion, which
    meant statistics were happily computed on ``policy_id`` (and the
    resulting 18865% trend motivated the Phase 1 remediation).
    """
    from app.services.analysis_engines.column_classifier import (
        numeric_columns as _classifier_numeric,
    )

    return _classifier_numeric(data)


def _is_numeric(val: Any) -> bool:
    """Check if a value is numeric."""
    return isinstance(val, (int, float)) and not isinstance(val, bool)


# ============================================================================
# Distribution Analysis
# ============================================================================

def analyze_distribution(values: List[float]) -> Dict[str, Any]:
    """
    Analyze the distribution of values.

    Returns:
        - distribution_type: str (normal, skewed_right, skewed_left, uniform, bimodal)
        - normality_score: float (0-1, how close to normal distribution)
        - outlier_count: int (values >3σ from mean)
    """
    if not values or len(values) < 5:
        return {
            "distribution_type": "unknown",
            "normality_score": 0,
            "outlier_count": 0
        }

    mean = statistics.mean(values)

    try:
        std_dev = statistics.stdev(values)
    except statistics.StatisticsError:
        std_dev = 0

    # Skewness for distribution type
    skewness = _calculate_skewness(values, mean, std_dev)

    if abs(skewness) < 0.5:
        distribution_type = "normal"
        normality_score = 1.0 - abs(skewness)
    elif skewness > 0.5:
        distribution_type = "skewed_right"
        normality_score = 0.5
    elif skewness < -0.5:
        distribution_type = "skewed_left"
        normality_score = 0.5
    else:
        distribution_type = "unknown"
        normality_score = 0.3

    # Count outliers (>3σ)
    outlier_count = 0
    if std_dev > 0:
        for val in values:
            z_score = abs((val - mean) / std_dev)
            if z_score > 3:
                outlier_count += 1

    return {
        "distribution_type": distribution_type,
        "normality_score": round(normality_score, 2),
        "outlier_count": outlier_count,
        "skewness": round(skewness, 2)
    }
