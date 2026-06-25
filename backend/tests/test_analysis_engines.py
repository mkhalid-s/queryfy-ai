"""
Comprehensive unit tests for the analysis layer.

Covers:
- statistics.py: compute_statistics, analyze_distribution, percentiles, skewness, concentration, Gini
- insight_detector.py: detect_insights (concentration, trend, anomaly, comparison)
- data_quality.py: assess_data_quality, analyze_completeness, check_consistency
- chart_intelligence.py: recommend_chart, prepare_chart_data, classify, outliers, aggregation
- comparisons.py: compare_periods, calculate_growth_rates, SQL date shifting
- query_tools.py: sanitize_value, detect_data_characteristics, extract_json_from_llm_response
- analysis_tools.py: handler wrappers, _generate_followups
- validator.py: validate_insights_accuracy, validate_chart_spec
"""

import json
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from app.services.analysis_engines.statistics import (
    _calculate_concentration,
    _calculate_gini,
    _calculate_skewness,
    _compute_column_statistics,
    _get_numeric_columns,
    _is_numeric,
    _percentile,
    analyze_distribution,
    compute_statistics,
)
from app.services.analysis_engines.insight_detector import (
    _detect_anomalies,
    _detect_comparisons,
    _detect_concentration,
    _detect_trends,
    _get_categorical_columns,
    _get_date_columns,
    _get_row_identifier,
    _linear_regression,
    _looks_like_date,
    detect_insights,
)
from app.services.analysis_engines.data_quality import (
    _count_duplicates,
    _infer_data_type,
    analyze_completeness,
    assess_data_quality,
    check_consistency,
)
from app.services.analysis_engines.data_quality import (
    _looks_like_date as dq_looks_like_date,
)
from app.services.analysis_engines.chart_intelligence import (
    _aggregate_bucket,
    _aggregate_data,
    _analyze_data_characteristics,
    _classify_column,
    _handle_high_cardinality,
    _handle_outliers,
    _sort_data_for_chart,
    prepare_chart_data,
    recommend_chart,
)
from app.services.analysis_engines.comparisons import (
    _assess_significance,
    _interpret_change,
    _looks_like_date_string,
    _modify_sql_for_previous_period,
    _parse_date_flexible,
    _perform_temporal_comparison,
    calculate_growth_rates,
    compare_periods,
)
from app.services.analysis_engines.validator import (
    log_analysis_tool_output,
    validate_chart_spec,
    validate_insights_accuracy,
)
from app.services.tools.query_tools import (
    detect_data_characteristics,
    extract_json_from_llm_response,
    sanitize_value,
)
from app.services.tools.analysis_tools import (
    _generate_followups,
)

# ============================================================================
# Reusable test datasets
# ============================================================================

SALES_DATA = [
    {"product": "Widget A", "revenue": 50000, "units": 500, "date": "2024-01-01"},
    {"product": "Widget B", "revenue": 30000, "units": 300, "date": "2024-02-01"},
    {"product": "Widget C", "revenue": 10000, "units": 100, "date": "2024-03-01"},
    {"product": "Widget D", "revenue": 5000, "units": 50, "date": "2024-04-01"},
    {"product": "Widget E", "revenue": 3000, "units": 30, "date": "2024-05-01"},
    {"product": "Widget F", "revenue": 2000, "units": 20, "date": "2024-06-01"},
]

TIME_SERIES_DATA = [
    {"month": "2024-01-01", "revenue": 100, "customers": 10},
    {"month": "2024-02-01", "revenue": 120, "customers": 12},
    {"month": "2024-03-01", "revenue": 150, "customers": 15},
    {"month": "2024-04-01", "revenue": 180, "customers": 18},
    {"month": "2024-05-01", "revenue": 200, "customers": 20},
    {"month": "2024-06-01", "revenue": 250, "customers": 25},
]

CATEGORICAL_DATA = [
    {"region": "North", "category": "A", "sales": 100},
    {"region": "North", "category": "A", "sales": 120},
    {"region": "South", "category": "B", "sales": 50},
    {"region": "South", "category": "B", "sales": 60},
    {"region": "East", "category": "A", "sales": 200},
    {"region": "East", "category": "A", "sales": 220},
    {"region": "West", "category": "B", "sales": 30},
    {"region": "West", "category": "B", "sales": 35},
]

QUALITY_DATA_WITH_NULLS = [
    {"id": 1, "name": "Alice", "score": 90, "email": "alice@test.com"},
    {"id": 2, "name": None, "score": 85, "email": None},
    {"id": 3, "name": "Charlie", "score": None, "email": "charlie@test.com"},
    {"id": 4, "name": None, "score": None, "email": None},
    {"id": 5, "name": "Eve", "score": 95, "email": "eve@test.com"},
    {"id": 6, "name": None, "score": 70, "email": None},
]


# ############################################################################
# statistics.py
# ############################################################################

class TestComputeStatistics:
    def test_empty_data(self):
        assert compute_statistics([]) == {}

    def test_auto_detect_numeric_columns(self):
        data = [{"name": "A", "value": 10}, {"name": "B", "value": 20}]
        result = compute_statistics(data)
        assert "value" in result
        assert "name" not in result

    def test_explicit_columns(self):
        data = [{"a": 1, "b": 2, "c": 3}, {"a": 4, "b": 5, "c": 6}]
        result = compute_statistics(data, columns=["a", "c"])
        assert "a" in result
        assert "c" in result
        assert "b" not in result

    def test_basic_stats(self):
        data = [{"val": v} for v in [10, 20, 30, 40, 50]]
        result = compute_statistics(data)
        stats = result["val"]
        assert stats["count"] == 5
        assert stats["mean"] == 30.0
        assert stats["median"] == 30.0
        assert stats["min"] == 10.0
        assert stats["max"] == 50.0
        assert stats["range"] == 40.0

    def test_single_value(self):
        data = [{"val": 42}]
        result = compute_statistics(data)
        stats = result["val"]
        assert stats["count"] == 1
        assert stats["mean"] == 42.0
        assert stats["std_dev"] == 0
        assert stats["variance"] == 0

    def test_percentiles_present(self):
        data = [{"val": v} for v in range(1, 101)]
        result = compute_statistics(data)
        p = result["val"]["percentiles"]
        assert "p10" in p
        assert "p25" in p
        assert "p50" in p
        assert "p75" in p
        assert "p90" in p
        assert "p95" in p
        assert "p99" in p

    def test_concentration_present(self):
        data = [{"val": v} for v in [100, 50, 25, 10, 5, 3, 2, 1, 1, 1]]
        result = compute_statistics(data)
        conc = result["val"]["concentration"]
        assert "gini" in conc
        assert "hhi" in conc
        assert "top_10_pct" in conc
        assert "top_20_pct" in conc
        assert "top_50_pct" in conc

    def test_skips_non_numeric_values(self):
        data = [{"val": 10}, {"val": "not a number"}, {"val": 30}]
        result = compute_statistics(data, columns=["val"])
        stats = result["val"]
        assert stats["count"] == 2

    def test_skips_boolean_values(self):
        data = [{"flag": True, "num": 10}, {"flag": False, "num": 20}]
        result = compute_statistics(data)
        assert "flag" not in result
        assert "num" in result

    def test_column_with_no_numeric_values_skipped(self):
        data = [{"name": "A"}, {"name": "B"}]
        result = compute_statistics(data, columns=["name"])
        assert result == {}


class TestPercentile:
    def test_empty_list(self):
        assert _percentile([], 50) == 0.0

    def test_single_element(self):
        assert _percentile([42.0], 50) == 42.0

    def test_median(self):
        assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0

    def test_q1(self):
        result = _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 25)
        assert result == 2.0

    def test_q3(self):
        result = _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 75)
        assert result == 4.0

    def test_p100(self):
        result = _percentile([1.0, 2.0, 3.0], 100)
        assert result == 3.0

    def test_p0(self):
        result = _percentile([1.0, 2.0, 3.0], 0)
        assert result == 1.0


class TestSkewness:
    def test_zero_std_dev(self):
        assert _calculate_skewness([5.0, 5.0, 5.0], 5.0, 0.0) == 0.0

    def test_empty_values(self):
        assert _calculate_skewness([], 0.0, 1.0) == 0.0

    def test_symmetric_distribution(self):
        values = [-2.0, -1.0, 0.0, 1.0, 2.0]
        import statistics
        mean = statistics.mean(values)
        std = statistics.stdev(values)
        skew = _calculate_skewness(values, mean, std)
        assert abs(skew) < 0.01

    def test_right_skewed(self):
        values = [1.0, 1.0, 1.0, 1.0, 1.0, 100.0]
        import statistics
        mean = statistics.mean(values)
        std = statistics.stdev(values)
        skew = _calculate_skewness(values, mean, std)
        assert skew > 0


