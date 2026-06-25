"""
Phase 3b reliability fix regression tests (Async Executors).

Scope of this file:
  - 3b.1 — AsyncExecutorProtocol + registry + pool routing hook
  - 3b.2 — query_progress SSE event plumbing

Driver integration (3b.3 BigQuery, 3b.4 Snowflake) requires real
credentials and lives in ``tests/integration/`` with appropriate skip
markers; not duplicated here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest


# ---------------------------------------------------------------------------
# 3b.1 — AsyncExecutorProtocol + registry
# ---------------------------------------------------------------------------


class TestAsyncExecutorProtocol:
    """Protocol/ABC describing native-async query executors."""

    def test_protocol_module_exists(self) -> None:
        from app.services import async_executor_protocol as aep

        assert hasattr(aep, "AsyncExecutorProtocol")
        assert hasattr(aep, "QueryHandle")
        assert hasattr(aep, "AsyncExecutorRegistry")

    def test_query_handle_shape(self) -> None:
        from app.services.async_executor_protocol import QueryHandle

        h = QueryHandle(query_id="job-abc", db_type="bigquery")
        assert h.query_id == "job-abc"
        assert h.db_type == "bigquery"

    def test_registry_register_and_lookup(self) -> None:
        """Registering a driver makes is_async_native(db_type) true."""
        from app.services.async_executor_protocol import AsyncExecutorRegistry

        registry = AsyncExecutorRegistry()
        assert registry.is_async_native("mydb-test") is False

        def fake_factory(config):
            class FakeExec:
                pass
            return FakeExec()

        registry.register("mydb-test", fake_factory)
        try:
            assert registry.is_async_native("mydb-test") is True
            assert registry.get_factory("mydb-test") is fake_factory
        finally:
            registry.unregister("mydb-test")

        assert registry.is_async_native("mydb-test") is False

    def test_registry_is_case_insensitive(self) -> None:
        from app.services.async_executor_protocol import AsyncExecutorRegistry

        registry = AsyncExecutorRegistry()
        registry.register("BigQuery", lambda c: None)
        try:
            assert registry.is_async_native("bigquery") is True
            assert registry.is_async_native("BIGQUERY") is True
        finally:
            registry.unregister("BigQuery")

    @pytest.mark.asyncio
    async def test_abstract_methods_enforced(self) -> None:
        """
        Instantiating a subclass without implementing all abstract methods
        must raise TypeError.
        """
        from app.services.async_executor_protocol import (
            AsyncExecutorProtocol,
        )

        # Missing implementations → TypeError at instantiation.
        class PartialExecutor(AsyncExecutorProtocol):
            async def start_query(self, sql, **kwargs):
                return None

            # Intentionally missing: poll_status, fetch_results, cancel, get_progress

        with pytest.raises(TypeError):
            PartialExecutor()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_full_implementation_instantiates(self) -> None:
        """A complete subclass works end-to-end with the protocol contract."""
        from app.services.async_executor_protocol import (
            AsyncExecutorProtocol,
            QueryHandle,
        )

        class FakeExec(AsyncExecutorProtocol):
            async def start_query(self, sql: str, **kwargs) -> QueryHandle:
                return QueryHandle(query_id="q-1", db_type="fake")

            async def poll_status(self, handle: QueryHandle) -> str:
                return "complete"

            async def fetch_results(
                self, handle: QueryHandle, limit: Optional[int] = None
            ) -> Dict[str, Any]:
                return {"rows": [], "columns": [], "row_count": 0}

            async def cancel(self, handle: QueryHandle) -> bool:
                return True

            async def get_progress(
                self, handle: QueryHandle
            ) -> Optional[Dict[str, Any]]:
                return {"bytes_scanned": 1024}

        exec_ = FakeExec()
        handle = await exec_.start_query("SELECT 1")
        assert handle.query_id == "q-1"
        assert await exec_.poll_status(handle) == "complete"
        assert (await exec_.fetch_results(handle))["row_count"] == 0
        assert await exec_.cancel(handle) is True
        progress = await exec_.get_progress(handle)
        assert progress == {"bytes_scanned": 1024}


class TestPoolManagerAsyncNativeHook:
    """
    Pool manager exposes ``is_async_native_db(db_type)`` that checks the
    registry. No routing change yet — 3b.3/3b.4 will flip routing when
    concrete drivers register themselves.
    """

    def test_helper_present(self) -> None:
        from app.services import connection_pool_manager as cpm

        assert hasattr(cpm, "is_async_native_db"), (
            "connection_pool_manager must expose is_async_native_db()"
        )

    def test_unknown_db_is_not_async_native(self) -> None:
        from app.services.connection_pool_manager import is_async_native_db

        assert is_async_native_db("postgresql") is False
        assert is_async_native_db("zzz") is False

    def test_registered_driver_flips_helper(self) -> None:
        from app.services.async_executor_protocol import async_executor_registry
        from app.services.connection_pool_manager import is_async_native_db

        async_executor_registry.register("phase3b-test-db", lambda c: None)
        try:
            assert is_async_native_db("phase3b-test-db") is True
        finally:
            async_executor_registry.unregister("phase3b-test-db")


# ---------------------------------------------------------------------------
# 3b.2 — query_progress SSE event plumbing
# ---------------------------------------------------------------------------


class TestQueryProgressEventPlumbing:
    """
    The SSE event shape and the ToolContext hook that executors use to
    emit progress updates. Driver-side wiring (actual emissions from
    BigQuery/Snowflake) is 3b.3/3b.4.
    """

    def test_feature_flag_exists(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "FIX_QUERY_PROGRESS_EVENTS")
        assert settings.FIX_QUERY_PROGRESS_EVENTS is True

    def test_tool_context_has_progress_emitter_slot(self) -> None:
        from app.services.tools.registry import ToolContext

        ctx = ToolContext(session_id="s1")
        assert hasattr(ctx, "progress_emitter"), (
            "ToolContext must expose a progress_emitter slot for "
            "executors to publish query_progress events"
        )
        assert ctx.progress_emitter is None  # Not wired by default

    def test_progress_event_builder(self) -> None:
        from app.services.react_agent import _query_progress_event

        evt = _query_progress_event(
            elapsed_ms=12345,
            bytes_scanned=2 * 1024 * 1024,
            rows_read=1000,
            percent=37.5,
        )
        assert evt["event"] == "query_progress"
        assert evt["elapsed_ms"] == 12345
        assert evt["bytes_scanned"] == 2 * 1024 * 1024
        assert evt["rows_read"] == 1000
        assert evt["percent"] == 37.5

    def test_progress_event_omits_absent_fields(self) -> None:
        """Optional fields (bytes_scanned, rows_read, percent) shouldn't
        show up as None in the payload — some drivers only provide a
        subset and the UI shouldn't have to guard every field."""
        from app.services.react_agent import _query_progress_event

        evt = _query_progress_event(elapsed_ms=500)
        assert evt == {"event": "query_progress", "elapsed_ms": 500}


