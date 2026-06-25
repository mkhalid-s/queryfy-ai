"""
Data Quality Assessment Engine

Assesses data quality and completeness of query results.
Reports issues that might affect analysis confidence.
"""

import statistics
from datetime import date, datetime
from typing import Any, Dict, List, cast


def assess_data_quality(
    data: List[Dict[str, Any]],
    aggregated: bool = False,
) -> Dict[str, Any]:
    """
    Assess data quality of query results.

    Args:
        data: rows
        aggregated: True when ``data`` is the result of a GROUP BY
            (Phase 3a.3 detection). In aggregated mode, "duplicate row"
            and "outlier" semantics shift — a duplicate region row is
            ambiguous and an outlier in group totals isn't an error.
            Currently the parameter is accepted for forward-compat;
            future work will adjust thresholds. Today the only
            behavioural change is that the response carries
            ``aggregated_mode: True`` so the UI can label scores as
            "data quality of the aggregated view" rather than the
            underlying rows.

    Returns: same shape as before, plus ``aggregated_mode: bool``.
    """
    if not data:
        return {
            "overall_score": 0,
            "completeness": 0,
            "null_pct": 100,
            "duplicate_count": 0,
            "outlier_count": 0,
            "issues": [{"severity": "error", "description": "No data returned"}],
            "column_quality": {}
        }

    issues = []
    column_quality = {}

    # Get all columns from first row
    columns = list(data[0].keys()) if data else []

    # Analyze each column
    total_cells = len(data) * len(columns) if columns else 0
    null_cells = 0
    outlier_count = 0

    for col in columns:
        col_issues = _assess_column_quality(data, col)
        column_quality[col] = col_issues["metrics"]
        issues.extend(col_issues["issues"])
        null_cells += col_issues["metrics"]["null_count"]
        outlier_count += col_issues["metrics"]["outlier_count"]

    # Check for duplicate rows
    duplicate_count = _count_duplicates(data)
    if duplicate_count > 0:
        issues.append({
            "severity": "warning",
            "description": f"{duplicate_count} duplicate row(s) detected"
        })

    # Calculate overall metrics
    null_pct = (null_cells / total_cells * 100) if total_cells > 0 else 0
    completeness = 100 - null_pct

    # Calculate overall quality score (0-100)
    overall_score = _calculate_quality_score(
        completeness=completeness,
        duplicate_count=duplicate_count,
        outlier_count=outlier_count,
        row_count=len(data)
    )

    return {
        "overall_score": overall_score,
        "completeness": round(completeness, 1),
        "null_pct": round(null_pct, 1),
        "duplicate_count": duplicate_count,
        "outlier_count": outlier_count,
        "issues": issues,
        "column_quality": column_quality,
        "row_count": len(data),
        "column_count": len(columns),
        # Phase 4 cross-phase wiring: lets the UI label the score
        # contextually ("Quality of the aggregated view: 92/100").
        "aggregated_mode": aggregated,
    }


def _assess_column_quality(data: List[Dict[str, Any]], col: str) -> Dict[str, Any]:
    """Assess quality of a single column."""
    issues = []
    values = [row.get(col) for row in data]

    # Count nulls
    null_count = sum(1 for v in values if v is None)
    null_pct = (null_count / len(values) * 100) if values else 0

    if null_pct > 50:
        issues.append({
            "severity": "high",
            "description": f"Column '{col}' has {null_pct:.1f}% null values"
        })
    elif null_pct > 20:
        issues.append({
            "severity": "medium",
            "description": f"Column '{col}' has {null_pct:.1f}% null values"
        })

    # Check for outliers in numeric columns
    # Cast to List[float] since _is_numeric() filters for int/float types
    filtered_values = [v for v in values if _is_numeric(v)]
    numeric_values: List[float] = cast(List[float], filtered_values)
    outlier_count = 0

    if numeric_values and len(numeric_values) >= 5:
        mean: float = statistics.mean(numeric_values)
        try:
            std_dev: float = statistics.stdev(numeric_values)
        except statistics.StatisticsError:
            std_dev = 0.0

        if std_dev > 0:
            for val in numeric_values:
                z_score = abs((val - mean) / std_dev)
                if z_score > 3:
                    outlier_count += 1

        if outlier_count > 0:
            issues.append({
                "severity": "low",
                "description": f"Column '{col}' has {outlier_count} outlier(s) (>3σ from mean)"
            })

    # Check for low cardinality (potential data issues)
    unique_values = set(v for v in values if v is not None)
    unique_pct = (len(unique_values) / len(values) * 100) if values else 0

    if len(unique_values) == 1 and len(values) > 1:
        issues.append({
            "severity": "low",
            "description": f"Column '{col}' has only 1 unique value (constant column)"
        })

    # Check for suspicious patterns (e.g., all zeros, all same value)
    if numeric_values and len(numeric_values) > 5:
        if all(v == 0 for v in numeric_values):
            issues.append({
                "severity": "medium",
                "description": f"Column '{col}' has all zero values"
            })

    return {
        "metrics": {
            "null_count": null_count,
            "null_pct": round(null_pct, 1),
            "unique_count": len(unique_values),
            "unique_pct": round(unique_pct, 1),
            "outlier_count": outlier_count,
            "data_type": _infer_data_type(values)
        },
        "issues": issues
    }