class TestConcentration:
    def test_empty(self):
        result = _calculate_concentration([])
        assert result["gini"] == 0
        assert result["hhi"] == 0

    def test_all_zeros(self):
        result = _calculate_concentration([0.0, 0.0, 0.0])
        assert result["gini"] == 0

    def test_high_concentration(self):
        result = _calculate_concentration([1.0, 1.0, 1.0, 1.0, 100.0])
        assert result["top_10_pct"] > 50

    def test_equal_distribution(self):
        result = _calculate_concentration([10.0, 10.0, 10.0, 10.0, 10.0])
        assert result["gini"] < 0.2


class TestGini:
    def test_empty(self):
        assert _calculate_gini([]) == 0.0

    def test_all_zeros(self):
        assert _calculate_gini([0.0, 0.0, 0.0]) == 0.0

    def test_equal_values(self):
        gini = _calculate_gini([10.0, 10.0, 10.0, 10.0])
        assert gini < 0.01

    def test_unequal_values(self):
        gini = _calculate_gini([0.0, 0.0, 0.0, 100.0])
        assert gini > 0.5


class TestGetNumericColumns:
    def test_empty(self):
        assert _get_numeric_columns([]) == []

    def test_mixed_types(self):
        data = [{"name": "A", "count": 5, "price": 9.99, "active": True}]
        cols = _get_numeric_columns(data)
        assert "count" in cols
        assert "price" in cols
        assert "name" not in cols
        assert "active" not in cols


class TestIsNumeric:
    def test_int(self):
        assert _is_numeric(42) is True

    def test_float(self):
        assert _is_numeric(3.14) is True

    def test_bool(self):
        assert _is_numeric(True) is False
        assert _is_numeric(False) is False

    def test_string(self):
        assert _is_numeric("123") is False

    def test_none(self):
        assert _is_numeric(None) is False


class TestAnalyzeDistribution:
    def test_too_few_values(self):
        result = analyze_distribution([1.0, 2.0])
        assert result["distribution_type"] == "unknown"
        assert result["normality_score"] == 0
        assert result["outlier_count"] == 0

    def test_empty(self):
        result = analyze_distribution([])
        assert result["distribution_type"] == "unknown"

    def test_normal_distribution(self):
        values = [10.0, 11.0, 12.0, 11.5, 10.5, 11.2, 10.8, 11.0, 10.7, 11.3]
        result = analyze_distribution(values)
        assert result["distribution_type"] == "normal"
        assert result["normality_score"] > 0.5

    def test_right_skewed_distribution(self):
        values = [1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 10.0, 100.0]
        result = analyze_distribution(values)
        assert result["distribution_type"] == "skewed_right"

    def test_left_skewed_distribution(self):
        values = [100.0, 99.0, 98.0, 97.0, 90.0, 50.0, 10.0, 1.0, 1.0, 1.0]
        result = analyze_distribution(values)
        assert result["skewness"] < 0

    def test_outlier_count(self):
        values = [10.0] * 50 + [1000.0]
        result = analyze_distribution(values)
        assert result["outlier_count"] >= 1

    def test_zero_std_dev(self):
        values = [5.0, 5.0, 5.0, 5.0, 5.0]
        result = analyze_distribution(values)
        assert result["outlier_count"] == 0


class TestComputeColumnStatistics:
    def test_empty(self):
        assert _compute_column_statistics([]) == {}

    def test_cv_zero_mean(self):
        values = [-1.0, 0.0, 1.0]
        result = _compute_column_statistics(values)
        assert result["cv"] == 0


# ############################################################################
# insight_detector.py
# ############################################################################

class TestDetectInsights:
    def test_empty_data(self):
        assert detect_insights([]) == []

    def test_all_analysis_types_default(self):
        insights = detect_insights(SALES_DATA)
        assert isinstance(insights, list)

    def test_specific_analysis_types(self):
        insights = detect_insights(SALES_DATA, analysis_types=["concentration"])
        for i in insights:
            assert i["type"] == "concentration"

    def test_all_keyword(self):
        insights = detect_insights(SALES_DATA, analysis_types=["all"])
        assert isinstance(insights, list)

    def test_sorted_by_severity(self):
        insights = detect_insights(SALES_DATA)
        severity_order = {"high": 0, "medium": 1, "low": 2}
        for i in range(len(insights) - 1):
            a = severity_order.get(insights[i]["severity"], 3)
            b = severity_order.get(insights[i + 1]["severity"], 3)
            assert a <= b


class TestDetectConcentration:
    def test_too_few_rows(self):
        data = [{"val": 10}, {"val": 20}]
        assert _detect_concentration(data) == []

    def test_high_concentration(self):
        data = [
            {"item": f"item{i}", "revenue": 1000 if i < 3 else 10}
            for i in range(10)
        ]
        insights = _detect_concentration(data)
        assert len(insights) > 0
        assert any(i["severity"] == "high" for i in insights)

    def test_no_concentration_equal_values(self):
        data = [{"item": f"item{i}", "value": 10} for i in range(10)]
        insights = _detect_concentration(data)
        assert len(insights) == 0

    def test_zero_total(self):
        data = [{"item": f"item{i}", "value": 0} for i in range(10)]
        insights = _detect_concentration(data)
        assert len(insights) == 0


class TestDetectTrends:
    def test_too_few_rows(self):
        data = [{"date": "2024-01-01", "val": 10}]
        assert _detect_trends(data) == []

    def test_strong_upward_trend(self):
        insights = _detect_trends(TIME_SERIES_DATA)
        assert len(insights) > 0
        has_trend = any(i["type"] == "trend" for i in insights)
        assert has_trend

    def test_no_date_column(self):
        data = [{"category": "A", "val": i} for i in range(5)]
        assert _detect_trends(data) == []

    def test_no_numeric_column(self):
        data = [{"date": f"2024-0{i}-01", "name": f"A{i}"} for i in range(1, 6)]
        assert _detect_trends(data) == []

    def test_weak_trend_skipped(self):
        import random
        random.seed(42)
        data = [
            {"month": f"2024-{i:02d}-01", "val": random.randint(1, 100)}
            for i in range(1, 13)
        ]
        insights = _detect_trends(data)
        for i in insights:
            if i["type"] == "trend":
                assert i["metrics"]["r_squared"] >= 0.5


class TestDetectAnomalies:
    def test_too_few_rows(self):
        data = [{"val": 10}]
        assert _detect_anomalies(data) == []

    def test_detects_outlier(self):
        data = [{"name": f"item{i}", "val": 10} for i in range(20)]
        data.append({"name": "outlier", "val": 10000})
        insights = _detect_anomalies(data)
        assert len(insights) > 0
        assert insights[0]["type"] == "anomaly"
        assert insights[0]["metrics"]["outlier_count"] >= 1

    def test_no_outliers_in_uniform_data(self):
        data = [{"val": 10} for _ in range(20)]
        insights = _detect_anomalies(data)
        assert len(insights) == 0


class TestDetectComparisons:
    def test_too_few_rows(self):
        data = [{"cat": "A", "val": 10}]
        assert _detect_comparisons(data) == []

    def test_significant_differences(self):
        data = [
            {"region": "North", "region2": "North", "sales": 100},
            {"region": "North", "region2": "North", "sales": 110},
            {"region": "South", "region2": "South", "sales": 10},
            {"region": "South", "region2": "South", "sales": 15},
        ]
        insights = _detect_comparisons(data)
        assert isinstance(insights, list)

    def test_no_categorical_columns(self):
        data = [{"a": i, "b": i * 2} for i in range(10)]
        insights = _detect_comparisons(data)
        assert insights == []


class TestInsightHelpers:
    def test_get_date_columns(self):
        data = [{"created_at": "2024-01-01", "name": "A", "timestamp": "x"}]
        cols = _get_date_columns(data)
        assert "created_at" in cols
        assert "timestamp" in cols

    def test_get_date_columns_with_datetime(self):
        data = [{"dt": datetime(2024, 1, 1), "name": "A"}]
        cols = _get_date_columns(data)
        assert "dt" in cols

    def test_get_date_columns_empty(self):
        assert _get_date_columns([]) == []

    def test_get_categorical_columns_empty(self):
        assert _get_categorical_columns([]) == []

    def test_looks_like_date(self):
        assert _looks_like_date("created_at") is True
        assert _looks_like_date("date") is True
        assert _looks_like_date("timestamp") is True
        assert _looks_like_date("month") is True
        assert _looks_like_date("name") is False

    def test_get_row_identifier_with_name(self):
        row = {"name": "Alice", "value": 100}
        ident = _get_row_identifier(row, [row])
        assert "name=Alice" in ident

    def test_get_row_identifier_with_id(self):
        row = {"product_id": 42, "value": 100}
        ident = _get_row_identifier(row, [row])
        assert "product_id=42" in ident

    def test_get_row_identifier_fallback(self):
        row = {"xyz": "hello", "abc": 123}
        ident = _get_row_identifier(row, [row])
        assert "=" in ident

    def test_get_row_identifier_empty_row(self):
        ident = _get_row_identifier({}, [])
        assert ident == "unknown"


