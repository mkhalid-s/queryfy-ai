"""
Phase 4 — size-unbounded analysis regression tests.

Scope:
  - 4.0 ResultCache service (Redis + in-memory fallback)
  - 4.1 execute_and_analyze: full-dataset analysis, rows cached
  - 4.2 LLM drill-down tools (get_cached_rows / inspect_cached_result)
  - 4.3 Frontend fetch endpoint
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 4.0 — ResultCache
# ---------------------------------------------------------------------------


class TestResultCache:
    """Day 4.0: ResultCache stores + retrieves with a stable handle."""

    def _fresh_cache(self, monkeypatch):
        """Create a fresh singleton so each test starts clean."""
        from app.services import result_cache as module

        # Drop any singleton leftover from previous tests
        module.ResultCache._instance = None
        cache = module.ResultCache()
        # Force in-memory backend (don't touch dev-machine Redis during tests)
        cache.redis_client = None
        cache._memory_store.clear()
        return cache

    def test_store_and_get_round_trip(self, monkeypatch) -> None:
        cache = self._fresh_cache(monkeypatch)

        ref = cache.store(
            session_id="s1",
            query_id="q1",
            sql="SELECT 1",
            columns=["x", "y"],
            rows=[{"x": 1, "y": 2}, {"x": 3, "y": 4}],
            db_type="postgresql",
        )
        assert ref == "result:s1:q1"

        got = cache.get(ref)
        assert got is not None
        assert got.columns == ["x", "y"]
        assert got.row_count == 2
        assert got.rows == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
        assert got.sql == "SELECT 1"
        assert got.db_type == "postgresql"

    def test_get_rows_slice_pagination(self, monkeypatch) -> None:
        cache = self._fresh_cache(monkeypatch)

        rows = [{"i": i} for i in range(100)]
        ref = cache.store(
            session_id="s1", query_id="q2", sql="", columns=["i"], rows=rows
        )

        page1 = cache.get_rows_slice(ref, offset=0, limit=10)
        assert page1["rows"] == [{"i": i} for i in range(10)]
        assert page1["total_row_count"] == 100
        assert page1["has_more"] is True

        page3 = cache.get_rows_slice(ref, offset=90, limit=20)
        assert page3["rows"] == [{"i": i} for i in range(90, 100)]
        assert page3["has_more"] is False

    def test_delete_removes(self, monkeypatch) -> None:
        cache = self._fresh_cache(monkeypatch)

        ref = cache.store(
            session_id="s1", query_id="q3", sql="", columns=[], rows=[]
        )
        assert cache.get(ref) is not None
        assert cache.delete(ref) is True
        assert cache.get(ref) is None

    def test_delete_session_purges_all(self, monkeypatch) -> None:
        cache = self._fresh_cache(monkeypatch)

        for i in range(3):
            cache.store(
                session_id="sA", query_id=f"q{i}", sql="", columns=[], rows=[]
            )
        cache.store(
            session_id="sB", query_id="q0", sql="", columns=[], rows=[]
        )

        removed = cache.delete_session("sA")
        assert removed == 3
        # sB entry untouched
        assert cache.get("result:sB:q0") is not None
        assert cache.size() == 1

    def test_missing_ref_returns_none(self, monkeypatch) -> None:
        cache = self._fresh_cache(monkeypatch)
        assert cache.get("result:nope:q") is None
        assert cache.get_rows_slice("result:nope:q") is None

    def test_row_count_can_exceed_stored_rows(self, monkeypatch) -> None:
        """Supplying explicit ``row_count`` records the true DB count
        even when ``rows`` is a truncated preview."""
        cache = self._fresh_cache(monkeypatch)

        ref = cache.store(
            session_id="s1",
            query_id="q4",
            sql="",
            columns=["x"],
            rows=[{"x": 1}],  # preview only
            row_count=9147,
        )
        got = cache.get(ref)
        assert got.row_count == 9147
        assert len(got.rows) == 1

    def test_config_flag_exists(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "FIX_RESULT_CACHE")
        assert hasattr(settings, "RESULT_CACHE_TTL_SECONDS")
        assert settings.FIX_RESULT_CACHE is True
        assert settings.RESULT_CACHE_TTL_SECONDS > 0

    def test_memory_store_caps_at_configured_ceiling(self, monkeypatch) -> None:
        """
        Prod audit HIGH: during a Redis outage the in-memory fallback
        accumulates entries forever. Hotfix caps to
        RESULT_CACHE_MEMORY_MAX_ENTRIES (default 200) with LRU eviction.
        """
        import app.services.result_cache as cache_module

        # Patch the cap to something small we can exceed quickly.
        monkeypatch.setattr(cache_module, "_MEMORY_STORE_MAX_ENTRIES", 5)
        cache = self._fresh_cache(monkeypatch)

        for i in range(10):
            cache.store(
                session_id="s",
                query_id=f"q{i}",
                sql="",
                columns=["x"],
                rows=[{"x": i}],
            )

        # Size is capped; oldest entries evicted.
        assert cache.size() == 5
        # The most recent 5 survive.
        assert cache.get("result:s:q9") is not None
        assert cache.get("result:s:q5") is not None
        # Old ones are gone.
        assert cache.get("result:s:q0") is None
        assert cache.get("result:s:q4") is None

    @pytest.mark.asyncio
    async def test_astore_timeout_falls_back_to_memory(self, monkeypatch) -> None:
        """
        Prod audit HIGH: if Redis SETEX hangs, astore times out via
        asyncio.wait_for and drops the redis_client so subsequent
        calls skip it instead of piling up more timeouts.
        """
        cache = self._fresh_cache(monkeypatch)

        # Install a "Redis" that hangs longer than our test timeout
        # budget but not pathologically long (thread cleanup on
        # pytest teardown has to wait for it). 2s is enough to prove
        # the timeout fires within the 0.1s budget.
        class HangingRedis:
            def setex(self, *a, **kw):
                import time
                time.sleep(2)

            def get(self, *a, **kw):
                return None

            def delete(self, *a, **kw):
                return 0

            def keys(self, *a, **kw):
                return []

        cache.redis_client = HangingRedis()
        # Tighten the timeout for the test — real default is 10s.
        monkeypatch.setattr(cache, "_IO_TIMEOUT_SECONDS", 0.1, raising=False)

        ref = await cache.astore(
            session_id="s", query_id="t", sql="", columns=[], rows=[]
        )
        # Stored successfully in memory via the fallback.
        assert ref == "result:s:t"
        assert cache.get(ref) is not None
        # Redis client was dropped so the next call doesn't block.
        assert cache.redis_client is None

    @pytest.mark.asyncio
    async def test_async_wrappers_available_and_round_trip(
        self, monkeypatch
    ) -> None:
        """
        Batch E: async wrappers (astore / aget / aget_rows_slice) wrap
        the sync redis-py calls in asyncio.to_thread so the SSE
        heartbeat loop doesn't stall on big writes.
        """
        cache = self._fresh_cache(monkeypatch)

        ref = await cache.astore(
            session_id="s",
            query_id="q",
            sql="SELECT 1",
            columns=["x"],
            rows=[{"x": i} for i in range(50)],
        )
        assert ref == "result:s:q"

        full = await cache.aget(ref)
        assert full is not None
        assert full.row_count == 50

        slice_ = await cache.aget_rows_slice(ref, offset=10, limit=5)
        assert slice_["rows"] == [{"x": i} for i in range(10, 15)]
        assert slice_["total_row_count"] == 50


# ---------------------------------------------------------------------------
# 4.1 — execute_and_analyze: full-dataset analysis, rows to cache
# ---------------------------------------------------------------------------


class TestExecuteAndAnalyzeCaching:
    """Day 4.1: tool returns rows_ref + preview, full rows live in cache."""

    @pytest.mark.asyncio
    async def test_large_result_returns_rows_ref_and_preview(
        self, monkeypatch
    ) -> None:
        """
        Simulate a 2,500-row query (well above the legacy 1000-row
        sampling threshold). Verify:
          - response.row_count reports the true count
          - response.rows is a preview (<= 20), NOT the full set
          - response.rows_ref exists
          - the cache actually holds all 2500 rows
        """
        import json

        from app.services import result_cache as cache_module
        from app.services.tools import query_tools

        # Fresh cache, installed as the module singleton that the tool
        # imports. Resetting _instance alone isn't enough because the
        # module-level ``result_cache`` name was bound at import time.
        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)

        # Fake DB returning 2500 rows
        async def fake_execute_query(**kwargs):
            return {
                "rows": [{"id": i, "val": i * 10} for i in range(2500)],
                "columns": ["id", "val"],
                "execution_time_ms": 42,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.services.database_service.DatabaseService.execute_query",
            fake_execute_query,
        )

        class FakeContext:
            session_id = "test-session-4-1"
            db_config = {
                "db_type": "postgresql",
                "connection_url": "postgresql://x",
                "db_name": "t",
            }

        result_json = await query_tools.execute_and_analyze(
            context=FakeContext(),
            sql="SELECT id, val FROM t",
            limit=10000,
        )
        payload = json.loads(result_json)

        assert payload["success"] is True
        assert payload["row_count"] == 2500
        assert payload["rows_cached"] is True
        assert payload["rows_ref"].startswith("result:test-session-4-1:")
        assert len(payload["rows"]) <= 20, (
            f"Tool response should carry a preview (<=20 rows), "
            f"got {len(payload['rows'])}"
        )

        # Full rows must be reachable via the cache.
        slice_ = cache.get_rows_slice(payload["rows_ref"], offset=0, limit=10)
        assert slice_["total_row_count"] == 2500

        tail = cache.get_rows_slice(payload["rows_ref"], offset=2499, limit=10)
        assert tail["rows"] == [{"id": 2499, "val": 24990}]

    @pytest.mark.asyncio
    async def test_tool_payload_never_exceeds_50kb(self, monkeypatch) -> None:
        """
        The 50KB registry cap is what historically triggered the
        "Result too large for processing" error and the agent's
        retry-with-simpler-SQL loop. After Phase 4.1 the tool response
        should stay well under that cap regardless of row count because
        rows no longer ride in the payload.
        """
        import json

        from app.services import result_cache as cache_module
        from app.services.tools import query_tools

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)

        # 10,000 rows × 10 wide columns → well over 50KB raw
        wide_columns = [f"col_{i}" for i in range(10)]
        wide_row_template = {c: "x" * 50 for c in wide_columns}

        async def fake_execute_query(**kwargs):
            return {
                "rows": [dict(wide_row_template) for _ in range(10000)],
                "columns": wide_columns,
                "execution_time_ms": 999,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.services.database_service.DatabaseService.execute_query",
            fake_execute_query,
        )

        class FakeContext:
            session_id = "wide-session"
            db_config = {
                "db_type": "postgresql",
                "connection_url": "postgresql://x",
                "db_name": "t",
            }

        result_json = await query_tools.execute_and_analyze(
            context=FakeContext(),
            sql="SELECT * FROM wide",
            limit=10000,
        )
        # Registry's hard cap is 50,000 chars. Give ourselves a margin.
        assert len(result_json) < 50_000, (
            f"Phase 4.1 tool payload grew to {len(result_json)} bytes; "
            f"rows must be cached out-of-band so the payload stays <50KB"
        )

        payload = json.loads(result_json)
        assert payload["success"] is True
        assert payload["row_count"] == 10000

    @pytest.mark.asyncio
    async def test_cache_failure_still_truncates_preview(self, monkeypatch) -> None:
        """
        Validator audit HIGH finding: when ResultCache.store() raises,
        the fallback path historically kept the full sanitized_rows,
        which then blew past the registry's 50KB cap and produced the
        exact "Result too large for processing" error Phase 4.1 was
        supposed to eliminate. Now the fallback truncates to a 20-row
        preview AND advertises ``rows_truncated: true`` so the
        frontend doesn't display the preview as if it were complete.
        """
        import json

        from app.services import result_cache as cache_module
        from app.services.tools import query_tools

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        # Force store() to raise to simulate Redis outage / disk full.
        def explode(*args, **kwargs):
            raise RuntimeError("simulated cache outage")

        monkeypatch.setattr(cache, "store", explode)
        monkeypatch.setattr(cache_module, "result_cache", cache)

        async def fake_execute_query(**kwargs):
            return {
                "rows": [{"id": i, "v": "x" * 200} for i in range(2000)],
                "columns": ["id", "v"],
                "execution_time_ms": 5,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.services.database_service.DatabaseService.execute_query",
            fake_execute_query,
        )

        class FakeContext:
            session_id = "fail-session"
            db_config = {
                "db_type": "postgresql",
                "connection_url": "postgresql://x",
                "db_name": "t",
            }

        result_json = await query_tools.execute_and_analyze(
            context=FakeContext(),
            sql="SELECT * FROM t",
            limit=10000,
        )
        payload = json.loads(result_json)

        assert payload["success"] is True
        # Preview MUST be truncated; full set would blow the 50KB cap.
        assert len(payload["rows"]) <= 20
        # And the response MUST advertise that rows are truncated so
        # the frontend doesn't misrepresent the preview.
        assert payload.get("rows_cached") is False
        assert payload.get("rows_truncated") is True
        assert payload.get("rows_truncated_reason") == "cache_unavailable"
        # And critical safety check: the payload still fits.
        assert len(result_json) < 50_000


# ---------------------------------------------------------------------------
# 4.2 — LLM drill-down tools
# ---------------------------------------------------------------------------


class TestCacheInspectionTools:
    """Day 4.2: get_cached_rows + inspect_cached_result."""

    def _seed(self, monkeypatch, rows, columns, ref="result:t:1"):
        """Install a fresh cache + seed it with one entry, return the ref."""
        from app.services import result_cache as cache_module

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)
        # Round-trip through store() so the ref is stable.
        return cache.store(
            session_id="t",
            query_id="1",
            sql="SELECT 1",
            columns=columns,
            rows=rows,
        )

    @pytest.mark.asyncio
    async def test_get_cached_rows_pagination(self, monkeypatch) -> None:
        from app.services.tools.cache_inspection_tools import get_cached_rows

        rows = [{"i": i, "v": i * 10} for i in range(100)]
        ref = self._seed(monkeypatch, rows, ["i", "v"])

        import json

        result = json.loads(await get_cached_rows(None, rows_ref=ref, offset=0, limit=10))
        assert result["success"] is True
        assert result["total_row_count"] == 100
        assert len(result["rows"]) == 10
        assert result["has_more"] is True

        # Tail page
        result_tail = json.loads(
            await get_cached_rows(None, rows_ref=ref, offset=95, limit=20)
        )
        assert len(result_tail["rows"]) == 5
        assert result_tail["has_more"] is False

    @pytest.mark.asyncio
    async def test_get_cached_rows_caps_limit_at_50(self, monkeypatch) -> None:
        """A runaway LLM asking for limit=999 must be reined in."""
        import json

        from app.services.tools.cache_inspection_tools import (
            MAX_LLM_FETCH_ROWS,
            get_cached_rows,
        )

        rows = [{"i": i} for i in range(500)]
        ref = self._seed(monkeypatch, rows, ["i"])

        result = json.loads(await get_cached_rows(None, rows_ref=ref, limit=999))
        assert len(result["rows"]) == MAX_LLM_FETCH_ROWS
        assert result["limit"] == MAX_LLM_FETCH_ROWS

    @pytest.mark.asyncio
    async def test_get_cached_rows_missing_ref(self, monkeypatch) -> None:
        import json

        from app.services.tools.cache_inspection_tools import get_cached_rows

        # No seed — cache empty.
        from app.services import result_cache as cache_module

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)

        result = json.loads(
            await get_cached_rows(None, rows_ref="result:nope:x")
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_inspect_filter(self, monkeypatch) -> None:
        import json

        from app.services.tools.cache_inspection_tools import inspect_cached_result

        rows = [
            {"state": "IN", "score": 80},
            {"state": "OH", "score": 90},
            {"state": "IN", "score": 60},
            {"state": "CA", "score": 75},
            {"state": "IN", "score": 95},
        ]
        ref = self._seed(monkeypatch, rows, ["state", "score"])

        result = json.loads(
            await inspect_cached_result(
                None,
                rows_ref=ref,
                operation="filter",
                params={"column": "state", "op": "eq", "value": "IN"},
            )
        )
        assert result["success"] is True
        assert result["matched_row_count"] == 3
        assert all(r["state"] == "IN" for r in result["sample"])

    @pytest.mark.asyncio
    async def test_inspect_top_n(self, monkeypatch) -> None:
        import json

        from app.services.tools.cache_inspection_tools import inspect_cached_result

        rows = [{"id": i, "score": (i * 7) % 13} for i in range(20)]
        ref = self._seed(monkeypatch, rows, ["id", "score"])

        result = json.loads(
            await inspect_cached_result(
                None,
                rows_ref=ref,
                operation="top_n",
                params={"column": "score", "n": 3, "direction": "desc"},
            )
        )
        assert result["success"] is True
        assert len(result["rows"]) == 3
        # Top entry has the highest score.
        scores = [r["score"] for r in result["rows"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_inspect_describe_numeric(self, monkeypatch) -> None:
        import json

        from app.services.tools.cache_inspection_tools import inspect_cached_result

        rows = [{"v": float(i)} for i in range(1, 11)]  # 1.0 .. 10.0
        ref = self._seed(monkeypatch, rows, ["v"])

        result = json.loads(
            await inspect_cached_result(
                None, rows_ref=ref, operation="describe",
                params={"column": "v"},
            )
        )
        assert result["success"] is True
        assert result["kind"] == "numeric"
        assert result["count"] == 10
        assert result["min"] == 1.0
        assert result["max"] == 10.0
        assert result["mean"] == 5.5
        assert result["median"] == 5.5

    @pytest.mark.asyncio
    async def test_inspect_group_summary_count(self, monkeypatch) -> None:
        import json

        from app.services.tools.cache_inspection_tools import inspect_cached_result

        rows = [
            {"region": "NA", "amt": 10},
            {"region": "NA", "amt": 20},
            {"region": "EU", "amt": 5},
            {"region": "EU", "amt": 15},
            {"region": "EU", "amt": 25},
        ]
        ref = self._seed(monkeypatch, rows, ["region", "amt"])

        result = json.loads(
            await inspect_cached_result(
                None, rows_ref=ref, operation="group_summary",
                params={"group_by": "region", "agg_fn": "sum", "agg_column": "amt"},
            )
        )
        assert result["success"] is True
        groups = {g["region"]: g["sum"] for g in result["groups"]}
        assert groups == {"NA": 30, "EU": 45}
        # Sorted desc by sum
        assert result["groups"][0]["region"] == "EU"

    @pytest.mark.asyncio
    async def test_inspect_count_distinct(self, monkeypatch) -> None:
        import json

        from app.services.tools.cache_inspection_tools import inspect_cached_result

        rows = (
            [{"product": "A"}] * 4
            + [{"product": "B"}] * 7
            + [{"product": "C"}] * 2
        )
        ref = self._seed(monkeypatch, rows, ["product"])

        result = json.loads(
            await inspect_cached_result(
                None, rows_ref=ref, operation="count_distinct",
                params={"column": "product", "top": 5},
            )
        )
        assert result["success"] is True
        assert result["distinct_count"] == 3
        # Top entry is most frequent.
        assert result["top"][0] == {"value": "B", "count": 7}

    @pytest.mark.asyncio
    async def test_inspect_unknown_operation(self, monkeypatch) -> None:
        import json

        from app.services.tools.cache_inspection_tools import inspect_cached_result

        ref = self._seed(monkeypatch, [{"x": 1}], ["x"])
        result = json.loads(
            await inspect_cached_result(
                None, rows_ref=ref, operation="bogus", params={}
            )
        )
        assert result["success"] is False
        assert "unknown operation" in result["error"]


class TestCacheInspectionRegistration:
    """Tools must be registered so the LLM can actually call them."""

    def test_definitions_in_all_tools(self) -> None:
        from app.services.tools.definitions import (
            ALL_TOOLS,
            GET_CACHED_ROWS,
            INSPECT_CACHED_RESULT,
        )

        names = {t.name for t in ALL_TOOLS}
        assert "get_cached_rows" in names
        assert "inspect_cached_result" in names
        assert GET_CACHED_ROWS.parameters["required"] == ["rows_ref"]
        assert "rows_ref" in INSPECT_CACHED_RESULT.parameters["required"]
        assert "operation" in INSPECT_CACHED_RESULT.parameters["required"]

    def test_registered_in_registry_after_register_all(self) -> None:
        from app.services.tools import register_all_tools
        from app.services.tools.registry import ToolRegistry

        register_all_tools()
        assert "get_cached_rows" in ToolRegistry._tools
        assert "inspect_cached_result" in ToolRegistry._tools


# ---------------------------------------------------------------------------
# 4.3 — Frontend fetch + export consistency
# ---------------------------------------------------------------------------


# ``app.api.queries`` pulls in pandas + sqlalchemy + redis transitively.
# In test envs that don't ship those (the local .venv we're running in
# right now), skip the endpoint-handler tests cleanly. The endpoint's
# pagination logic is exercised by TestResultCache.test_get_rows_slice_pagination.
_HAS_QUERIES_MODULE = True
try:
    from app.api import queries as _queries_check  # noqa: F401
except ImportError:
    _HAS_QUERIES_MODULE = False


@pytest.mark.skipif(
    not _HAS_QUERIES_MODULE,
    reason="app.api.queries import requires pandas + sqlalchemy + redis",
)
class TestResultsEndpoint:
    """
    Day 4.3: GET /api/v1/results/{rows_ref} surfaces cached rows for
    the frontend table. Same handle, paginated.
    """

    def test_endpoint_handler_module_exists(self) -> None:
        from app.api import queries

        assert hasattr(queries, "get_cached_query_result")

    @pytest.mark.asyncio
    async def test_endpoint_returns_paginated_slice(self, monkeypatch) -> None:
        from app.api.queries import get_cached_query_result
        from app.services import result_cache as cache_module

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)
        # Bypass session auth — this test covers pagination logic, not auth.
        # validate_request is imported locally inside the handler so patch the source.
        monkeypatch.setattr("app.core.dependencies.validate_request", lambda *a, **kw: None)

        ref = cache.store(
            session_id="s",
            query_id="q",
            sql="SELECT 1",
            columns=["i"],
            rows=[{"i": i} for i in range(150)],
        )

        result = await get_cached_query_result(ref, session_id="s", offset=0, limit=50)
        assert result["total_row_count"] == 150
        assert len(result["rows"]) == 50
        assert result["has_more"] is True
        assert result["columns"] == ["i"]

        page2 = await get_cached_query_result(ref, session_id="s", offset=100, limit=100)
        assert len(page2["rows"]) == 50
        assert page2["has_more"] is False

    @pytest.mark.asyncio
    async def test_endpoint_404_when_missing(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from app.api.queries import get_cached_query_result
        from app.services import result_cache as cache_module

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)

        with pytest.raises(HTTPException) as exc_info:
            await get_cached_query_result("result:ghost:xyz")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Security hotfix regression tests — IDOR + session-delete purge
# ---------------------------------------------------------------------------


_HAS_CHAT_MODULE = True
try:
    from app.api import chat as _chat_check  # noqa: F401
except ImportError:
    _HAS_CHAT_MODULE = False


@pytest.mark.skipif(
    not _HAS_QUERIES_MODULE,
    reason="app.api.queries import requires pandas + sqlalchemy + redis",
)
class TestExportRowsRefOwnershipCheck:
    """
    CRITICAL hotfix regression: ``POST /query/export`` must reject a
    request where the submitted ``rows_ref`` belongs to a session other
    than ``request.session_id``. Previously exploitable — Mallory's
    valid session + CSRF + SQL-hash plus a crafted rows_ref returned
    the victim's data.

    Test exercises the source-level check (string comparison with
    hmac.compare_digest) because the full endpoint test would require
    sqlalchemy + pandas (env-skipped elsewhere). A live integration
    test belongs in tests/integration/api with the proper fixtures.
    """

    def test_source_contains_ownership_guard(self) -> None:
        import inspect

        from app.api import queries as queries_module

        src = inspect.getsource(queries_module)
        # The guard must check the rows_ref prefix against the
        # caller's session_id. Look for both the exception shape and
        # the hmac.compare_digest call.
        assert "EXPORT_ROWS_REF_OWNERSHIP_MISMATCH" in src, (
            "Export endpoint must emit a security event when a caller "
            "submits a rows_ref belonging to a different session."
        )
        assert "compare_digest" in src, (
            "Ownership check must use hmac.compare_digest to avoid "
            "length-leak side channels on the prefix comparison."
        )


@pytest.mark.skipif(
    not _HAS_QUERIES_MODULE,
    reason="app.api.queries import requires pandas + sqlalchemy + redis",
)
class TestResultsEndpointRequiresSessionAuth:
    """
    CRITICAL hotfix regression: ``GET /api/v1/results/{rows_ref}`` now
    requires ``session_id`` as a query parameter AND verifies the
    rows_ref prefix matches via hmac.compare_digest. Previously had
    zero auth.
    """

    def test_handler_signature_requires_session_id(self) -> None:
        import inspect

        from app.api import queries as queries_module

        sig = inspect.signature(queries_module.get_cached_query_result)
        assert "session_id" in sig.parameters, (
            "GET /results/{rows_ref} must require session_id param"
        )

    def test_handler_validates_session_and_prefix(self) -> None:
        """Source-level guard: validate_request() + prefix check live
        in the handler so a future refactor can't accidentally drop
        either."""
        import inspect

        from app.api import queries as queries_module

        src = inspect.getsource(queries_module.get_cached_query_result)
        # Rate-limited via validate_request with a named action.
        assert "validate_request" in src
        assert 'rate_limit_action="results_read"' in src
        # Prefix comparison present.
        assert "compare_digest" in src
        assert "RESULTS_FETCH_FOREIGN_ROWS_REF" in src


@pytest.mark.skipif(
    not _HAS_CHAT_MODULE,
    reason="app.api.sessions import requires pandas + sqlalchemy (via chat)",
)
class TestSessionDeletePurgesResultCache:
    """
    CRITICAL hotfix regression: deleting a session must purge any
    cached query results keyed under that session so rows don't
    survive for up to 30 min past logout.
    """

    @pytest.mark.asyncio
    async def test_session_delete_calls_result_cache_purge(
        self, monkeypatch
    ) -> None:
        """
        Seed 3 cache entries for session S, invoke the DELETE handler
        directly, assert all entries are gone.
        """
        from app.services import result_cache as cache_module

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)

        # Seed 3 entries for session S and 1 for a different session.
        for i in range(3):
            cache.store(
                session_id="S",
                query_id=f"q{i}",
                sql="",
                columns=[],
                rows=[],
            )
        cache.store(
            session_id="other",
            query_id="q0",
            sql="",
            columns=[],
            rows=[],
        )

        # Stub out session_store, security services, audit logger so
        # the handler doesn't fail on missing deps.
        from app.api import sessions as sessions_module

        class FakeStore:
            def delete(self, sid):
                return True

        class FakeSecurity:
            def cleanup_session(self, sid):
                pass

        class FakeCSRF:
            def cleanup_session(self, sid):
                pass

        class FakeAudit:
            @staticmethod
            def log_session_event(sid, event):
                pass

        monkeypatch.setattr(sessions_module, "session_store", FakeStore())
        monkeypatch.setattr(sessions_module, "csrf_protection", FakeCSRF())
        monkeypatch.setattr(sessions_module, "AuditLogger", FakeAudit)
        # security module is imported inside the handler — patch it there.
        import app.services.security as security_module

        monkeypatch.setattr(security_module, "sql_integrity", FakeSecurity())
        monkeypatch.setattr(security_module, "rate_limiter", FakeSecurity())

        await sessions_module.delete_session("S")

        # Session S entries purged; other session untouched.
        assert cache.get("result:S:q0") is None
        assert cache.get("result:S:q1") is None
        assert cache.get("result:S:q2") is None
        assert cache.get("result:other:q0") is not None


@pytest.mark.skipif(
    not _HAS_CHAT_MODULE,
    reason="app.api.chat import requires pandas + sqlalchemy",
)
class TestChatSummaryExposesRowsField:
    """
    E2E audit BLOCKER regression: chat.py ``result_summary`` must
    emit a ``rows`` key (not just ``sample_rows``) so the frontend's
    ResultsExpander can render the preview immediately before the
    lazy-fetch completes. Previously the frontend got
    ``sample_rows`` only and the table body stayed empty until the
    cache fetch returned (which broke entirely when the cache write
    had failed).
    """

    def test_both_rows_and_sample_rows_present(self) -> None:
        import inspect

        from app.api import chat as chat_module

        src = inspect.getsource(chat_module)
        # Count occurrences of the preview key pair. 4 build sites
        # (non-streaming raw + result, streaming raw + result), so
        # expect 4+ of each after the hotfix.
        rows_count = src.count('"rows": execution_result.get("rows"')
        sample_count = src.count('"sample_rows": execution_result.get("rows"')
        assert rows_count >= 4, (
            f"Expected all 4 result-summary build sites to include "
            f"``rows`` for the frontend's live-render path; found "
            f"{rows_count}"
        )
        assert sample_count >= 4, (
            f"Expected ``sample_rows`` alias kept for backward compat "
            f"with older clients; found {sample_count}"
        )


class TestAnalysisSummaryDoesNotPromiseEmptyInsights:
    """
    UX regression: ``_generate_analysis_summary`` used to always end
    with "See insights below for detailed analysis." even when the
    insights array was empty. Users saw the promise and nothing
    below. Now the template adapts: insights present → direct the
    user there; insights empty → narrate from statistics / quality /
    chart; nothing at all → say so honestly.
    """

    def test_empty_insights_falls_back_to_statistics_narrative(self) -> None:
        from app.services.react_agent import _generate_analysis_summary

        summary = _generate_analysis_summary(
            {
                "row_count": 556,
                "columns": ["a", "b", "c", "d", "e", "f", "g", "h"],
                "insights": [],
                "statistics": {
                    "revenue": {"mean": 120.5, "min": 10, "max": 500},
                },
                "quality": {"overall_score": 95},
                "chart": {"recommended_chart": "bar"},
            }
        )
        assert "556 results" in summary
        # Must NOT promise non-existent insights:
        assert "See insights below" not in summary
        # Must SUBSTITUTE descriptive narrative from whatever is available:
        assert "revenue" in summary
        assert "120" in summary  # mean
        assert "bar" in summary  # chart

    def test_empty_everything_says_so_honestly(self) -> None:
        from app.services.react_agent import _generate_analysis_summary

        summary = _generate_analysis_summary(
            {
                "row_count": 12,
                "columns": ["uniform_col"],
                "insights": [],
                "statistics": {},
                "quality": {},
                "chart": None,
            }
        )
        assert "12 results" in summary
        assert "See insights below" not in summary
        # Honest fallback — tells the user no patterns were found.
        assert "uniform" in summary.lower() or "no notable patterns" in summary.lower()

    def test_fallback_describes_up_to_three_columns(self) -> None:
        """
        Richer narrative: when insights empty, describe top 3 numeric
        columns so the user gets actual detail from a 9-column
        aggregated query rather than one bland sentence.
        """
        from app.services.react_agent import _generate_analysis_summary

        summary = _generate_analysis_summary(
            {
                "row_count": 5000,
                "columns": list("abcdefghi"),
                "insights": [],
                "statistics": {
                    "premium_amount": {"mean": 2748.04, "min": 500, "max": 5000},
                    "claim_count": {"mean": 1.2, "min": 0, "max": 15},
                    "policy_age_years": {"mean": 4.5, "min": 1, "max": 30},
                    "risk_score": {"mean": 72, "min": 10, "max": 100},
                },
                "quality": {"overall_score": 98},
                "chart": {"recommended_chart": "horizontal_bar"},
            }
        )
        # All three top columns mentioned:
        assert "premium_amount" in summary
        assert "claim_count" in summary
        assert "policy_age_years" in summary
        # Fourth one NOT mentioned (we cap at 3):
        assert "risk_score" not in summary

    def test_headline_uses_llm_business_insight_when_present(self) -> None:
        """
        Talk-to-your-data Step 3: when the LLM produced a
        business_insight, the summary must LEAD with its title +
        description, not the template. The template is fallback only.
        """
        from app.services.react_agent import _generate_analysis_summary

        summary = _generate_analysis_summary(
            {
                "row_count": 5000,
                "columns": ["region", "premium"],
                "insights": [
                    {
                        "type": "business_insight",
                        "severity": "high",
                        "title": "NA region drives 62% of premium",
                        "description": (
                            "North America contributes $12.4M of the "
                            "$20M total premium — 62% concentration. "
                            "The next region (EU) is less than half."
                        ),
                        "recommendations": ["Assess NA dependency risk"],
                    },
                    {
                        "type": "business_insight",
                        "severity": "medium",
                        "title": "Claim ratio elevated in LATAM",
                        "description": "LATAM shows 1.8x the median claim ratio.",
                    },
                    {"type": "concentration", "severity": "medium", "title": "X"},
                ],
                "statistics": {"premium": {"mean": 2748, "min": 500, "max": 12400}},
                "quality": {"overall_score": 96},
                "chart": None,
            }
        )
        # Headline = highest-severity LLM finding:
        assert "NA region drives 62%" in summary
        # Followed by its description:
        assert "12.4M" in summary or "62%" in summary
        # Tail mentions remaining insights:
        assert "1 more business insight(s)" in summary
        assert "1 statistical finding(s)" in summary
        # NOT the generic template:
        assert "See insights below for detailed analysis" not in summary


class TestChatResponseCarriesStructuredInsights:
    """
    Mission-critical: the LLM's structured business_insight output
    (title / severity / description / recommendations / metrics) must
    reach the frontend's InsightCard. Previously the analyst path
    flattened insights to string-only ``key_findings`` and dropped
    the structured shape entirely, so the rich card component
    received an empty array even when the LLM produced perfect
    narrative.
    """

    def test_chatresponse_schema_has_insights_field(self) -> None:
        from app.models.chat_models import ChatResponse

        fields = ChatResponse.model_fields
        assert "insights" in fields, (
            "ChatResponse must carry structured insights for the "
            "InsightCard renderer — key_findings (strings) alone "
            "loses title/severity/recommendations."
        )
        # Default empty so non-analyst paths are unaffected.
        resp = ChatResponse(mode="analyst")
        assert resp.insights == []

    def test_chatresponse_round_trips_llm_insight_shape(self) -> None:
        from app.models.chat_models import ChatResponse

        sample = [
            {
                "type": "business_insight",
                "severity": "high",
                "title": "NA drives 62% of premium",
                "description": "North America contributes $12.4M of $20M total…",
                "recommendations": ["Audit NA pipeline", "Check EU gap"],
                "column_name": "_llm_0",
            },
            {
                "type": "concentration",
                "severity": "medium",
                "title": "Top 3 agents = 48% of policies",
                "description": "Three agents hold 48% …",
                "column_name": "agent_id",
            },
        ]
        resp = ChatResponse(mode="analyst", insights=sample)
        # Full round-trip — title/severity/recommendations preserved.
        serialised = resp.model_dump()
        assert len(serialised["insights"]) == 2
        assert serialised["insights"][0]["title"] == "NA drives 62% of premium"
        assert serialised["insights"][0]["recommendations"] == [
            "Audit NA pipeline",
            "Check EU gap",
        ]


class TestAnalysisDigestBuilder:
    """
    Talk-to-your-data Step 1: the LLM narrator never sees raw rows.
    It sees a ``_build_analysis_digest`` output — stats + top/bottom
    exemplars + categorical frequencies — ~3-5KB regardless of the
    row count. This replaces the hardcoded 100-row skip gate that
    silently disabled business insights on analytical workloads.
    """

    def test_digest_size_bounded_by_columns_not_rows(self) -> None:
        from app.services.tools.query_tools import _build_analysis_digest

        # Build 10,000 wide rows — this is what the 100-row cap
        # previously rejected outright.
        rows = [
            {
                "region": f"R{i % 5}",
                "amount": 100 + i,
                "score": 50 + (i % 50),
            }
            for i in range(10000)
        ]
        statistics = {
            "amount": {"min": 100, "max": 10099, "mean": 5099.5, "median": 5099},
            "score": {"min": 50, "max": 99, "mean": 74.5, "median": 74},
        }

        digest = _build_analysis_digest(
            rows=rows,
            columns=["region", "amount", "score"],
            sql="SELECT region, amount, score FROM t",
            statistics=statistics,
            quality={"overall_score": 92},
            aggregated=False,
            existing_insights=[],
        )

        # Shape + contents:
        assert digest["row_count"] == 10000
        assert digest["column_count"] == 3
        assert digest["quality_score"] == 92
        assert "amount" in digest["numeric_exemplars"]
        # Top-5 + bottom-5 exemplars, not 10,000 rows:
        assert len(digest["numeric_exemplars"]["amount"]["lowest_5"]) == 5
        assert len(digest["numeric_exemplars"]["amount"]["highest_5"]) == 5
        # Categorical top-10:
        assert "region" in digest["categorical_top"]
        # Size bounded — the whole point of the digest.
        import json

        serialised = json.dumps(digest, default=str)
        assert len(serialised) < 10_000, (
            f"Digest ballooned to {len(serialised)} bytes; must stay "
            f"<10KB regardless of row count (O(columns), not O(rows))"
        )

    def test_digest_carries_detector_findings_trimmed(self) -> None:
        from app.services.tools.query_tools import _build_analysis_digest

        existing = [
            {
                "type": "concentration",
                "severity": "high",
                "title": "Top 20% = 80% of revenue",
                "column_name": "revenue",
                "description": "a" * 500,  # over trim limit
            },
        ]
        digest = _build_analysis_digest(
            rows=[{"revenue": 100}],
            columns=["revenue"],
            sql="SELECT revenue FROM t",
            statistics={"revenue": {"min": 100, "max": 100, "mean": 100}},
            quality={},
            aggregated=False,
            existing_insights=existing,
        )
        assert len(digest["detector_findings"]) == 1
        # Description trimmed to <=280 chars.
        assert len(digest["detector_findings"][0]["description"]) <= 280


class TestExecuteAndAnalyzeAcceptsQuestion:
    """
    Talk-to-your-data Step 2: the LLM narrator needs the user's
    original question to answer it directly. ``execute_and_analyze``
    now takes an optional ``question`` parameter the LLM passes
    verbatim from the agent state.
    """

    @pytest.mark.asyncio
    async def test_question_reaches_enhance_insights(self, monkeypatch) -> None:
        from app.services import result_cache as cache_module
        from app.services.tools import query_tools

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)

        async def fake_execute_query(**kwargs):
            return {
                "rows": [{"region": "NA", "total": 100}],
                "columns": ["region", "total"],
                "execution_time_ms": 1,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.services.database_service.DatabaseService.execute_query",
            fake_execute_query,
        )

        captured = {}

        async def fake_enhance(
            context, rows, columns, sql, statistics, existing_insights,
            question=None, quality=None, aggregated=False,
        ):
            captured["question"] = question
            captured["quality"] = quality
            captured["aggregated"] = aggregated
            return existing_insights

        monkeypatch.setattr(query_tools, "enhance_insights_with_llm", fake_enhance)

        class FakeContext:
            session_id = "qtest"
            db_config = {
                "db_type": "postgresql",
                "connection_url": "postgresql://x",
                "db_name": "t",
            }

        await query_tools.execute_and_analyze(
            context=FakeContext(),
            sql="SELECT region, SUM(amount) total FROM t GROUP BY region",
            limit=100,
            question="Which regions lead in total premium?",
        )

        assert captured["question"] == "Which regions lead in total premium?"
        # Quality + aggregated forwarded as well.
        assert captured["quality"] is not None
        assert captured["aggregated"] is True


    def test_insights_present_keeps_see_insights_link(self) -> None:
        """
        Step 3 update: when an LLM business_insight is present, the
        summary now LEADS with its narrative text instead of
        saying "See insights below". Counts move to a tail clause.
        """
        from app.services.react_agent import _generate_analysis_summary

        summary = _generate_analysis_summary(
            {
                "row_count": 100,
                "columns": ["x"],
                "insights": [
                    {
                        "type": "business_insight",
                        "severity": "high",
                        "title": "Top 3 = 60% of total",
                        "description": "top 3 = 60%",
                    },
                    {"type": "concentration", "description": "Pareto"},
                ],
                "statistics": {},
                "quality": {},
                "chart": None,
            }
        )
        # Headline is the LLM finding:
        assert "Top 3 = 60%" in summary
        # Count of remaining statistical findings in the tail:
        assert "statistical finding(s)" in summary
        # Template's "See insights below" is NOT used when we have an LLM headline:
        assert "See insights below" not in summary


class TestExportRequestSchemaSupportsRowsRef:
    """
    Day 4.3: ExecuteQueryRequest carries the optional ``rows_ref`` so
    the frontend can ask the export endpoint to source from the cache
    instead of re-running the SQL — the fix for the "summary says 200
    / export gives 9000" drift.
    """

    def test_field_present_and_optional(self) -> None:
        from app.models.schemas import ExecuteQueryRequest

        # No rows_ref — still valid (legacy path)
        req = ExecuteQueryRequest(
            session_id="s", sql_query="SELECT 1", limit=100
        )
        assert req.rows_ref is None

        # With rows_ref — round-trips
        req2 = ExecuteQueryRequest(
            session_id="s",
            sql_query="SELECT 1",
            limit=100,
            rows_ref="result:s:abc",
        )
        assert req2.rows_ref == "result:s:abc"


# ---------------------------------------------------------------------------
# Audit-driven wiring fixes — must stay green or Phase 4 regresses end-to-end
# ---------------------------------------------------------------------------


class TestCacheToolsWrappedInLangGraph:
    """
    Phase 4 audit BLOCKER: get_cached_rows / inspect_cached_result are
    registered in ToolRegistry but were initially never wrapped as
    StructuredTool in build_tools(). Without these wrappers the LangGraph
    agent has no binding for them and the LLM physically cannot call
    them. This test guards against re-introducing that gap.
    """

    def test_create_langchain_tools_includes_cache_tools(self) -> None:
        from langchain_core.tools import StructuredTool

        from app.services.react_agent import create_langchain_tools
        from app.services.tools.registry import ToolContext

        ctx = ToolContext(session_id="t")
        wrapped = create_langchain_tools(ctx)

        names = {
            t.name for t in wrapped if isinstance(t, StructuredTool)
        }
        assert "get_cached_rows" in names, (
            "Phase 4.2 regression: get_cached_rows not bound to LangGraph"
        )
        assert "inspect_cached_result" in names, (
            "Phase 4.2 regression: inspect_cached_result not bound to LangGraph"
        )


class TestSystemPromptAdvertisesCacheTools:
    """
    Phase 4 audit HIGH: SYSTEM_PROMPT must mention the cache tools so
    the LLM knows to use them for follow-up questions. Without this
    even the wrapped tools sit idle.
    """

    def test_prompt_mentions_get_cached_rows(self) -> None:
        from app.services.react_agent import SYSTEM_PROMPT

        assert "get_cached_rows" in SYSTEM_PROMPT

    def test_prompt_mentions_inspect_cached_result(self) -> None:
        from app.services.react_agent import SYSTEM_PROMPT

        assert "inspect_cached_result" in SYSTEM_PROMPT

    def test_prompt_explains_followup_routing(self) -> None:
        """
        Specific instruction telling the LLM to route follow-ups to the
        cache tools instead of re-running execute_and_analyze / SQL.
        """
        from app.services.react_agent import SYSTEM_PROMPT

        # Loose check — any of these signal the routing rule is present.
        assert any(
            phrase in SYSTEM_PROMPT
            for phrase in (
                "follow-up",
                "those results",
                "previous query",
                "ROUTING RULE",
            )
        )


class TestExecuteAndAnalyzeDescriptionMentionsRowsRef:
    """Phase 4 audit HIGH: tool description must surface rows_ref."""

    def test_description_mentions_rows_ref(self) -> None:
        from app.services.tools.definitions import EXECUTE_AND_ANALYZE

        assert "rows_ref" in EXECUTE_AND_ANALYZE.description, (
            "execute_and_analyze description must tell the LLM about "
            "the rows_ref handle so it knows to chain into cache tools"
        )


class TestNonFiniteFloatsScrubbedFromCache:
    """
    Phase 4 audit HIGH: NaN / Inf cells in cached rows historically
    blew the frontend's JSON.parse with SyntaxError. Cache writer now
    scrubs them to None at serialization time.
    """

    def test_nan_in_row_becomes_null(self, monkeypatch) -> None:
        import math

        from app.services import result_cache as cache_module
        from app.services.result_cache import CachedResult

        cr = CachedResult(
            rows_ref="result:s:t",
            session_id="s",
            query_id="t",
            sql="",
            columns=["x", "y"],
            rows=[
                {"x": 1.0, "y": math.nan},
                {"x": math.inf, "y": -math.inf},
                {"x": 3.0, "y": 4.0},
            ],
            row_count=3,
        )
        raw = cr.to_json().decode()
        # Critical: no bare NaN / Infinity tokens; JSON.parse-safe.
        assert "NaN" not in raw
        assert "Infinity" not in raw
        # Round-trip: NaN/Inf became null
        round_tripped = CachedResult.from_json(cr.to_json())
        assert round_tripped.rows[0]["y"] is None
        assert round_tripped.rows[1]["x"] is None
        assert round_tripped.rows[1]["y"] is None
        assert round_tripped.rows[2]["x"] == 3.0


class TestPreviousResultReturnsRowsRef:
    """
    Phase 4 audit HIGH: get_previous_result must return rows_ref so
    the LLM can chain into inspect_cached_result for the FULL row set
    instead of being stuck with a 10-row sample.
    """

    @pytest.mark.asyncio
    async def test_response_includes_rows_ref_and_hint(
        self, monkeypatch
    ) -> None:
        import json

        from app.services.tools import conversation_tools
        from app.services.tools.registry import ToolContext

        # Stub the session store to return a cached result with rows_ref
        class FakeStore:
            def get_cached_result(self, session_id, ref):
                return {
                    "columns": ["x"],
                    "rows": [{"x": i} for i in range(5)],
                    "row_count": 9000,
                    "sql": "SELECT x FROM t",
                    "rows_ref": "result:abc:def",
                }

        monkeypatch.setattr(
            conversation_tools, "session_store", FakeStore()
        )

        out = await conversation_tools.get_previous_result(
            ToolContext(session_id="abc"), query_reference="last"
        )
        payload = json.loads(out)
        assert payload["rows_ref"] == "result:abc:def"
        assert "next_step_hint" in payload
        assert "inspect_cached_result" in payload["next_step_hint"]


class TestLLMInsightsHaveColumnName:
    """
    Cross-phase audit HIGH: dedup keys insights by (type, column_name).
    LLM insights have no natural column → all collapse under
    ("business_insight", "") unless we stamp them. Phase 4 hardening
    adds a per-insight sentinel column_name.
    """

    def test_aggregated_flag_threads_through_all_engines(self) -> None:
        """
        Cross-phase audit HIGH: aggregated flag must reach
        compute_statistics + assess_data_quality + recommend_chart,
        not just detect_insights. Otherwise group-aggregated rows get
        Pareto/Gini/HHI metrics labelled as if they were row-level.
        """
        from app.services.analysis_engines.chart_intelligence import (
            recommend_chart,
        )
        from app.services.analysis_engines.data_quality import (
            assess_data_quality,
        )
        from app.services.analysis_engines.statistics import (
            compute_statistics,
        )

        rows = [{"region": f"R{i}", "total": (i + 1) * 100} for i in range(8)]

        # Statistics: aggregated=True must suppress concentration block.
        agg_stats = compute_statistics(rows, aggregated=True)
        for col_stats in agg_stats.values():
            assert col_stats.get("concentration") is None
            assert col_stats.get("concentration_skipped_reason") == "aggregated_mode"

        raw_stats = compute_statistics(rows, aggregated=False)
        # Concentration must be present in raw mode as before.
        for col_stats in raw_stats.values():
            assert col_stats.get("concentration") is not None

        # Data quality: aggregated_mode echoed in response.
        agg_quality = assess_data_quality(rows, aggregated=True)
        assert agg_quality.get("aggregated_mode") is True
        raw_quality = assess_data_quality(rows, aggregated=False)
        assert raw_quality.get("aggregated_mode") is False

        # Chart recommender: aggregated_mode echoed in response.
        agg_chart = recommend_chart(rows, aggregated=True)
        assert agg_chart.get("aggregated_mode") is True
        raw_chart = recommend_chart(rows, aggregated=False)
        assert raw_chart.get("aggregated_mode") is False


class TestProgressEventsDuringAnalysis:
    """
    Cross-phase audit HIGH: execute_and_analyze must call
    ToolContext.progress_emitter at staged points so multi-second
    analysis on big datasets doesn't look like a hang.
    """

    @pytest.mark.asyncio
    async def test_emitter_called_at_each_stage(self, monkeypatch) -> None:
        from app.services import result_cache as cache_module
        from app.services.tools import query_tools

        cache_module.ResultCache._instance = None
        cache = cache_module.ResultCache()
        cache.redis_client = None
        cache._memory_store.clear()
        monkeypatch.setattr(cache_module, "result_cache", cache)

        async def fake_execute_query(**kwargs):
            return {
                "rows": [{"i": i, "v": i * 10} for i in range(50)],
                "columns": ["i", "v"],
                "execution_time_ms": 5,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.services.database_service.DatabaseService.execute_query",
            fake_execute_query,
        )

        captured: list = []

        class FakeContext:
            session_id = "progress-test"
            db_config = {
                "db_type": "postgresql",
                "connection_url": "postgresql://x",
                "db_name": "t",
            }
            progress_emitter = staticmethod(lambda payload: captured.append(payload))

        await query_tools.execute_and_analyze(
            context=FakeContext(),
            sql="SELECT * FROM t",
            limit=100,
        )

        # Expect at least: starting + insights + stats + quality + chart.
        stages = [p.get("stage") for p in captured]
        assert "analysis_starting" in stages
        assert "insights_detected" in stages
        assert "statistics_computed" in stages
        assert "quality_assessed" in stages
        assert "chart_recommended" in stages
        # All percent values should be in [0, 100]
        for p in captured:
            assert 0.0 <= p.get("percent", -1) <= 100.0


    def test_query_tools_stamps_column_name_on_llm_insights(self) -> None:
        """
        Source-level guard: the enhance step must stamp a unique
        column_name sentinel on every LLM insight before prepending,
        otherwise Phase 1 Day 2b dedup collapses them all to one entry.
        """
        import inspect

        from app.services.tools import query_tools

        src = inspect.getsource(query_tools)
        # The stamping loop introduced by Phase 4 hardening.
        assert '"_llm_' in src or "f\"_llm_{idx}\"" in src, (
            "enhance_insights_with_llm must stamp a per-insight "
            "column_name (e.g. '_llm_{idx}') so dedup doesn't "
            "collapse distinct LLM findings"
        )
