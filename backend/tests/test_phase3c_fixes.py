"""
Phase 3c reliability fix regression tests (Analytics excellence).

Scope of this file:
  - 3c.1 — aggregated-mode insight thresholds
  - 3c.2 — system prompt conditional GROUP BY guidance

Cost-estimation (3c.3) requires real BigQuery credentials and lives in
tests/integration/data_lakes with requires_real_bigquery marker.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 3c.1 — aggregated-mode insight thresholds
# ---------------------------------------------------------------------------
#
# When results come from a GROUP BY, insights need different thresholds:
# - Each row is a pre-aggregated group total, not a raw observation.
# - N is much smaller (often 5-30 groups vs. 1000+ rows).
# - Trends on <5 group points are noise.
# - z-score > 3 is very unlikely with small N (thin tails) — we tighten
#   to > 2 so genuine outliers aren't missed.
# - Concentration (Pareto) is already implicit in aggregated views so
#   the baseline shifts.


class TestAggregatedModeFlag:
    """3c.1: ``detect_insights(data, aggregated=True)`` is the entry point."""

    def test_flag_exists(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "FIX_AGGREGATED_MODE_THRESHOLDS")
        assert settings.FIX_AGGREGATED_MODE_THRESHOLDS is True

    def test_detect_insights_accepts_aggregated_kwarg(self) -> None:
        """Public API must accept the new keyword argument."""
        from app.services.analysis_engines.insight_detector import detect_insights

        # Empty data — should return [] regardless of aggregated value,
        # but the call signature must accept the kwarg without error.
        assert detect_insights([], aggregated=True) == []
        assert detect_insights([], aggregated=False) == []


class TestAggregatedTrendThreshold:
    """3c.1: trends require >=5 groups in aggregated mode."""

    def _monthly_series(self, n: int):
        """Build n groups of (month, revenue) — mimics a GROUP BY month."""
        return [
            {"month": f"2024-{i + 1:02d}-01", "revenue": 100 * (i + 1)}
            for i in range(n)
        ]

    def test_four_groups_does_not_emit_trend(self) -> None:
        """Aggregated with 4 groups → no trend insight even if monotonic."""
        from app.services.analysis_engines.insight_detector import detect_insights

        insights = detect_insights(
            self._monthly_series(4),
            analysis_types=["trend"],
            aggregated=True,
        )
        trend_insights = [i for i in insights if i.get("type") == "trend"]
        assert trend_insights == [], (
            "Aggregated data with <5 groups should NOT produce trend insights"
        )

    def test_five_groups_does_emit_trend(self) -> None:
        """>=5 groups clears the aggregated floor."""
        from app.services.analysis_engines.insight_detector import detect_insights

        insights = detect_insights(
            self._monthly_series(7),
            analysis_types=["trend"],
            aggregated=True,
        )
        trend_insights = [i for i in insights if i.get("type") == "trend"]
        assert len(trend_insights) >= 1, (
            "7 monotonic aggregated groups should emit at least one trend insight"
        )

    def test_raw_mode_keeps_three_point_floor(self) -> None:
        """Raw mode (aggregated=False) still uses the original 3-point floor."""
        from app.services.analysis_engines.insight_detector import detect_insights

        # 4 points — below aggregated's 5 floor, above raw's 3 floor.
        insights = detect_insights(
            self._monthly_series(4),
            analysis_types=["trend"],
            aggregated=False,
        )
        trend_insights = [i for i in insights if i.get("type") == "trend"]
        assert len(trend_insights) >= 1, (
            "Raw mode should keep the legacy 3-point trend floor"
        )


class TestAggregatedAnomalyThreshold:
    """
    3c.1: aggregated mode tightens the z-score threshold from 3 to 2 so
    genuine outliers don't get hidden by small-N thin tails.
    """

    def test_aggregated_uses_tighter_zscore(self) -> None:
        """
        Build an aggregated series where one row is ~2.5 stdev from mean.
        Raw mode (z>3) misses it; aggregated mode (z>2) catches it.
        """
        from app.services.analysis_engines.insight_detector import detect_insights

        # 8 groups with one moderately high outlier
        data = [
            {"region": f"R{i}", "total": v}
            for i, v in enumerate([10, 12, 11, 13, 9, 11, 12, 30])
        ]
        # z for value=30 with the rest around 11: approx 2.5 stdev above mean.

        raw_insights = detect_insights(
            data, analysis_types=["anomaly"], aggregated=False
        )
        agg_insights = detect_insights(
            data, analysis_types=["anomaly"], aggregated=True
        )

        raw_anomalies = [i for i in raw_insights if i.get("type") == "anomaly"]
        agg_anomalies = [i for i in agg_insights if i.get("type") == "anomaly"]

        assert agg_anomalies, (
            "Aggregated mode should flag ~2.5-stdev outlier in small group list"
        )
        # raw can either catch it or not depending on exact variance; the
        # contract is only that aggregated is ≥ raw in sensitivity.
        assert len(agg_anomalies) >= len(raw_anomalies), (
            "Aggregated threshold should be at least as sensitive as raw"
        )


class TestAggregatedInsightsWiredThroughExecuteAndAnalyze:
    """
    3c.1: ``execute_and_analyze`` must pass ``aggregated`` from the
    detected flag (3a.3) into ``detect_insights``.
    """

    @pytest.mark.asyncio
    async def test_execute_and_analyze_passes_aggregated_flag(
        self, monkeypatch
    ) -> None:
        import json

        from app.services.tools import query_tools

        async def fake_execute_query(**kwargs):
            return {
                "rows": [
                    {"region": f"R{i}", "total": v}
                    for i, v in enumerate([100, 110, 105, 95, 108, 112, 100, 2000])
                ],
                "columns": ["region", "total"],
                "execution_time_ms": 5,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.services.database_service.DatabaseService.execute_query",
            fake_execute_query,
        )

        # ``detect_insights`` is imported inside execute_and_analyze's
        # function body, so patch it at its defining module. The import
        # inside the function body will re-resolve to this spy.
        from app.services.analysis_engines import insight_detector

        captured: dict = {}
        original = insight_detector.detect_insights

        def spy(data, analysis_types=None, aggregated=False):
            captured["aggregated"] = aggregated
            return original(
                data, analysis_types=analysis_types, aggregated=aggregated
            )

        monkeypatch.setattr(insight_detector, "detect_insights", spy)
        # The analysis_engines package may re-export it at package level.
        import app.services.analysis_engines as analysis_engines_pkg
        monkeypatch.setattr(
            analysis_engines_pkg, "detect_insights", spy, raising=False
        )

        class FakeContext:
            db_config = {
                "db_type": "postgresql",
                "connection_url": "postgresql://x",
                "db_name": "t",
            }

        # SQL with GROUP BY → aggregation detector flags it True.
        await query_tools.execute_and_analyze(
            context=FakeContext(),
            sql="SELECT region, SUM(amount) AS total FROM sales GROUP BY region",
            limit=10,
        )

        assert captured.get("aggregated") is True, (
            "execute_and_analyze must pass aggregated=True when the "
            "aggregation detector flags the query"
        )


# ---------------------------------------------------------------------------
# 3c.2 — system prompt conditional GROUP BY guidance
# ---------------------------------------------------------------------------


class TestPromptAggregationHint:
    """
    3c.2: analyst-mode system prompt gains a conditional hint telling the
    LLM to prefer GROUP BY over SELECT * for analytical questions.
    Guarded by ``FIX_PROMPT_AGGREGATION_HINT``.
    """

    def test_flag_exists(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "FIX_PROMPT_AGGREGATION_HINT")
        assert settings.FIX_PROMPT_AGGREGATION_HINT is True

    def test_prompt_contains_group_by_hint_when_enabled(
        self, monkeypatch
    ) -> None:
        from app.core.config import settings
        from app.services import react_agent as ra

        monkeypatch.setattr(settings, "FIX_PROMPT_AGGREGATION_HINT", True)

        hint = ra._aggregation_prompt_hint()
        assert hint, "Hint must be non-empty when flag is on"
        assert "GROUP BY" in hint.upper(), (
            "Hint must mention GROUP BY so the LLM routes analytical "
            "questions to aggregated SQL"
        )

    def test_hint_empty_when_flag_off(self, monkeypatch) -> None:
        from app.core.config import settings
        from app.services import react_agent as ra

        monkeypatch.setattr(settings, "FIX_PROMPT_AGGREGATION_HINT", False)
        assert ra._aggregation_prompt_hint() == ""