class TestLinearRegression:
    def test_too_few_points(self):
        assert _linear_regression([1.0], [1.0]) == (0, 0, 0)

    def test_perfect_positive_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        slope, intercept, r_sq = _linear_regression(x, y)
        assert abs(slope - 2.0) < 0.01
        assert abs(intercept) < 0.01
        assert abs(r_sq - 1.0) < 0.01

    def test_flat_line(self):
        x = [1.0, 2.0, 3.0]
        y = [5.0, 5.0, 5.0]
        slope, intercept, r_sq = _linear_regression(x, y)
        assert slope == 0
        assert intercept == 5.0

    def test_constant_x(self):
        x = [3.0, 3.0, 3.0]
        y = [1.0, 2.0, 3.0]
        slope, intercept, r_sq = _linear_regression(x, y)
        assert slope == 0


# ############################################################################
# data_quality.py
# ############################################################################

class TestAssessDataQuality:
    def test_empty_data(self):
        result = assess_data_quality([])
        assert result["overall_score"] == 0
        assert result["null_pct"] == 100
        assert len(result["issues"]) > 0

    def test_perfect_data(self):
        data = [
            {"id": 1, "name": "A", "value": 10},
            {"id": 2, "name": "B", "value": 20},
            {"id": 3, "name": "C", "value": 30},
        ]
        result = assess_data_quality(data)
        assert result["overall_score"] > 80
        assert result["completeness"] == 100.0
        assert result["null_pct"] == 0.0
        assert result["duplicate_count"] == 0

    def test_data_with_nulls(self):
        result = assess_data_quality(QUALITY_DATA_WITH_NULLS)
        assert result["completeness"] < 100
        assert result["null_pct"] > 0
        assert result["row_count"] == 6

    def test_data_with_duplicates(self):
        data = [
            {"id": 1, "val": 10},
            {"id": 1, "val": 10},
            {"id": 2, "val": 20},
        ]
        result = assess_data_quality(data)
        assert result["duplicate_count"] == 1

    def test_column_quality_metrics(self):
        data = [
            {"id": 1, "val": 10},
            {"id": 2, "val": 20},
        ]
        result = assess_data_quality(data)
        assert "id" in result["column_quality"]
        assert "val" in result["column_quality"]
        assert "null_count" in result["column_quality"]["id"]
        assert "data_type" in result["column_quality"]["id"]

    def test_high_null_column_issue(self):
        data = [
            {"id": 1, "opt": None},
            {"id": 2, "opt": None},
            {"id": 3, "opt": None},
            {"id": 4, "opt": "value"},
        ]
        result = assess_data_quality(data)
        high_issues = [
            i for i in result["issues"]
            if "opt" in i.get("description", "") and i.get("severity") == "high"
        ]
        assert len(high_issues) > 0

    def test_constant_column_issue(self):
        data = [
            {"id": 1, "status": "active"},
            {"id": 2, "status": "active"},
            {"id": 3, "status": "active"},
        ]
        result = assess_data_quality(data)
        low_issues = [i for i in result["issues"] if "constant" in i.get("description", "").lower()]
        assert len(low_issues) > 0

    def test_all_zeros_issue(self):
        data = [{"id": i, "value": 0} for i in range(10)]
        result = assess_data_quality(data)
        zero_issues = [i for i in result["issues"] if "zero" in i.get("description", "").lower()]
        assert len(zero_issues) > 0

    def test_outlier_detection_in_quality(self):
        data = [{"val": 10} for _ in range(20)]
        data.append({"val": 10000})
        result = assess_data_quality(data)
        assert result["outlier_count"] >= 1


class TestCountDuplicates:
    def test_no_duplicates(self):
        data = [{"a": 1}, {"a": 2}, {"a": 3}]
        assert _count_duplicates(data) == 0

    def test_one_duplicate(self):
        data = [{"a": 1}, {"a": 1}, {"a": 2}]
        assert _count_duplicates(data) == 1

    def test_multiple_duplicates(self):
        data = [{"a": 1}, {"a": 1}, {"a": 1}]
        assert _count_duplicates(data) == 2

    def test_unhashable_values(self):
        data = [{"a": [1, 2]}, {"a": [1, 2]}]
        result = _count_duplicates(data)
        assert isinstance(result, int)


class TestInferDataType:
    def test_null(self):
        assert _infer_data_type([None, None]) == "null"

    def test_boolean(self):
        assert _infer_data_type([True, False, None]) == "boolean"

    def test_integer(self):
        assert _infer_data_type([1, 2, None]) == "integer"

    def test_float(self):
        assert _infer_data_type([1.5, 2.5, None]) == "float"

    def test_date(self):
        assert _infer_data_type([datetime(2024, 1, 1), None]) == "date"

    def test_date_obj(self):
        assert _infer_data_type([date(2024, 1, 1), None]) == "date"

    def test_string(self):
        assert _infer_data_type(["hello", None]) == "string"

    def test_date_string(self):
        assert _infer_data_type(["2024-01-15", None]) == "date_string"

    def test_complex(self):
        assert _infer_data_type([{"nested": True}, None]) == "complex"

    def test_list_type(self):
        assert _infer_data_type([[1, 2], None]) == "complex"

    def test_unknown_type(self):
        assert _infer_data_type([b"bytes", None]) == "unknown"


class TestDqLooksLikeDate:
    def test_yyyy_mm_dd(self):
        assert dq_looks_like_date("2024-01-15") is True

    def test_mm_dd_yyyy(self):
        assert dq_looks_like_date("01/15/2024") is True

    def test_yyyy_slash(self):
        assert dq_looks_like_date("2024/01/15") is True

    def test_not_a_date(self):
        assert dq_looks_like_date("hello world") is False


class TestAnalyzeCompleteness:
    def test_empty_data(self):
        result = analyze_completeness([])
        assert result["overall_completeness"] == 0
        assert result["missing_patterns"] == ["No data"]

    def test_full_completeness(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        result = analyze_completeness(data)
        assert result["overall_completeness"] == 100.0
        assert result["column_completeness"]["a"] == 100.0
        assert len(result["missing_patterns"]) == 0

    def test_partial_completeness(self):
        data = [
            {"a": 1, "b": None},
            {"a": None, "b": None},
            {"a": 3, "b": None},
        ]
        result = analyze_completeness(data)
        assert result["column_completeness"]["b"] == 0.0
        assert len(result["missing_patterns"]) > 0


class TestCheckConsistency:
    def test_empty_data(self):
        result = check_consistency([])
        assert result["consistent"] is True
        assert result["issues"] == []

    def test_consistent_data(self):
        data = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        result = check_consistency(data)
        assert result["consistent"] is True

    def test_schema_mismatch(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "c": 4}]
        result = check_consistency(data)
        assert result["consistent"] is False
        schema_issues = [i for i in result["issues"] if i["type"] == "schema_mismatch"]
        assert len(schema_issues) > 0

    def test_type_inconsistency(self):
        data = [{"a": 1, "b": "hello"}, {"a": "two", "b": "world"}]
        result = check_consistency(data)
        type_issues = [i for i in result["issues"] if i["type"] == "type_inconsistency"]
        assert len(type_issues) > 0


# ############################################################################
# chart_intelligence.py
# ############################################################################

