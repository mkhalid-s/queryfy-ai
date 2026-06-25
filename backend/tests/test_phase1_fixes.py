"""
Phase 1 reliability fix regression tests.

Each test in this file corresponds to a specific bug identified in
docs/architecture-audit-2026-04-16.md and fixed in Phase 1 of the remediation
plan.

Protocol
--------
1. Tests are added in the Day 0 commit BEFORE the corresponding fix lands.
2. Each test is marked `xfail` with a reason referencing the day the fix ships.
3. When the fix lands, the xfail marker is removed in the same commit, so
   the test's green status proves the fix is active.
4. If a fix is reverted (feature flag off), its test should xfail again.

Import policy
-------------
Imports that target code added by later commits are done lazily inside the
test body. This keeps test collection green even before the new symbols
exist.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Day 1 — success-path error masking (react_agent.tool_node)
# ---------------------------------------------------------------------------


class TestSuccessPathErrorMasking:
    """
    Day 1 fix: when `execute_and_analyze` returns ``{"success": false}``, the
    result must flow through the error path. Before the fix the tool_node
    parses the JSON, finds success=False, but still returns
    ``status="complete"`` and resets ``consecutive_failures`` to 0, silently
    masking the failure.
    """

    def test_json_success_false_is_detected_as_error(self) -> None:
        """
        Contract: the helper that classifies a tool result as an error must
        treat a JSON string with ``success: false`` as an error even when the
        string does not contain the literal word "Error".

        Added by Day 1a (react_agent._is_error_result). If this xpasses to
        xfail, either the helper was removed or ``FIX_JSON_ERROR_DETECTION``
        is disabled.
        """
        from app.services.react_agent import _is_error_result

        # Note: this envelope does NOT contain "error" or "Error" literally,
        # so the legacy string check misses it. The new JSON check catches it.
        result = '{"success": false, "message": "operation failed"}'
        assert _is_error_result(result) is True, (
            "JSON with success=false must be detected as error"
        )

    def test_plain_text_tool_result_is_not_false_positive(self) -> None:
        """
        Negative contract: schema tools (``search_tables``, ``get_table_schema``)
        return plain text (not JSON). The error detector must NOT flag these
        as errors just because they are not valid JSON.
        """
        from app.services.react_agent import _is_error_result

        # Typical plain-text success output from a schema tool
        result = "Tables matching 'customer':\n  - public.customers\n  - public.customer_orders"
        assert _is_error_result(result) is False, (
            "Plain-text tool output must not be flagged as error"
        )


# ---------------------------------------------------------------------------
# Day 2a — every insight carries a `column_name` field
# ---------------------------------------------------------------------------


class TestInsightColumnNameField:
    """
    Day 2a prerequisite: all four detectors (concentration, trend, anomaly,
    comparison) must attach a ``column_name`` key to every insight they emit.
    Without this field the deduplication step (Day 2b) has nothing to group
    on and the unified ColumnClassifier (Phase 2) cannot reconcile insights.
    """

    def test_every_insight_has_column_name(self) -> None:
        from app.services.analysis_engines.insight_detector import detect_insights

        # Rich dataset designed to trigger multiple detector types
        data = [
            {
                "customer": f"Customer {i % 4}",
                "date": f"2024-{(i % 12) + 1:02d}-15",
                "revenue": (i + 1) * 100 + (5000 if i == 19 else 0),  # outlier at end
            }
            for i in range(20)
        ]

        insights = detect_insights(data, analysis_types=["all"])
        assert insights, "Expected at least one insight from rich data"

        missing = [i for i in insights if "column_name" not in i]
        assert not missing, (
            f"{len(missing)} of {len(insights)} insights missing column_name: "
            f"{[(i.get('type'), i.get('title')) for i in missing]}"
        )


# ---------------------------------------------------------------------------
# Day 2b — deduplicate insights by (type, column_name)
# ---------------------------------------------------------------------------


class TestInsightDeduplication:
    """
    Day 2b fix: when multiple detectors produce insights about the same column
    with the same type (e.g. two ``concentration`` insights on ``revenue``),
    only the highest-severity one should survive.
    """

    def test_duplicate_trend_on_same_column_collapsed(self) -> None:
        """
        Two date columns with the same numeric column trigger the
        ``date_cols x numeric_cols`` loop in ``_detect_trends`` to emit two
        trend insights about the same metric (``revenue``). Without the
        Day 2b dedup step, both appear in the final list; this test asserts
        at most one survives after dedup.

        This is the exact pattern the user reported ("same trend insight
        shown twice"): multiple date columns producing redundant insights.
        """
        from app.services.analysis_engines.insight_detector import detect_insights

        # 12 monthly rows with a clean monotonic upward trend. Two date-like
        # columns (``created_date``, ``updated_date``) pointing at the same
        # month but different days. With the ``date_cols x numeric_cols``
        # loop, the trend detector will run twice for ``revenue`` — once
        # against each date column — producing the exact duplicate pattern
        # Day 2b exists to collapse.
        data = [
            {
                "created_date": f"2024-{i + 1:02d}-01",
                "updated_date": f"2024-{i + 1:02d}-15",
                "revenue": (i + 1) * 100.0,
            }
            for i in range(12)
        ]

        insights = detect_insights(data, analysis_types=["all"])

        # Exactly one trend insight for revenue must remain after dedup.
        # (Guards against both "no dedup" — two would slip through — AND
        # "vacuous test" where the detector emits nothing at all.)
        revenue_trends = [
            i for i in insights
            if i.get("type") == "trend" and i.get("column_name") == "revenue"
        ]
        assert len(revenue_trends) == 1, (
            f"Expected exactly one revenue trend after dedup, got "
            f"{len(revenue_trends)}: {[t.get('title') for t in revenue_trends]}"
        )

        # Additional structural check: no (type, column_name) key appears
        # more than once in the final list.
        seen: dict[tuple[str, str], int] = {}
        for i in insights:
            key = (i.get("type", ""), i.get("column_name", ""))
            seen[key] = seen.get(key, 0) + 1
        duplicates = {k: v for k, v in seen.items() if v > 1}
        assert not duplicates, f"Duplicate insights found: {duplicates}"


# ---------------------------------------------------------------------------
# Day 2c — trend detection uses real date axis, not row index
# ---------------------------------------------------------------------------


class TestTrendDateAxis:
    """
    Day 2c fix: ``_detect_trends`` currently uses ``enumerate(data)`` as the
    x-axis for linear regression, which is wrong for any non-uniform time
    series (and produces absurd slopes for ID columns sorted numerically).
    The fix parses each date column's values (via ``datetime.fromisoformat``
    plus ordinal conversion) and sorts the series by true time before
    regressing.
    """

    def test_slope_reflects_days_not_row_position(self) -> None:
        from app.services.analysis_engines.insight_detector import _detect_trends

        # 3 points spread unevenly across a year.
        # Row-index slope would be ~10 (two steps of +10 per row).
        # Date-index slope is ~20 / ~334 days ≈ 0.06 per day.
        data = [
            {"date": "2024-01-01", "revenue": 10.0},
            {"date": "2024-07-01", "revenue": 20.0},
            {"date": "2024-12-01", "revenue": 30.0},
        ]

        insights = _detect_trends(data)
        trends = [i for i in insights if i.get("type") == "trend"]
        assert trends, "Expected at least one trend insight"

        slope = abs(trends[0].get("metrics", {}).get("slope", 0))
        # A date-based slope for 20 units over ~334 days is well below 1.
        # A row-based slope is ~10 per row.
        assert slope < 1.0, (
            f"Slope {slope} looks row-based; expected <1 (growth per day) "
            f"for 20-unit growth over ~334 days"
        )

    def test_trend_stable_under_row_reordering(self) -> None:
        """
        A property of a correct time-based regression: shuffling the row
        order of the input must not change the detected slope (because the
        fix sorts by parsed date before regressing).
        """
        from app.services.analysis_engines.insight_detector import _detect_trends

        ordered = [
            {"date": "2024-01-01", "revenue": 10.0},
            {"date": "2024-06-01", "revenue": 20.0},
            {"date": "2024-12-01", "revenue": 30.0},
        ]
        shuffled = [ordered[2], ordered[0], ordered[1]]

        def slope_of(data: list) -> float:
            trends = [i for i in _detect_trends(data) if i.get("type") == "trend"]
            assert trends, "Expected a trend"
            return float(trends[0].get("metrics", {}).get("slope", 0))

        assert slope_of(ordered) == pytest.approx(slope_of(shuffled), rel=1e-6), (
            "Trend slope changed when rows were reordered — "
            "indicates row-index axis, not date axis"
        )


# ---------------------------------------------------------------------------
# Day 2c — smart ID column exclusion (cardinality-aware)
# ---------------------------------------------------------------------------


class TestSmartIdExclusion:
    """
    Day 2c fix: columns matching ID-like name patterns (``_id$``, ``^id$``,
    ``_pk$``) are excluded from numeric analysis ONLY when their cardinality
    equals the row count (i.e. all values are unique, indicating a primary
    key or sequence). Columns like ``region_id`` with low cardinality
    continue to be analyzed because concentration and comparison insights
    on them are genuinely useful.
    """

    def test_all_unique_id_excluded_but_low_cardinality_id_kept(self) -> None:
        from app.services.analysis_engines.insight_detector import _get_numeric_columns

        # 100 rows: policy_id is all-unique (100 distinct values),
        # region_id has only 5 distinct values, revenue is a real metric.
        data = [
            {
                "policy_id": i + 1,
                "region_id": i % 5,
                "revenue": (i + 1) * 100,
            }
            for i in range(100)
        ]

        numeric_cols = _get_numeric_columns(data)

        assert "policy_id" not in numeric_cols, (
            "All-unique policy_id should be excluded as an ID column"
        )
        assert "region_id" in numeric_cols, (
            "region_id has low cardinality (5), should be kept for analysis"
        )
        assert "revenue" in numeric_cols, "revenue is a real metric, must be kept"

    def test_unrelated_numeric_column_not_excluded(self) -> None:
        """
        Regression guard (not xfail — this must pass both before AND after
        the Day 2c fix). Its job is to catch a future mistake where someone
        over-broadens the ID-exclusion heuristic and starts filtering real
        metric columns.

        ``invoice_number`` and ``zip_code`` are numeric but match neither the
        ``_id$`` / ``^id$`` / ``_pk$`` patterns, so they must remain in the
        numeric-columns list regardless of cardinality.
        """
        from app.services.analysis_engines.insight_detector import _get_numeric_columns

        data = [
            {
                "invoice_number": 10000 + i,
                "zip_code": 94100 + (i % 20),
                "amount": (i + 1) * 50,
            }
            for i in range(100)
        ]
        numeric_cols = _get_numeric_columns(data)

        assert "invoice_number" in numeric_cols, (
            "invoice_number does not match ID patterns — must not be excluded"
        )
        assert "zip_code" in numeric_cols, (
            "zip_code does not match ID patterns — must not be excluded"
        )
        assert "amount" in numeric_cols