# ---------------------------------------------------------------------------
# Step 1b — mock long-running query helpers
# ---------------------------------------------------------------------------


class TestMockAsyncExecutor:
    """
    The mock executor used by Phase 3b driver-layer tests. Validates the
    AsyncExecutorProtocol contract against the mock so Phase 3b.3/3b.4
    real drivers have a confidence baseline.
    """

    @pytest.mark.asyncio
    async def test_happy_path_lifecycle(self) -> None:
        from tests.utils.mock_long_running_query import make_happy_path_executor

        exec_ = make_happy_path_executor(row_count=5)
        handle = await exec_.start_query("SELECT * FROM t")
        assert handle.db_type == "mock-bigquery"

        # Walk the status machine to completion.
        for _ in range(50):
            status = await exec_.poll_status(handle)
            if status == "complete":
                break
            import asyncio
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("Mock executor never reached 'complete'")

        result = await exec_.fetch_results(handle)
        assert result["row_count"] == 5
        assert result["columns"] == ["id", "value"]

    @pytest.mark.asyncio
    async def test_fetch_before_complete_raises(self) -> None:
        from tests.utils.mock_long_running_query import MockAsyncExecutor

        exec_ = MockAsyncExecutor(run_duration_s=1.0, result_columns=["x"])
        handle = await exec_.start_query("SELECT 1")
        with pytest.raises(RuntimeError, match="status="):
            await exec_.fetch_results(handle)
        # Cleanup so the background task doesn't leak
        await exec_.cancel(handle)

    @pytest.mark.asyncio
    async def test_cancel_transitions_to_cancelled(self) -> None:
        import asyncio

        from tests.utils.mock_long_running_query import MockAsyncExecutor

        exec_ = MockAsyncExecutor(
            run_duration_s=1.0,
            cancel_on_request=True,
        )
        handle = await exec_.start_query("SELECT 1")
        await asyncio.sleep(0.02)
        ok = await exec_.cancel(handle)
        assert ok is True
        assert await exec_.poll_status(handle) == "cancelled"

    @pytest.mark.asyncio
    async def test_progress_emitter_is_called(self) -> None:
        import asyncio

        from tests.utils.mock_long_running_query import MockAsyncExecutor

        seen: list = []

        def emitter(payload: dict) -> None:
            seen.append(payload)

        exec_ = MockAsyncExecutor(
            run_duration_s=0.15,
            progress_interval_s=0.05,
            progress_sequence=[
                {"bytes_scanned": 100},
                {"bytes_scanned": 200},
                {"bytes_scanned": 300},
            ],
        )
        handle = await exec_.start_query("SELECT 1", progress_emitter=emitter)
        # Wait for the simulated run to finish naturally.
        for _ in range(50):
            if await exec_.poll_status(handle) == "complete":
                break
            await asyncio.sleep(0.01)

        assert seen, "Mock executor did not call the progress emitter"
        assert any("bytes_scanned" in p for p in seen)

    @pytest.mark.asyncio
    async def test_failure_transition(self) -> None:
        import asyncio

        from tests.utils.mock_long_running_query import MockAsyncExecutor

        exec_ = MockAsyncExecutor(
            run_duration_s=0.5,
            fail_after_s=0.02,
        )
        handle = await exec_.start_query("SELECT 1")
        # Wait past the configured fail point
        for _ in range(30):
            status = await exec_.poll_status(handle)
            if status == "failed":
                break
            await asyncio.sleep(0.02)
        assert await exec_.poll_status(handle) == "failed"

    @pytest.mark.asyncio
    async def test_simulate_progress_stream(self) -> None:
        """``simulate_progress_stream`` yields on schedule."""
        from tests.utils.mock_long_running_query import simulate_progress_stream

        events = [
            {"bytes_scanned": 1},
            {"bytes_scanned": 2},
            {"bytes_scanned": 3},
        ]
        received = []
        async for payload in simulate_progress_stream(events, interval_s=0.01):
            received.append(payload)
        assert received == events