class TestRecommendChart:
    def test_empty_data(self):
        result = recommend_chart([])
        assert result["recommended_chart"] is None
        assert "No data" in result["rationale"]

    def test_time_series_recommends_line(self):
        data = [
            {"date": datetime(2024, 1, 1), "value": 100},
            {"date": datetime(2024, 2, 1), "value": 120},
            {"date": datetime(2024, 3, 1), "value": 140},
        ]
        result = recommend_chart(data)
        assert result["recommended_chart"] == "line"

    def test_single_value_recommends_gauge(self):
        data = [{"value": 42}]
        result = recommend_chart(data)
        assert result["recommended_chart"] == "gauge"

    def test_few_categories_recommends_pie(self):
        data = [
            {"category": "A", "value": 10},
            {"category": "A", "value": 20},
            {"category": "B", "value": 30},
            {"category": "B", "value": 20},
            {"category": "C", "value": 10},
            {"category": "C", "value": 15},
            {"category": "C", "value": 10},
        ]
        result = recommend_chart(data)
        assert result["recommended_chart"] == "pie"

    def test_many_categories_recommends_horizontal_bar(self):
        names = [f"item_{i}" for i in range(25)]
        data = [{"name": names[i % 25], "count": (i + 1) * 10} for i in range(60)]
        result = recommend_chart(data)
        assert result["recommended_chart"] == "horizontal_bar"

    def test_two_numeric_cols_recommends_scatter(self):
        data = [{"x": i, "y": i ** 2} for i in range(20)]
        result = recommend_chart(data)
        assert result["recommended_chart"] == "scatter"

    def test_large_dataset_warning(self):
        data = [{"category": f"c{i}", "value": i} for i in range(150)]
        result = recommend_chart(data)
        assert any("Large dataset" in w for w in result["warnings"])

    def test_nulls_warning(self):
        data = [
            {"category": "A", "value": 10},
            {"category": "B", "value": None},
            {"category": "C", "value": 30},
        ]
        result = recommend_chart(data)
        assert any("null" in w.lower() for w in result["warnings"])


class TestPrepareChartData:
    def test_empty_data(self):
        result = prepare_chart_data([], "bar")
        assert result["transformed_data"] == []
        assert result["transformations_applied"] == []

    def test_small_dataset_no_aggregation(self):
        data = [{"cat": "A", "val": 10}, {"cat": "B", "val": 20}]
        result = prepare_chart_data(data, "bar", max_points=50)
        assert len(result["transformed_data"]) == 2

    def test_aggregation_for_large_dataset(self):
        data = [{"val": i} for i in range(200)]
        result = prepare_chart_data(data, "line", max_points=50)
        assert len(result["transformed_data"]) <= 55
        assert any("Aggregated" in t for t in result["transformations_applied"])

    def test_high_cardinality_grouping(self):
        data = [{"name": f"item_{i}", "value": 100 - i} for i in range(30)]
        result = prepare_chart_data(data, "bar", max_points=100)
        has_other = any(
            row.get("name") == "Other"
            for row in result["transformed_data"]
        )
        assert has_other

    def test_sort_for_bar_chart(self):
        data = [
            {"name": "A", "value": 10},
            {"name": "B", "value": 30},
            {"name": "C", "value": 20},
        ]
        result = prepare_chart_data(data, "bar", max_points=50, handle_outliers=False)
        values = [row["value"] for row in result["transformed_data"]]
        assert values == sorted(values, reverse=True)

    def test_outlier_handling(self):
        data = [{"val": 10} for _ in range(20)]
        data.append({"val": 10000})
        result = prepare_chart_data(data, "line", max_points=100, handle_outliers=True)
        assert any("outlier" in t.lower() for t in result["transformations_applied"])

    def test_no_outlier_handling(self):
        data = [{"val": 10} for _ in range(20)]
        data.append({"val": 10000})
        result = prepare_chart_data(data, "line", max_points=100, handle_outliers=False)
        outlier_transformations = [t for t in result["transformations_applied"] if "outlier" in t.lower()]
        assert len(outlier_transformations) == 0


class TestClassifyColumn:
    def test_numeric(self):
        data = [{"val": 10}, {"val": 20}]
        assert _classify_column(data, "val") == "numeric"

    def test_date(self):
        data = [{"dt": datetime(2024, 1, 1)}, {"dt": datetime(2024, 2, 1)}]
        assert _classify_column(data, "dt") == "date"

    def test_categorical(self):
        data = [{"cat": "A"}, {"cat": "A"}, {"cat": "A"}, {"cat": "B"}, {"cat": "B"}, {"cat": "B"}]
        assert _classify_column(data, "cat") == "categorical"

    def test_text(self):
        data = [{"desc": f"unique_{i}"} for i in range(20)]
        assert _classify_column(data, "desc") == "text"

    def test_unknown(self):
        data = [{"val": None}, {"val": None}]
        assert _classify_column(data, "val") == "unknown"

    def test_boolean_not_numeric(self):
        data = [{"flag": True}, {"flag": False}]
        result = _classify_column(data, "flag")
        assert result != "numeric"


class TestHandleOutliers:
    def test_no_outliers(self):
        data = [{"val": 10} for _ in range(10)]
        result = _handle_outliers(data)
        assert result["outliers_capped"] == 0

    def test_caps_outliers(self):
        data = [{"val": 10} for _ in range(20)]
        data.append({"val": 10000})
        result = _handle_outliers(data)
        assert result["outliers_capped"] >= 1

    def test_few_values_no_capping(self):
        data = [{"val": 10}, {"val": 10000}]
        result = _handle_outliers(data)
        assert result["outliers_capped"] == 0


class TestAggregateData:
    def test_small_dataset(self):
        data = [{"val": i} for i in range(5)]
        result = _aggregate_data(data, target_points=10)
        assert result["method"] == "none"
        assert result["data"] == data

    def test_aggregation(self):
        data = [{"val": i, "name": f"r{i}"} for i in range(100)]
        result = _aggregate_data(data, target_points=10)
        assert len(result["data"]) < 100
        assert "bucket_average" in result["method"]


class TestAggregateBucket:
    def test_empty(self):
        assert _aggregate_bucket([]) == {}

    def test_numeric_aggregation(self):
        bucket = [{"val": 10, "name": "A"}, {"val": 20, "name": "B"}]
        result = _aggregate_bucket(bucket)
        assert result["val"] == 15.0
        assert result["name"] == "A"

    def test_all_null_column(self):
        bucket = [{"val": None}, {"val": None}]
        result = _aggregate_bucket(bucket)
        assert result["val"] is None


class TestHandleHighCardinality:
    def test_empty_data(self):
        result = _handle_high_cardinality([], max_categories=5)
        assert result["grouped"] is False

    def test_low_cardinality_no_grouping(self):
        data = [
            {"cat": "A", "val": 10},
            {"cat": "B", "val": 20},
        ]
        result = _handle_high_cardinality(data, max_categories=5)
        assert result["grouped"] is False

    def test_high_cardinality_groups_to_other(self):
        data = [{"name": f"item_{i}", "value": 100 - i} for i in range(30)]
        result = _handle_high_cardinality(data, max_categories=10)
        assert result["grouped"] is True
        assert result["categories_grouped"] == 20
        names = [row["name"] for row in result["data"]]
        assert "Other" in names

    def test_no_numeric_cols(self):
        data = [{"name": f"item_{i}", "desc": f"desc_{i}"} for i in range(30)]
        result = _handle_high_cardinality(data, max_categories=5)
        assert result["grouped"] is False


class TestSortDataForChart:
    def test_empty(self):
        result = _sort_data_for_chart([], "bar")
        assert result["sorted"] is False

    def test_bar_chart_sorted_descending(self):
        data = [
            {"name": "A", "val": 10},
            {"name": "B", "val": 30},
            {"name": "C", "val": 20},
        ]
        result = _sort_data_for_chart(data, "bar")
        assert result["sorted"] is True
        values = [r["val"] for r in result["data"]]
        assert values == [30, 20, 10]

    def test_line_chart_not_sorted(self):
        data = [
            {"name": "A", "val": 10},
            {"name": "B", "val": 30},
        ]
        result = _sort_data_for_chart(data, "line")
        assert result["sorted"] is False

    def test_no_numeric_cols(self):
        data = [{"name": "A"}, {"name": "B"}]
        result = _sort_data_for_chart(data, "bar")
        assert result["sorted"] is False


class TestAnalyzeDataCharacteristics:
    def test_empty(self):
        assert _analyze_data_characteristics([]) == {}

    def test_time_series(self):
        data = [
            {"date": datetime(2024, 1, 1), "value": 100},
            {"date": datetime(2024, 2, 1), "value": 200},
        ]
        result = _analyze_data_characteristics(data)
        assert result["is_time_series"] is True
        assert len(result["date_cols"]) > 0

    def test_categorical_data(self):
        data = [
            {"cat": "A", "val": 10},
            {"cat": "A", "val": 20},
            {"cat": "A", "val": 25},
            {"cat": "B", "val": 30},
            {"cat": "B", "val": 35},
            {"cat": "B", "val": 40},
        ]
        result = _analyze_data_characteristics(data)
        assert "cat" in result["categorical_cols"]
        assert "val" in result["numeric_cols"]

    def test_nulls_detection(self):
        data = [
            {"a": 1, "b": None},
            {"a": 2, "b": 3},
        ]
        result = _analyze_data_characteristics(data)
        assert result["has_nulls"] is True


# ############################################################################
# comparisons.py
# ############################################################################

