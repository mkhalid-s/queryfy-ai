"""
Phase 3a reliability fix regression tests (Data Lake Foundation).

Each test corresponds to a Phase 3a item in
``docs/architecture-audit-2026-04-16.md``. Protocol mirrors Phases 1/2:
fail-first, flag-gated, lazy imports for not-yet-introduced symbols.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Day 1 — per-DB tool-execution timeout map
# ---------------------------------------------------------------------------
#
# Phase 1 Day 4 introduced a binary "30s transactional / 300s data lake"
# rule. Phase 3a Day 1 replaces that with an explicit per-DB map so each
# database gets a timeout that matches its real-world query-duration
# profile: BigQuery/Hive/Spark analytical queries commonly need >5 min,
# while Athena/Clickhouse are usually fast. The legacy AGENT_TOOL_TIMEOUT
# remains as a floor — if an operator configures a longer default, we
# won't shrink it.


class TestPerDbTimeoutMap:
    """Day 1: TOOL_TIMEOUT_BY_DB supersedes the binary split."""

    def test_map_exists_and_covers_expected_dbs(self) -> None:
        from app.services.react_agent import TOOL_TIMEOUT_BY_DB

        expected_dbs = {
            "postgresql",
            "mysql",
            "sqlite",
            "sqlserver",
            "oracle",
            "mongodb",
            "cassandra",
            "dynamodb",
            "duckdb",
            "athena",
            "clickhouse",
            "trino",
            "presto",
            "redshift",
            "snowflake",
            "databricks",
            "bigquery",
            "hive",
            "spark",
        }
        missing = expected_dbs - set(TOOL_TIMEOUT_BY_DB.keys())
        assert not missing, (
            f"TOOL_TIMEOUT_BY_DB is missing entries for {sorted(missing)}"
        )

    def test_bigquery_gets_ten_minute_timeout(self) -> None:
        from app.core.config import settings
        from app.services.react_agent import _effective_tool_timeout

        # Floor is AGENT_TOOL_TIMEOUT (default 30). BigQuery deserves 600.
        assert settings.FIX_DB_SPECIFIC_TIMEOUTS is True
        assert _effective_tool_timeout("bigquery") == 600.0

    def test_postgres_keeps_thirty_seconds(self) -> None:
        from app.services.react_agent import _effective_tool_timeout

        assert _effective_tool_timeout("postgresql") == 30.0

    def test_case_insensitive(self) -> None:
        from app.services.react_agent import _effective_tool_timeout

        assert _effective_tool_timeout("BigQuery") == 600.0
        assert _effective_tool_timeout("SNOWFLAKE") == 300.0

    def test_floor_honoured_when_operator_configured_higher(
        self, monkeypatch
    ) -> None:
        """
        If AGENT_TOOL_TIMEOUT is deliberately high (e.g. 900s), a DB in
        the map at 180s should still get at least the floor.
        """
        import app.services.react_agent as ra

        monkeypatch.setattr(ra, "TOOL_EXECUTION_TIMEOUT", 900.0)
        assert ra._effective_tool_timeout("athena") == 900.0

    def test_unknown_db_falls_back_to_base(self) -> None:
        from app.services.react_agent import _effective_tool_timeout

        # Not in the map → base AGENT_TOOL_TIMEOUT (30s default).
        assert _effective_tool_timeout("zzz-unknown") == 30.0

    def test_flag_off_reverts_to_phase1_behaviour(self, monkeypatch) -> None:
        """
        FIX_DB_SPECIFIC_TIMEOUTS=False must fall back to the Phase 1 Day 4
        binary "transactional 30s / data-lake 300s" rule exactly, so the
        feature flag is a true rollback switch.
        """
        from app.core.config import settings
        from app.services.react_agent import _effective_tool_timeout

        monkeypatch.setattr(settings, "FIX_DB_SPECIFIC_TIMEOUTS", False)
        # Phase 1 still gives 300s for bigquery, not 600.
        assert _effective_tool_timeout("bigquery") == 300.0
        assert _effective_tool_timeout("postgresql") == 30.0


# ---------------------------------------------------------------------------
# Day 2 — SSE heartbeat task
# ---------------------------------------------------------------------------
#
# During multi-minute data-lake queries the SSE stream can go quiet for
# the duration of the tool execution. Some reverse proxies (cloud LBs,
# corporate squid) and browsers close idle streams at 60s / 120s. A
# server-emitted heartbeat every 15s keeps the connection warm without
# polluting user-visible chat events.


class TestSseHeartbeat:
    """Day 2: background heartbeat generator + feature flag."""

    def test_heartbeat_helper_exists(self) -> None:
        from app.services import react_agent as ra

        assert hasattr(ra, "_sse_heartbeat_event"), (
            "react_agent must expose _sse_heartbeat_event(elapsed_ms) helper"
        )

    def test_heartbeat_event_shape(self) -> None:
        from app.services.react_agent import _sse_heartbeat_event

        evt = _sse_heartbeat_event(elapsed_ms=12345)
        assert evt["event"] == "heartbeat"
        assert evt["elapsed_ms"] == 12345

    def test_feature_flag_exists(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "FIX_SSE_HEARTBEAT"), (
            "settings.FIX_SSE_HEARTBEAT feature flag must exist"
        )
        assert settings.FIX_SSE_HEARTBEAT is True, (
            "FIX_SSE_HEARTBEAT should default True for Phase 3a"
        )

    @pytest.mark.asyncio
    async def test_merge_emits_heartbeat_during_quiet_period(self) -> None:
        """
        ``_merge_stream_with_heartbeat`` wraps an async iterator and
        injects a heartbeat event whenever the underlying source is
        silent for ``interval`` seconds. Verifies both real events and
        heartbeats are delivered in order.
        """
        import asyncio

        from app.services.react_agent import _merge_stream_with_heartbeat

        async def source():
            yield {"event": "thinking", "iteration": 0}
            await asyncio.sleep(0.12)  # quiet period — should trigger heartbeat
            yield {"event": "thinking", "iteration": 1}

        events: list = []
        async for evt in _merge_stream_with_heartbeat(
            source(), interval=0.05, start_time=0.0
        ):
            events.append(evt)

        kinds = [e["event"] for e in events]
        assert kinds[0] == "thinking"
        assert "heartbeat" in kinds, (
            f"Expected at least one heartbeat during the 0.12s quiet "
            f"period; got only {kinds}"
        )
        assert kinds[-1] == "thinking"


# ---------------------------------------------------------------------------
# Day 3 — aggregation detection
# ---------------------------------------------------------------------------
#
# Add ``aggregated: bool`` and ``grouping_columns: List[str]`` to
# execution_result so downstream (Phase 3c insight thresholds, chart
# recommender, LLM prompt templates) can differentiate aggregated-mode
# results from raw rows. Detection heuristic: GROUP BY clause in SQL OR
# aggregate function wrapping a column name (SUM/COUNT/AVG/MIN/MAX).


class TestAggregationDetector:
    """Day 3: ``detect_aggregation(sql, columns)`` correctness."""

    def test_module_exists(self) -> None:
        from app.services.analysis_engines import aggregation_detector

        assert hasattr(aggregation_detector, "detect_aggregation")

    def test_group_by_detected(self) -> None:
        from app.services.analysis_engines.aggregation_detector import (
            detect_aggregation,
        )

        result = detect_aggregation(
            sql="SELECT region, SUM(revenue) FROM sales GROUP BY region",
            columns=["region", "sum_revenue"],
        )
        assert result["aggregated"] is True
        assert result["grouping_columns"] == ["region"]
        # SUM(revenue) → aggregate output
        assert "sum_revenue" in result["aggregate_columns"] or \
               any("revenue" in c.lower() for c in result["aggregate_columns"])

    def test_multi_column_group_by(self) -> None:
        from app.services.analysis_engines.aggregation_detector import (
            detect_aggregation,
        )

        result = detect_aggregation(
            sql="SELECT region, product, COUNT(*) FROM sales GROUP BY region, product",
            columns=["region", "product", "count"],
        )
        assert result["aggregated"] is True
        assert "region" in result["grouping_columns"]
        assert "product" in result["grouping_columns"]

    def test_no_group_by_raw_rows(self) -> None:
        from app.services.analysis_engines.aggregation_detector import (
            detect_aggregation,
        )

        result = detect_aggregation(
            sql="SELECT id, name, revenue FROM sales WHERE year = 2024 LIMIT 100",
            columns=["id", "name", "revenue"],
        )
        assert result["aggregated"] is False
        assert result["grouping_columns"] == []

    def test_aggregate_column_names_without_group_by_still_flagged(self) -> None:
        """
        A query like ``SELECT COUNT(*) FROM t`` has no GROUP BY but is
        still aggregated (implicit single group). Column-name heuristic
        picks this up.
        """
        from app.services.analysis_engines.aggregation_detector import (
            detect_aggregation,
        )

        result = detect_aggregation(
            sql="SELECT COUNT(*) AS total FROM sales",
            columns=["total"],
        )
        assert result["aggregated"] is True
        # No GROUP BY clause → no grouping columns
        assert result["grouping_columns"] == []

    def test_case_insensitive(self) -> None:
        from app.services.analysis_engines.aggregation_detector import (
            detect_aggregation,
        )

        result = detect_aggregation(
            sql="select region, sum(revenue) from sales group by region",
            columns=["region", "sum_revenue"],
        )
        assert result["aggregated"] is True
        assert result["grouping_columns"] == ["region"]

    def test_group_by_in_subquery_is_not_outer_aggregation(self) -> None:
        """
        ``SELECT * FROM (SELECT region, SUM(revenue) FROM sales GROUP BY region) t``
        should NOT be flagged as aggregated at the outer level — the
        detector focuses on the outermost query. (Edge case documented;
        a false-positive is acceptable here for Phase 3a since it only
        affects insight threshold tuning downstream.)
        """
        from app.services.analysis_engines.aggregation_detector import (
            detect_aggregation,
        )

        # Pragmatic: we DO flag this as aggregated because the heuristic
        # is regex-based. The test documents that known limitation so
        # nobody is surprised.
        result = detect_aggregation(
            sql="SELECT * FROM (SELECT region, SUM(revenue) s FROM sales GROUP BY region) t",
            columns=["region", "s"],
        )
        # Regex-based heuristic will see the inner GROUP BY — acceptable.
        assert result["aggregated"] is True

    def test_feature_flag_exists(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "FIX_AGGREGATION_DETECTION")
        assert settings.FIX_AGGREGATION_DETECTION is True


class TestAggregationInExecutionResult:
    """Day 3: execute_and_analyze must surface aggregated + grouping_columns."""

    @pytest.mark.asyncio
    async def test_execute_and_analyze_payload_has_aggregation_fields(
        self, monkeypatch
    ) -> None:
        """
        Stub DatabaseService.execute_query and call execute_and_analyze
        with a GROUP BY query; verify the returned JSON includes the new
        fields.
        """
        import json

        from app.services.tools import query_tools

        # Stub the DB call so we don't need a real database.
        async def fake_execute_query(**kwargs):
            return {
                "rows": [
                    {"region": "R1", "total": 100},
                    {"region": "R2", "total": 200},
                ],
                "columns": ["region", "total"],
                "execution_time_ms": 5,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.services.database_service.DatabaseService.execute_query",
            fake_execute_query,
        )

        class FakeContext:
            db_config = {
                "db_type": "postgresql",
                "connection_url": "postgresql://x",
                "db_name": "t",
            }

        result_json = await query_tools.execute_and_analyze(
            context=FakeContext(),
            sql="SELECT region, SUM(total) AS total FROM sales GROUP BY region",
            limit=10,
        )
        parsed = json.loads(result_json)
        assert parsed.get("success") is True
        assert parsed.get("aggregated") is True, (
            "execute_and_analyze payload must include aggregated=True"
        )
        assert parsed.get("grouping_columns") == ["region"], (
            f"expected grouping_columns=['region'], got "
            f"{parsed.get('grouping_columns')}"
        )