def _count_duplicates(data: List[Dict[str, Any]]) -> int:
    """Count duplicate rows in the data."""
    seen = set()
    duplicates = 0

    for row in data:
        # Convert row to hashable tuple
        try:
            row_tuple = tuple(sorted(row.items()))
            if row_tuple in seen:
                duplicates += 1
            else:
                seen.add(row_tuple)
        except (TypeError, ValueError):
            # Skip unhashable rows
            continue

    return duplicates


def _calculate_quality_score(
    completeness: float,
    duplicate_count: int,
    outlier_count: int,
    row_count: int
) -> int:
    """
    Calculate overall data quality score (0-100).

    Factors:
    - Completeness (weight: 50%)
    - Duplicates (weight: 25%)
    - Outliers (weight: 25%)
    """
    # Completeness score (0-50)
    completeness_score = (completeness / 100) * 50

    # Duplicate penalty (0-25)
    duplicate_pct = (duplicate_count / row_count * 100) if row_count > 0 else 0
    duplicate_score = max(0, 25 - duplicate_pct)

    # Outlier penalty (0-25)
    outlier_pct = (outlier_count / row_count * 100) if row_count > 0 else 0
    outlier_score = max(0, 25 - outlier_pct)

    total_score = completeness_score + duplicate_score + outlier_score
    return int(min(100, max(0, total_score)))


def _infer_data_type(values: List[Any]) -> str:
    """Infer the data type of a column from its values."""
    non_null_values = [v for v in values if v is not None]

    if not non_null_values:
        return "null"

    # Check first non-null value
    sample = non_null_values[0]

    if isinstance(sample, bool):
        return "boolean"
    elif isinstance(sample, int):
        return "integer"
    elif isinstance(sample, float):
        return "float"
    elif isinstance(sample, (datetime, date)):
        return "date"
    elif isinstance(sample, str):
        # Check if it's a date string
        if _looks_like_date(sample):
            return "date_string"
        return "string"
    elif isinstance(sample, (list, dict)):
        return "complex"
    else:
        return "unknown"


def _looks_like_date(value: str) -> bool:
    """Check if a string looks like a date."""
    date_patterns = [
        r"\d{4}-\d{2}-\d{2}",  # YYYY-MM-DD
        r"\d{2}/\d{2}/\d{4}",  # MM/DD/YYYY
        r"\d{4}/\d{2}/\d{2}",  # YYYY/MM/DD
    ]

    import re
    return any(re.match(pattern, value) for pattern in date_patterns)


def _is_numeric(val: Any) -> bool:
    """Check if a value is numeric."""
    return isinstance(val, (int, float)) and not isinstance(val, bool)


# ============================================================================
# Data Completeness Analysis
# ============================================================================

def analyze_completeness(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Detailed completeness analysis.

    Returns:
        - overall_completeness: float (percentage)
        - column_completeness: Dict[str, float] (per-column completeness)
        - missing_patterns: List[str] (patterns in missing data)
    """
    if not data:
        return {
            "overall_completeness": 0,
            "column_completeness": {},
            "missing_patterns": ["No data"]
        }

    columns = list(data[0].keys()) if data else []
    column_completeness = {}

    for col in columns:
        values = [row.get(col) for row in data]
        non_null_count = sum(1 for v in values if v is not None)
        completeness = (non_null_count / len(values) * 100) if values else 0
        column_completeness[col] = round(completeness, 1)

    overall_completeness = statistics.mean(column_completeness.values()) if column_completeness else 0

    # Identify missing patterns
    missing_patterns = []
    for col, completeness in column_completeness.items():
        if completeness < 50:
            missing_patterns.append(f"{col}: {100 - completeness:.1f}% missing")

    return {
        "overall_completeness": round(overall_completeness, 1),
        "column_completeness": column_completeness,
        "missing_patterns": missing_patterns
    }


# ============================================================================
# Data Consistency Checks
# ============================================================================

def check_consistency(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Check for data consistency issues.

    Returns:
        - issues: List[Dict] (consistency issues found)
        - consistent: bool (whether data passes all checks)
    """
    issues = []

    if not data:
        return {"issues": [], "consistent": True}

    # Check: All rows have same columns
    columns_set = [set(row.keys()) for row in data]
    if len(set(frozenset(cs) for cs in columns_set)) > 1:
        issues.append({
            "type": "schema_mismatch",
            "severity": "high",
            "description": "Rows have different column sets"
        })

    # Check: Data type consistency within columns
    columns = list(data[0].keys()) if data else []
    for col in columns:
        types = set()
        for row in data:
            val = row.get(col)
            if val is not None:
                types.add(type(val).__name__)

        if len(types) > 1:
            issues.append({
                "type": "type_inconsistency",
                "severity": "medium",
                "description": f"Column '{col}' has mixed types: {', '.join(types)}"
            })

    return {
        "issues": issues,
        "consistent": len(issues) == 0
    }