class TestComparePeriods:
    def test_empty_data(self):
        result = compare_periods([], "MoM")
        assert result["comparisons"] == []
        assert result["needs_previous_fetch"] is False

    def test_segment_vs_avg(self):
        data = CATEGORICAL_DATA
        result = compare_periods(data, "segment_vs_avg")
        assert result["needs_previous_fetch"] is False

    def test_temporal_without_previous_data_with_sql(self):
        data = [{"month": "2024-01-01", "revenue": 100}]
        result = compare_periods(
            data,
            "MoM",
            previous_data=None,
            original_sql="SELECT * FROM sales WHERE date >= '2024-01-01'"
        )
        assert result["needs_previous_fetch"] is True
        assert result["modified_sql"] is not None

    def test_temporal_without_previous_data_without_sql(self):
        data = [{"month": "2024-01-01", "revenue": 100}]
        result = compare_periods(data, "MoM", previous_data=None, original_sql=None)
        assert result["needs_previous_fetch"] is True
        assert "error" in result

    def test_temporal_with_both_datasets(self):
        current = [{"revenue": 150}, {"revenue": 200}]
        previous = [{"revenue": 100}, {"revenue": 120}]
        result = compare_periods(current, "MoM", previous_data=previous)
        assert result["needs_previous_fetch"] is False
        assert len(result["comparisons"]) > 0

    def test_temporal_comparison_increase(self):
        current = [{"val": 200}]
        previous = [{"val": 100}]
        result = compare_periods(current, "YoY", previous_data=previous)
        comp = result["comparisons"][0]
        assert comp["direction"] == "increase"
        assert comp["change_pct"] == 100.0

    def test_temporal_comparison_decrease(self):
        current = [{"val": 50}]
        previous = [{"val": 100}]
        result = compare_periods(current, "YoY", previous_data=previous)
        comp = result["comparisons"][0]
        assert comp["direction"] == "decrease"

    def test_temporal_comparison_stable(self):
        current = [{"val": 100}]
        previous = [{"val": 100}]
        result = compare_periods(current, "MoM", previous_data=previous)
        comp = result["comparisons"][0]
        assert comp["direction"] == "stable"
        assert comp["change_pct"] == 0.0


class TestPerformTemporalComparison:
    def test_no_numeric_columns(self):
        current = [{"name": "A"}]
        previous = [{"name": "B"}]
        result = _perform_temporal_comparison(current, previous, "MoM")
        assert result == []

    def test_empty_values(self):
        current = [{"val": None}]
        previous = [{"val": None}]
        result = _perform_temporal_comparison(current, previous, "MoM")
        assert result == []

    def test_previous_zero(self):
        current = [{"val": 100}]
        previous = [{"val": 0}]
        result = _perform_temporal_comparison(current, previous, "MoM")
        assert len(result) > 0
        assert result[0]["change_pct"] == 0.0


class TestCompareSegments:
    def test_no_categorical_columns(self):
        from app.services.analysis_engines.comparisons import _compare_segments
        data = [{"val": i} for i in range(10)]
        result = _compare_segments(data)
        assert result["comparisons"] == []

    def test_segments_comparison(self):
        from app.services.analysis_engines.comparisons import _compare_segments
        data = [
            {"region": "North", "region2": "North", "sales": 1000},
            {"region": "North", "region2": "North", "sales": 1100},
            {"region": "South", "region2": "South", "sales": 100},
            {"region": "South", "region2": "South", "sales": 110},
        ]
        result = _compare_segments(data)
        assert isinstance(result["comparisons"], list)


class TestModifySqlForPreviousPeriod:
    def test_simple_date_shift(self):
        sql = "SELECT * FROM sales WHERE date >= '2024-06-01' AND date < '2024-07-01'"
        result = _modify_sql_for_previous_period(sql, "MoM")
        assert "2024-05" in result

    def test_no_dates_in_sql(self):
        sql = "SELECT * FROM sales WHERE id > 10"
        result = _modify_sql_for_previous_period(sql, "MoM")
        assert "No date literals" in result

    def test_yoy_shift(self):
        sql = "SELECT * FROM sales WHERE date = '2024-01-15'"
        result = _modify_sql_for_previous_period(sql, "YoY")
        assert "2023" in result

    def test_wow_shift(self):
        sql = "SELECT * FROM sales WHERE date = '2024-06-15'"
        result = _modify_sql_for_previous_period(sql, "WoW")
        assert "2024-06-08" in result

    def test_datetime_format_preserved(self):
        sql = "SELECT * FROM sales WHERE ts >= '2024-06-01 00:00:00'"
        result = _modify_sql_for_previous_period(sql, "MoM")
        assert "00:00:00" in result


class TestLooksLikeDateString:
    def test_iso_date(self):
        assert _looks_like_date_string("2024-01-15") is True

    def test_us_date(self):
        assert _looks_like_date_string("01/15/2024") is True

    def test_slash_date(self):
        assert _looks_like_date_string("2024/01/15") is True

    def test_iso_datetime(self):
        assert _looks_like_date_string("2024-01-15T10:30:00") is True

    def test_datetime_space(self):
        assert _looks_like_date_string("2024-01-15 10:30") is True

    def test_not_a_date(self):
        assert _looks_like_date_string("hello") is False

    def test_number_string(self):
        assert _looks_like_date_string("12345") is False


class TestParseDateFlexible:
    def test_iso_date(self):
        result = _parse_date_flexible("2024-06-15")
        assert result == datetime(2024, 6, 15)

    def test_slash_date(self):
        result = _parse_date_flexible("2024/06/15")
        assert result == datetime(2024, 6, 15)

    def test_us_date(self):
        result = _parse_date_flexible("06/15/2024")
        assert result == datetime(2024, 6, 15)

    def test_iso_datetime(self):
        result = _parse_date_flexible("2024-06-15 10:30:00")
        assert result == datetime(2024, 6, 15, 10, 30, 0)

    def test_iso_datetime_t(self):
        result = _parse_date_flexible("2024-06-15T10:30:00")
        assert result == datetime(2024, 6, 15, 10, 30, 0)

    def test_invalid(self):
        assert _parse_date_flexible("not-a-date") is None


class TestInterpretChange:
    def test_stable(self):
        result = _interpret_change(2.0, "MoM")
        assert "stable" in result.lower()

    def test_moderate_growth(self):
        result = _interpret_change(10.0, "MoM")
        assert "growth" in result.lower()

    def test_strong_growth(self):
        result = _interpret_change(25.0, "YoY")
        assert "strong" in result.lower()

    def test_exceptional_growth(self):
        result = _interpret_change(50.0, "MoM")
        assert "exceptional" in result.lower()

    def test_slight_decline(self):
        result = _interpret_change(-10.0, "MoM")
        assert "decline" in result.lower()

    def test_concerning_decline(self):
        result = _interpret_change(-25.0, "QoQ")
        assert "concerning" in result.lower()

    def test_significant_decline(self):
        result = _interpret_change(-50.0, "MoM")
        assert "significant" in result.lower()


class TestAssessSignificance:
    def test_not_significant(self):
        assert _assess_significance(2.0) == "not_significant"

    def test_moderate(self):
        assert _assess_significance(10.0) == "moderate"

    def test_significant(self):
        assert _assess_significance(20.0) == "significant"

    def test_highly_significant(self):
        assert _assess_significance(50.0) == "highly_significant"

    def test_negative_highly_significant(self):
        assert _assess_significance(-50.0) == "highly_significant"


class TestCalculateGrowthRates:
    def test_empty_data(self):
        result = calculate_growth_rates([], "value", "date")
        assert result["cagr"] == 0
        assert result["period_growth_rates"] == []
        assert result["growth_acceleration"] == "unknown"

    def test_single_point(self):
        data = [{"date": "2024-01-01", "value": 100}]
        result = calculate_growth_rates(data, "value", "date")
        assert result["cagr"] == 0

    def test_positive_growth(self):
        data = [
            {"date": "2024-01-01", "value": 100},
            {"date": "2024-02-01", "value": 120},
            {"date": "2024-03-01", "value": 150},
            {"date": "2024-04-01", "value": 200},
        ]
        result = calculate_growth_rates(data, "value", "date")
        assert result["cagr"] > 0
        assert len(result["period_growth_rates"]) == 3
        assert result["average_growth_rate"] > 0

    def test_growth_acceleration(self):
        data = [
            {"date": "2024-01-01", "value": 100},
            {"date": "2024-02-01", "value": 110},
            {"date": "2024-03-01", "value": 120},
            {"date": "2024-04-01", "value": 150},
            {"date": "2024-05-01", "value": 200},
        ]
        result = calculate_growth_rates(data, "value", "date")
        assert result["growth_acceleration"] == "accelerating"

    def test_growth_deceleration(self):
        data = [
            {"date": "2024-01-01", "value": 100},
            {"date": "2024-02-01", "value": 200},
            {"date": "2024-03-01", "value": 280},
            {"date": "2024-04-01", "value": 300},
            {"date": "2024-05-01", "value": 310},
        ]
        result = calculate_growth_rates(data, "value", "date")
        assert result["growth_acceleration"] == "decelerating"

    def test_zero_start_value(self):
        data = [
            {"date": "2024-01-01", "value": 0},
            {"date": "2024-02-01", "value": 100},
        ]
        result = calculate_growth_rates(data, "value", "date")
        assert result["cagr"] == 0

    def test_non_numeric_filtered(self):
        data = [
            {"date": "2024-01-01", "value": "not_a_number"},
            {"date": "2024-02-01", "value": 100},
        ]
        result = calculate_growth_rates(data, "value", "date")
        assert result["cagr"] == 0


# ############################################################################
# query_tools.py (pure functions)
# ############################################################################

class TestSanitizeValue:
    def test_none(self):
        assert sanitize_value(None) is None

    def test_int(self):
        assert sanitize_value(42) == 42

    def test_float(self):
        assert sanitize_value(3.14) == 3.14

    def test_bool(self):
        assert sanitize_value(True) is True

    def test_string(self):
        assert sanitize_value("hello") == "hello"

    def test_control_characters_stripped(self):
        result = sanitize_value("hello\x00world")
        assert "\x00" not in result

    def test_long_string_truncated(self):
        long_str = "a" * 200
        result = sanitize_value(long_str)
        assert len(result) <= 104
        assert result.endswith("...")

    def test_object_converted_to_string(self):
        result = sanitize_value({"key": "value"})
        assert isinstance(result, str)

    def test_datetime_converted(self):
        dt = datetime(2024, 1, 15, 10, 30)
        result = sanitize_value(dt)
        assert isinstance(result, str)


class TestDetectDataCharacteristics:
    def test_basic_data(self):
        columns = ["name", "value"]
        rows = [{"name": "A", "value": 10}, {"name": "B", "value": 20}]
        result = detect_data_characteristics(columns, rows)
        assert "has_time_series" in result
        assert "has_id_sequence" in result
        assert "has_outliers_risk" in result
        assert "sampling_appropriate" in result

    def test_time_series_detected(self):
        columns = ["created_date", "amount"]
        rows = [
            {"created_date": "2024-01-01", "amount": 100},
            {"created_date": "2024-02-01", "amount": 200},
        ]
        result = detect_data_characteristics(columns, rows)
        assert result["has_time_series"] is True
        assert result["sampling_appropriate"] is False

    def test_sequential_id_detected(self):
        columns = ["id", "value"]
        rows = [{"id": i, "value": i * 10} for i in range(1, 51)]
        result = detect_data_characteristics(columns, rows)
        assert result["has_id_sequence"] is True
        assert result["sampling_appropriate"] is False

    def test_high_variance_detected(self):
        columns = ["amount"]
        rows = [{"amount": 1} for _ in range(50)]
        rows.extend([{"amount": 1000000} for _ in range(5)])
        result = detect_data_characteristics(columns, rows)
        assert result["has_outliers_risk"] is True

    def test_no_issues(self):
        columns = ["category", "value"]
        rows = [{"category": f"cat{i}", "value": 10 + i} for i in range(20)]
        result = detect_data_characteristics(columns, rows)
        assert result["sampling_appropriate"] is True

    def test_empty_rows(self):
        columns = ["id"]
        result = detect_data_characteristics(columns, [])
        assert result["sampling_appropriate"] is True

    def test_timestamp_column(self):
        columns = ["timestamp", "val"]
        rows = [{"timestamp": "2024-01-01", "val": 1}]
        result = detect_data_characteristics(columns, rows)
        assert result["has_time_series"] is True


class TestExtractJsonFromLlmResponse:
    def test_empty_input(self):
        assert extract_json_from_llm_response("") == []
        assert extract_json_from_llm_response("   ") == []
        assert extract_json_from_llm_response(None) == []

    def test_clean_json_array(self):
        text = '[{"type": "insight", "severity": "high"}]'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1
        assert result[0]["type"] == "insight"

    def test_markdown_code_fence(self):
        text = '```json\n[{"type": "insight"}]\n```'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1

    def test_text_around_json(self):
        text = 'Here are insights:\n[{"type": "insight"}]\nLet me know!'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1

    def test_single_object_wrapped(self):
        text = '{"type": "insight", "severity": "low"}'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1

    def test_trailing_comma_fix(self):
        text = '[{"type": "insight",}]'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1

    def test_invalid_json_returns_empty(self):
        text = 'This is not JSON at all'
        result = extract_json_from_llm_response(text)
        assert result == []

    def test_code_fence_with_json_keyword(self):
        text = '```JSON\n[{"a": 1}]\n```'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1

    def test_multiple_code_blocks_uses_first(self):
        text = '```json\n[{"first": true}]\n```\n```json\n[{"second": true}]\n```'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1
        assert result[0].get("first") is True

    def test_control_characters_cleaned(self):
        text = '[{"type": "test\x01\x02"}]'
        result = extract_json_from_llm_response(text)
        assert isinstance(result, list)


# ############################################################################
# validator.py
# ############################################################################

class TestValidateInsightsAccuracy:
    def test_empty_insights(self):
        result = validate_insights_accuracy([], [])
        assert result["accurate"] is True
        assert result["accuracy_score"] == 100

    def test_concentration_accurate(self):
        data = [
            {"item": "A", "val": 50},
            {"item": "B", "val": 30},
            {"item": "C", "val": 10},
            {"item": "D", "val": 5},
            {"item": "E", "val": 5},
        ]
        insights = [{
            "type": "concentration",
            "severity": "high",
            "title": "test",
            "description": "test",
            "metrics": {"top_3_pct": 90.0},
            "recommendations": []
        }]
        result = validate_insights_accuracy(insights, data)
        assert result["accurate"] is True

    def test_concentration_inaccurate(self):
        data = [
            {"item": "A", "val": 50},
            {"item": "B", "val": 30},
            {"item": "C", "val": 10},
            {"item": "D", "val": 5},
            {"item": "E", "val": 5},
        ]
        insights = [{
            "type": "concentration",
            "severity": "high",
            "title": "test",
            "description": "test",
            "metrics": {"top_3_pct": 50.0},
            "recommendations": []
        }]
        result = validate_insights_accuracy(insights, data)
        assert result["accurate"] is False
        assert len(result["discrepancies"]) > 0

    def test_trend_valid_r_squared(self):
        insights = [{
            "type": "trend",
            "severity": "medium",
            "title": "test",
            "description": "test",
            "metrics": {"r_squared": 0.85},
            "recommendations": []
        }]
        result = validate_insights_accuracy(insights, [{"val": 1}])
        assert result["accurate"] is True

    def test_trend_invalid_r_squared(self):
        insights = [{
            "type": "trend",
            "severity": "medium",
            "title": "test",
            "description": "test",
            "metrics": {"r_squared": 1.5},
            "recommendations": []
        }]
        result = validate_insights_accuracy(insights, [{"val": 1}])
        assert result["accurate"] is False

    def test_anomaly_valid(self):
        insights = [{
            "type": "anomaly",
            "severity": "medium",
            "title": "test",
            "description": "test",
            "metrics": {"outlier_count": 2, "outliers": [{"val": 1}, {"val": 2}]},
            "recommendations": []
        }]
        result = validate_insights_accuracy(insights, [{"val": 1}])
        assert result["accurate"] is True

    def test_anomaly_count_mismatch(self):
        insights = [{
            "type": "anomaly",
            "severity": "medium",
            "title": "test",
            "description": "test",
            "metrics": {"outlier_count": 1, "outliers": [{"val": 1}, {"val": 2}, {"val": 3}]},
            "recommendations": []
        }]
        result = validate_insights_accuracy(insights, [{"val": 1}])
        assert result["accurate"] is False

    def test_unknown_type_skipped(self):
        insights = [{
            "type": "custom_type",
            "severity": "low",
            "title": "test",
            "description": "test",
            "metrics": {},
            "recommendations": []
        }]
        result = validate_insights_accuracy(insights, [{"val": 1}])
        assert result["accurate"] is True

    def test_accuracy_score_decreases_with_discrepancies(self):
        data = [{"val": i} for i in range(10)]
        insights = [
            {"type": "trend", "severity": "low", "title": "t", "description": "d",
             "metrics": {"r_squared": 5.0}, "recommendations": []},
            {"type": "trend", "severity": "low", "title": "t", "description": "d",
             "metrics": {"r_squared": -1.0}, "recommendations": []},
        ]
        result = validate_insights_accuracy(insights, data)
        assert result["accuracy_score"] < 100


class TestValidateChartSpec:
    def test_empty(self):
        result = validate_chart_spec({}, [])
        assert result["valid"] is True

    def test_missing_chart_type(self):
        data = [{"a": 1}]
        spec = {"x_axis": "a", "y_axis": "b"}
        result = validate_chart_spec(spec, data)
        assert result["valid"] is False

    def test_invalid_axis_column(self):
        data = [{"a": 1, "b": 2}]
        spec = {"chart_type": "bar", "x_axis": "nonexistent", "y_axis": "b"}
        result = validate_chart_spec(spec, data)
        assert result["valid"] is False
        assert any("nonexistent" in e for e in result["errors"])

    def test_valid_spec(self):
        data = [{"a": 1, "b": 2}]
        spec = {"chart_type": "bar", "x_axis": "a", "y_axis": "b", "data": data}
        result = validate_chart_spec(spec, data)
        assert result["valid"] is True

    def test_no_data_points_warning(self):
        data = [{"a": 1}]
        spec = {"chart_type": "bar", "data": []}
        result = validate_chart_spec(spec, data)
        assert any("no data" in w.lower() for w in result["warnings"])

    def test_many_data_points_warning(self):
        data = [{"a": 1}]
        spec = {"chart_type": "bar", "data": [{"a": i} for i in range(150)]}
        result = validate_chart_spec(spec, data)
        assert any("aggregation" in w.lower() for w in result["warnings"])


# ############################################################################
# analysis_tools.py (sync helpers)
# ############################################################################

class TestGenerateFollowups:
    def test_no_insights(self):
        result = _generate_followups({}, "some query")
        assert result == []

    def test_empty_insights_list(self):
        result = _generate_followups({"insights": []}, "some query")
        assert result == []

    def test_concentration_followup(self):
        insights = {
            "insights": [{
                "type": "concentration",
                "description": "High concentration",
                "severity": "high"
            }]
        }
        result = _generate_followups(insights, "test query")
        assert len(result) == 1
        assert result[0]["category"] == "drill_down"
        assert result[0]["priority"] == "high"

    def test_trend_followup(self):
        insights = {
            "insights": [{
                "type": "trend",
                "description": "Upward trend",
                "severity": "medium"
            }]
        }
        result = _generate_followups(insights, "test query")
        assert len(result) == 1
        assert result[0]["category"] == "comparison"

    def test_anomaly_followup(self):
        insights = {
            "insights": [{
                "type": "anomaly",
                "description": "Outliers found",
                "severity": "medium"
            }]
        }
        result = _generate_followups(insights, "test query")
        assert len(result) == 1
        assert result[0]["category"] == "investigation"

    def test_comparison_followup(self):
        insights = {
            "insights": [{
                "type": "comparison",
                "description": "Segment diff",
                "severity": "medium"
            }]
        }
        result = _generate_followups(insights, "test query")
        assert len(result) == 1
        assert result[0]["category"] == "drill_down"

    def test_max_5_suggestions(self):
        insights = {
            "insights": [
                {"type": "concentration", "description": f"c{i}", "severity": "high"}
                for i in range(10)
            ]
        }
        result = _generate_followups(insights, "test query")
        assert len(result) <= 5

    def test_unknown_type_ignored(self):
        insights = {
            "insights": [{
                "type": "unknown_type",
                "description": "Something",
                "severity": "low"
            }]
        }
        result = _generate_followups(insights, "test query")
        assert len(result) == 0


# ############################################################################
# analysis_tools.py (async handlers)
# ############################################################################

class TestAsyncHandlers:
    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.session_id = "test-session"
        ctx.connection_url = "postgresql://test"
        ctx.db_config = None
        ctx.llm_config = None
        return ctx

    @pytest.mark.asyncio
    async def test_detect_insights_handler_valid(self, mock_context):
        from app.services.tools.analysis_tools import detect_insights_handler
        data = json.dumps(SALES_DATA)
        result = await detect_insights_handler(mock_context, data, analysis_types=["concentration"])
        parsed = json.loads(result)
        assert "insights" in parsed
        assert "validation" in parsed

    @pytest.mark.asyncio
    async def test_detect_insights_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import detect_insights_handler
        result = await detect_insights_handler(mock_context, "not json")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_detect_insights_handler_not_list(self, mock_context):
        from app.services.tools.analysis_tools import detect_insights_handler
        result = await detect_insights_handler(mock_context, '{"not": "a list"}')
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_analyze_statistics_handler_valid(self, mock_context):
        from app.services.tools.analysis_tools import analyze_statistics_handler
        data = json.dumps([{"val": 10}, {"val": 20}, {"val": 30}])
        result = await analyze_statistics_handler(mock_context, data)
        parsed = json.loads(result)
        assert "statistics" in parsed
        assert "val" in parsed["statistics"]

    @pytest.mark.asyncio
    async def test_analyze_statistics_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import analyze_statistics_handler
        result = await analyze_statistics_handler(mock_context, "bad json")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_analyze_statistics_handler_not_list(self, mock_context):
        from app.services.tools.analysis_tools import analyze_statistics_handler
        result = await analyze_statistics_handler(mock_context, '{"not": "a list"}')
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_check_data_quality_handler_valid(self, mock_context):
        from app.services.tools.analysis_tools import check_data_quality_handler
        data = json.dumps([{"id": 1, "val": 10}, {"id": 2, "val": 20}])
        result = await check_data_quality_handler(mock_context, data)
        parsed = json.loads(result)
        assert "overall_score" in parsed

    @pytest.mark.asyncio
    async def test_check_data_quality_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import check_data_quality_handler
        result = await check_data_quality_handler(mock_context, "nope")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_check_data_quality_handler_not_list(self, mock_context):
        from app.services.tools.analysis_tools import check_data_quality_handler
        result = await check_data_quality_handler(mock_context, '"just a string"')
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_compare_periods_handler_valid(self, mock_context):
        from app.services.tools.analysis_tools import compare_periods_handler
        current = json.dumps(CATEGORICAL_DATA)
        result = await compare_periods_handler(mock_context, current, "segment_vs_avg")
        parsed = json.loads(result)
        assert "comparisons" in parsed

    @pytest.mark.asyncio
    async def test_compare_periods_handler_with_previous(self, mock_context):
        from app.services.tools.analysis_tools import compare_periods_handler
        current = json.dumps([{"val": 200}])
        previous = json.dumps([{"val": 100}])
        result = await compare_periods_handler(mock_context, current, "MoM", previous_data=previous)
        parsed = json.loads(result)
        assert "comparisons" in parsed

    @pytest.mark.asyncio
    async def test_compare_periods_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import compare_periods_handler
        result = await compare_periods_handler(mock_context, "bad", "MoM")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_suggest_followups_handler_valid(self, mock_context):
        from app.services.tools.analysis_tools import suggest_followups_handler
        insights_data = json.dumps({
            "insights": [
                {"type": "trend", "description": "Up", "severity": "high"},
                {"type": "anomaly", "description": "Outlier", "severity": "medium"},
            ]
        })
        result = await suggest_followups_handler(mock_context, insights_data, "test query")
        parsed = json.loads(result)
        assert "suggestions" in parsed
        assert len(parsed["suggestions"]) == 2

    @pytest.mark.asyncio
    async def test_suggest_followups_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import suggest_followups_handler
        result = await suggest_followups_handler(mock_context, "bad json", "query")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_recommend_chart_handler_valid(self, mock_context):
        from app.services.tools.analysis_tools import recommend_chart_handler
        data = json.dumps([
            {"category": "A", "value": 30},
            {"category": "B", "value": 50},
            {"category": "C", "value": 20},
        ])
        result = await recommend_chart_handler(mock_context, data)
        parsed = json.loads(result)
        assert "recommended_chart" in parsed
        assert "validation" in parsed

    @pytest.mark.asyncio
    async def test_recommend_chart_handler_with_insights(self, mock_context):
        from app.services.tools.analysis_tools import recommend_chart_handler
        data = json.dumps([{"val": 10}])
        insights = json.dumps({"insights": []})
        result = await recommend_chart_handler(mock_context, data, insights=insights)
        parsed = json.loads(result)
        assert "recommended_chart" in parsed

    @pytest.mark.asyncio
    async def test_recommend_chart_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import recommend_chart_handler
        result = await recommend_chart_handler(mock_context, "nope")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_prepare_chart_data_handler_valid(self, mock_context):
        from app.services.tools.analysis_tools import prepare_chart_data_handler
        data = json.dumps([{"name": "A", "val": 10}, {"name": "B", "val": 20}])
        result = await prepare_chart_data_handler(mock_context, data, "bar")
        parsed = json.loads(result)
        assert "transformed_data" in parsed

    @pytest.mark.asyncio
    async def test_prepare_chart_data_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import prepare_chart_data_handler
        result = await prepare_chart_data_handler(mock_context, "bad", "bar")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_annotate_chart_handler_basic(self, mock_context):
        from app.services.tools.analysis_tools import annotate_chart_handler
        chart_spec = json.dumps({"chart_type": "line", "data": [{"x": 1, "y": 2}]})
        result = await annotate_chart_handler(mock_context, chart_spec)
        parsed = json.loads(result)
        assert "annotations" in parsed

    @pytest.mark.asyncio
    async def test_annotate_chart_handler_with_insights(self, mock_context):
        from app.services.tools.analysis_tools import annotate_chart_handler
        chart_spec = json.dumps({"chart_type": "line"})
        insights = json.dumps({
            "insights": [
                {
                    "type": "trend",
                    "severity": "medium",
                    "title": "Up",
                    "description": "Going up",
                    "metrics": {"slope": 0.5, "r_squared": 0.9, "direction": "up", "acceleration": "steady"}
                },
                {
                    "type": "anomaly",
                    "severity": "high",
                    "title": "Outlier found",
                    "description": "Big outlier",
                    "metrics": {"outliers": [{"value": 1000, "z_score": 4.5, "identifier": "x=1"}]}
                }
            ]
        })
        result = await annotate_chart_handler(mock_context, chart_spec, insights=insights)
        parsed = json.loads(result)
        assert len(parsed["annotations"]) > 0

    @pytest.mark.asyncio
    async def test_annotate_chart_handler_with_statistics(self, mock_context):
        from app.services.tools.analysis_tools import annotate_chart_handler
        chart_spec = json.dumps({"chart_type": "bar"})
        statistics = json.dumps({
            "statistics": {"revenue": {"mean": 100.0, "median": 90.0}}
        })
        result = await annotate_chart_handler(mock_context, chart_spec, statistics=statistics)
        parsed = json.loads(result)
        benchmark_annotations = [a for a in parsed["annotations"] if a.get("type") == "benchmark"]
        assert len(benchmark_annotations) == 2

    @pytest.mark.asyncio
    async def test_annotate_chart_handler_with_comparisons(self, mock_context):
        from app.services.tools.analysis_tools import annotate_chart_handler
        chart_spec = json.dumps({"chart_type": "bar"})
        comparisons = json.dumps({
            "comparisons": [{"type": "MoM", "previous": 500.0, "metric": "revenue"}]
        })
        result = await annotate_chart_handler(mock_context, chart_spec, comparisons=comparisons)
        parsed = json.loads(result)
        prev_annotations = [a for a in parsed["annotations"] if a.get("subtype") == "previous_period"]
        assert len(prev_annotations) == 1

    @pytest.mark.asyncio
    async def test_annotate_chart_handler_invalid_json(self, mock_context):
        from app.services.tools.analysis_tools import annotate_chart_handler
        result = await annotate_chart_handler(mock_context, "bad json")
        parsed = json.loads(result)
        assert "error" in parsed


# ############################################################################
# Edge cases across all modules
# ############################################################################

class TestEdgeCases:
    def test_statistics_all_nulls(self):
        data = [{"val": None}, {"val": None}, {"val": None}]
        result = compute_statistics(data, columns=["val"])
        assert result == {}

    def test_statistics_mixed_types(self):
        data = [
            {"val": 10},
            {"val": "string"},
            {"val": None},
            {"val": True},
            {"val": 30},
        ]
        result = compute_statistics(data, columns=["val"])
        assert result["val"]["count"] == 2

    def test_insights_single_row(self):
        data = [{"val": 100}]
        result = detect_insights(data)
        assert result == []

    def test_insights_two_rows(self):
        data = [{"val": 100}, {"val": 200}]
        result = detect_insights(data)
        assert isinstance(result, list)

    def test_data_quality_single_row(self):
        data = [{"id": 1, "val": 42}]
        result = assess_data_quality(data)
        assert result["overall_score"] > 0
        assert result["row_count"] == 1
        assert result["duplicate_count"] == 0

    def test_chart_recommendation_no_numeric(self):
        data = [{"name": "A"}, {"name": "B"}]
        result = recommend_chart(data)
        assert result["recommended_chart"] == "bar"

    def test_comparisons_segment_no_groups(self):
        data = [
            {"cat": "A", "val": 10},
            {"cat": "A", "val": 20},
        ]
        result = compare_periods(data, "segment_vs_avg")
        assert result["comparisons"] == []

    def test_prepare_chart_data_pie_chart(self):
        data = [
            {"name": "A", "val": 30},
            {"name": "B", "val": 50},
            {"name": "C", "val": 20},
        ]
        result = prepare_chart_data(data, "pie", max_points=50, handle_outliers=False)
        assert len(result["transformed_data"]) == 3

    def test_growth_rates_all_same_value(self):
        data = [
            {"date": f"2024-0{i}-01", "value": 100}
            for i in range(1, 6)
        ]
        result = calculate_growth_rates(data, "value", "date")
        assert all(r == 0 for r in result["period_growth_rates"])

    def test_percentile_two_elements(self):
        result = _percentile([1.0, 100.0], 50)
        assert result == 50.5

    def test_compute_statistics_large_dataset(self):
        data = [{"val": float(i)} for i in range(1, 1001)]
        result = compute_statistics(data)
        assert result["val"]["count"] == 1000
        assert result["val"]["mean"] == 500.5

    def test_detect_insights_all_types_on_rich_data(self):
        data = []
        for i in range(20):
            data.append({
                "customer_name": f"Customer {i % 5}",
                "date": f"2024-{(i % 12) + 1:02d}-01",
                "revenue": (i + 1) * 100 + (1000 if i == 19 else 0),
                "units": (i + 1) * 10,
            })
        insights = detect_insights(data, analysis_types=["all"])
        assert isinstance(insights, list)
        types_found = {i["type"] for i in insights}
        assert len(types_found) >= 1

    def test_data_quality_medium_null_percentage(self):
        data = [
            {"id": 1, "opt": "A"},
            {"id": 2, "opt": None},
            {"id": 3, "opt": "C"},
            {"id": 4, "opt": None},
            {"id": 5, "opt": "E"},
            {"id": 6, "opt": "F"},
            {"id": 7, "opt": "G"},
        ]
        result = assess_data_quality(data)
        medium_issues = [
            i for i in result["issues"]
            if "opt" in i.get("description", "") and i.get("severity") == "medium"
        ]
        assert len(medium_issues) > 0

    def test_concentration_no_numeric_columns(self):
        data = [{"name": f"item{i}"} for i in range(10)]
        assert _detect_concentration(data) == []

    def test_anomaly_all_same_values(self):
        data = [{"val": 42} for _ in range(20)]
        assert _detect_anomalies(data) == []

    def test_chart_default_fallback(self):
        data = [{"text": f"unique_text_{i}"} for i in range(5)]
        result = recommend_chart(data)
        assert result["recommended_chart"] == "bar"

    def test_handle_high_cardinality_other_row_non_numeric_cols(self):
        data = [
            {"name": f"item_{i}", "value": 100 - i, "extra": f"info_{i}"}
            for i in range(30)
        ]
        result = _handle_high_cardinality(data, max_categories=10)
        assert result["grouped"] is True
        other_row = [r for r in result["data"] if r.get("name") == "Other"][0]
        assert "extra" in other_row

    def test_sanitize_value_list(self):
        result = sanitize_value([1, 2, 3])
        assert isinstance(result, str)

    def test_extract_json_code_block_with_non_json_first(self):
        text = '```\nsome text\n```\n```json\n[{"a": 1}]\n```'
        result = extract_json_from_llm_response(text)
        assert len(result) == 1

    def test_log_analysis_tool_output_does_not_crash(self):
        log_analysis_tool_output(
            tool_name="test",
            input_data={"data_rows": 10},
            output={"insights": [1, 2, 3]},
            execution_time_ms=50.0
        )

    def test_compare_periods_qoq(self):
        sql = "SELECT * FROM t WHERE d >= '2024-04-01'"
        result = _modify_sql_for_previous_period(sql, "QoQ")
        assert "2024-01" in result

    def test_date_column_with_date_object(self):
        data = [{"d": date(2024, 1, 1)}]
        from app.services.analysis_engines.chart_intelligence import _classify_column
        assert _classify_column(data, "d") == "date"
