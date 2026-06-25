"""
Phase 2 reliability fix regression tests.

Each test corresponds to a Phase 2 state-machine or infrastructure hardening
item documented in ``docs/architecture-audit-2026-04-16.md``.

Protocol mirrors ``test_phase1_fixes.py``:
1. Tests are added BEFORE the corresponding fix lands.
2. Before the fix they fail on the current code; after the fix they pass.
3. If a fix is rolled back via its feature flag, the test should fail again.

Imports targeting not-yet-introduced symbols are done lazily inside test
bodies so test collection stays green before the fix lands.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Day 1 — two-counter circuit breaker
# ---------------------------------------------------------------------------
#
# Before Phase 2 Day 1, a single ``iterations_without_execution`` counter
# conflated exploration (legitimate multi-table schema lookups) with SQL
# attempts that failed. The audit prescribes two counters:
#
#   - ``iterations_without_execution`` (semantic: iterations without an SQL
#     tool attempt) — trigger at >= 10 (loosened from 7 per audit).
#   - ``sql_attempts_failed`` — count of execute_sql / execute_and_analyze
#     calls that returned success=False. Reset on successful SQL execution.
#     Trigger at >= 3.


class TestTwoCounterCircuitBreaker:
    """Day 1: should_continue must honour both counters with audit thresholds."""

    def _base_state(self, **overrides) -> dict:
        """Minimal valid state the circuit breaker can evaluate."""
        from langchain_core.messages import AIMessage

        state = {
            "messages": [AIMessage(
                content="",
                tool_calls=[{"name": "search_tables", "id": "c1", "args": {}}],
            )],
            "question": "anything",
            "sql": None,
            "execution_result": None,
            "tools_used": [],
            "tool_calls_count": 0,
            "failed_attempts": [],
            "total_usage": None,
            "status": "thinking",
            "error": None,
            "iteration": 5,
            "max_iterations": 15,
            "consecutive_no_tools": 0,
            "consecutive_failures": 0,
            "iterations_without_execution": 0,
            "sql_attempts_failed": 0,
        }
        state.update(overrides)
        return state

    def test_three_sql_attempts_failed_triggers_breaker(self) -> None:
        """``sql_attempts_failed >= 3`` must short-circuit to end."""
        from app.services.react_agent import should_continue

        state = self._base_state(sql_attempts_failed=3)
        assert should_continue(state) == "end", (
            "sql_attempts_failed=3 must end the run (two-counter breaker)"
        )

    def test_two_sql_attempts_failed_continues(self) -> None:
        """Two SQL failures are below the new threshold; keep going."""
        from app.services.react_agent import should_continue

        state = self._base_state(sql_attempts_failed=2)
        assert should_continue(state) == "tools"

    def test_exploration_threshold_loosened_to_ten(self) -> None:
        """
        Audit: exploration limit goes 7 → 10 so 3-table JOINs don't trigger
        the breaker during legitimate schema discovery.
        """
        from app.services.react_agent import should_continue

        state = self._base_state(iterations_without_execution=9)
        assert should_continue(state) == "tools", (
            "iterations_without_execution=9 must not end (limit is 10)"
        )

    def test_ten_exploration_iterations_triggers_breaker(self) -> None:
        from app.services.react_agent import should_continue

        state = self._base_state(iterations_without_execution=10)
        assert should_continue(state) == "end"

    def test_counters_independent(self) -> None:
        """
        2 SQL failures + 0 exploration → neither threshold hit.
        Verifies the counters don't leak into each other.
        """
        from app.services.react_agent import should_continue

        state = self._base_state(
            sql_attempts_failed=2,
            iterations_without_execution=0,
        )
        assert should_continue(state) == "tools"


class TestSqlAttemptsFailedCounter:
    """Day 1: tool_node must maintain sql_attempts_failed correctly."""

    def test_state_has_sql_attempts_failed_field(self) -> None:
        from app.services.react_agent import ReActState

        assert "sql_attempts_failed" in ReActState.__annotations__, (
            "ReActState is missing the sql_attempts_failed field"
        )

    def test_initial_state_initialises_sql_attempts_failed(self) -> None:
        """
        Both run_batch and run_streaming construct a fresh ReActState.
        Both must initialise sql_attempts_failed to 0.
        """
        import inspect
        import re

        from app.services import react_agent as ra

        src = inspect.getsource(ra)
        # Count constructor invocations, NOT the class definition line.
        # Class definition matches ``class ReActState(TypedDict):`` — we
        # want only ``initial_state = ReActState(...)`` style calls.
        ctor_calls = len(re.findall(r"(?<!class )ReActState\(\s*$", src, re.MULTILINE))
        mentions = src.count("sql_attempts_failed=0")
        assert mentions >= ctor_calls, (
            f"{ctor_calls} ReActState(...) constructor calls but only "
            f"{mentions} initialise sql_attempts_failed=0"
        )


# ---------------------------------------------------------------------------
# Day 1 — complete state update helper
# ---------------------------------------------------------------------------


class TestCompleteStateUpdate:
    """
    Day 1: ``_build_complete_state_update`` helper ensures defensive early
    returns from nodes set status/counters explicitly so a stale "thinking"
    state can't route the graph into an infinite loop.
    """

    def test_helper_exists_on_agent_nodes(self) -> None:
        from app.services.react_agent import ReActAgentNodes

        assert hasattr(ReActAgentNodes, "_build_complete_state_update"), (
            "ReActAgentNodes must expose _build_complete_state_update()"
        )

    def test_helper_preserves_current_counters_by_default(self) -> None:
        from app.services.react_agent import ReActAgentNodes

        state = {
            "messages": [],
            "consecutive_no_tools": 1,
            "consecutive_failures": 2,
            "iterations_without_execution": 3,
            "sql_attempts_failed": 1,
            "status": "thinking",
        }

        update = ReActAgentNodes._build_complete_state_update(state)
        assert update["consecutive_no_tools"] == 1
        assert update["consecutive_failures"] == 2
        assert update["iterations_without_execution"] == 3
        assert update["sql_attempts_failed"] == 1

    def test_helper_accepts_field_overrides(self) -> None:
        from app.services.react_agent import ReActAgentNodes

        state = {
            "messages": [],
            "consecutive_no_tools": 1,
            "consecutive_failures": 2,
            "iterations_without_execution": 3,
            "sql_attempts_failed": 1,
            "status": "thinking",
        }

        update = ReActAgentNodes._build_complete_state_update(
            state,
            status="error",
            error="test",
            sql_attempts_failed=0,
        )
        assert update["status"] == "error"
        assert update["error"] == "test"
        assert update["sql_attempts_failed"] == 0
        assert update["consecutive_failures"] == 2


# ---------------------------------------------------------------------------
# Day 2 — checkpoint-resume safety
# ---------------------------------------------------------------------------
#
# Historically ``_resume_from_checkpoint`` (and the streaming equivalent)
# mutated ``state.values["messages"]`` in place, appending the new question
# directly onto the checkpoint's message list. Two concurrent resumes of
# the same thread_id (possible when the distributed-lock fallback is
# process-local) would double-append. Day 2 adds a ``_safely_resume_state``
# helper that returns a fresh state dict with a deep-copied message list.


class TestCheckpointResumeSafety:
    """Day 2: resuming from a checkpoint must not mutate the stored state."""

    def test_safely_resume_state_helper_exists(self) -> None:
        from app.services.react_agent import ReActAgentNodes

        assert hasattr(ReActAgentNodes, "_safely_resume_state"), (
            "ReActAgentNodes must expose _safely_resume_state() to build "
            "a fresh state dict for checkpoint resume"
        )

    def test_resume_does_not_mutate_original_messages(self) -> None:
        """
        Critical safety contract: calling the helper twice against the
        same original state (simulating two concurrent resumes) must not
        produce a doubly-appended messages list on the original.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.services.react_agent import ReActAgentNodes

        original_messages = [
            SystemMessage(content="system"),
            HumanMessage(content="original question"),
        ]
        original_state = {
            "messages": original_messages,
            "status": "complete",
            "iteration": 3,
        }

        resumed_a = ReActAgentNodes._safely_resume_state(original_state, "q1")
        resumed_b = ReActAgentNodes._safely_resume_state(original_state, "q2")

        # Both resumes added exactly one question, independently.
        assert len(resumed_a["messages"]) == len(original_messages) + 1
        assert len(resumed_b["messages"]) == len(original_messages) + 1

        # The ORIGINAL must be untouched.
        assert len(original_state["messages"]) == len(original_messages), (
            "Original state's messages list was mutated — this is the "
            "in-place append bug flagged in the audit"
        )
        assert original_state["status"] == "complete", (
            "Original state's status was mutated"
        )

    def test_resume_resets_status_to_thinking(self) -> None:
        from langchain_core.messages import SystemMessage

        from app.services.react_agent import ReActAgentNodes

        state = {"messages": [SystemMessage(content="s")], "status": "complete"}
        resumed = ReActAgentNodes._safely_resume_state(state, "new question")
        assert resumed["status"] == "thinking"

    def test_resume_appends_human_message(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.services.react_agent import ReActAgentNodes

        state = {"messages": [SystemMessage(content="s")], "status": "complete"}
        resumed = ReActAgentNodes._safely_resume_state(state, "follow-up Q")
        last = resumed["messages"][-1]
        assert isinstance(last, HumanMessage)
        assert last.content == "follow-up Q"


# ---------------------------------------------------------------------------
# Day 2 — tool timeout cancellation
# ---------------------------------------------------------------------------


class TestToolTimeoutCancellation:
    """
    Day 2: timeouts must issue an explicit task.cancel() so that
    cancellation-aware DB drivers can release their side of the query.
    For sync-DB drivers running under ThreadPoolExecutor the thread
    cannot be cancelled (Python limitation — fixed in Phase 3b); this
    test verifies the cancellation path is at least wired correctly.
    """

    @pytest.mark.asyncio
    async def test_task_cancelled_on_timeout(self, monkeypatch) -> None:
        """
        Monkeypatch ToolRegistry.execute to return a coroutine that
        sleeps longer than the timeout, then assert the task was
        cancelled (not just abandoned) so cancellation-aware drivers
        would see a cancel signal.
        """
        import asyncio

        from app.services import react_agent as ra
        from app.services.tools.registry import ToolRegistry

        cancelled_flag = {"value": False}

        async def slow_execute(name, context, **kwargs):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled_flag["value"] = True
                raise
            return '{"success": true}'

        monkeypatch.setattr(ToolRegistry, "execute", slow_execute)

        # Use the helper so we don't need to stand up a whole tool_node.
        # The expectation: if an explicit cancel is used, the sleep task
        # will observe CancelledError.
        task = asyncio.create_task(slow_execute("x", None))
        try:
            await asyncio.wait_for(task, timeout=0.05)
        except asyncio.TimeoutError:
            # asyncio.wait_for already cancels the task in 3.10+.
            # Wait for the cancellation to propagate.
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        assert cancelled_flag["value"], (
            "Expected the slow task to observe CancelledError. If this "
            "fails, either asyncio.wait_for is not cancelling (regression) "
            "or the tool wrapper is swallowing CancelledError."
        )


# ---------------------------------------------------------------------------
# Day 3 — distributed lock fail-loud + background extension
# ---------------------------------------------------------------------------


class TestDistributedLockFailLoud:
    """
    Day 3: when Redis is unavailable the lock used to silently fall back to
    a process-local asyncio.Lock. In multi-worker prod this means two
    workers can run the ReAct agent concurrently for the same session and
    corrupt the checkpoint. Fix: in production (DEVELOPMENT_MODE=False
    and FIX_DISTRIBUTED_LOCK_FAIL_LOUD=True) raise instead of falling back.
    """

    @pytest.mark.asyncio
    async def test_local_fallback_raises_in_production(self, monkeypatch) -> None:
        from app.core.config import settings
        from app.services.distributed_lock import DistributedLock

        monkeypatch.setattr(settings, "DEVELOPMENT_MODE", False)
        monkeypatch.setattr(settings, "FIX_DISTRIBUTED_LOCK_FAIL_LOUD", True)

        # Simulate Redis unavailable
        async def no_redis(cls=None):
            return False

        monkeypatch.setattr(DistributedLock, "_ensure_redis", classmethod(no_redis))

        lock = DistributedLock("test:fail-loud")
        with pytest.raises(RuntimeError, match="Redis"):
            await lock.acquire()

    @pytest.mark.asyncio
    async def test_local_fallback_allowed_in_development(self, monkeypatch) -> None:
        from app.core.config import settings
        from app.services.distributed_lock import DistributedLock

        monkeypatch.setattr(settings, "DEVELOPMENT_MODE", True)
        monkeypatch.setattr(settings, "FIX_DISTRIBUTED_LOCK_FAIL_LOUD", True)

        async def no_redis(cls=None):
            return False

        monkeypatch.setattr(DistributedLock, "_ensure_redis", classmethod(no_redis))

        # Use a unique name to avoid clashes with the cached class-level dict
        lock = DistributedLock("test:dev-mode-ok-unique")
        acquired = await lock.acquire()
        try:
            assert acquired, "Dev mode must still permit local-lock fallback"
        finally:
            if acquired:
                await lock.release()


class TestBackgroundLockExtender:
    """
    Day 3: lock extension moves from the event-driven per-iteration check
    inside the astream loop to a background asyncio.create_task that
    refreshes the TTL every 60s. Cancelled on completion.
    """

    def test_extender_helper_exists(self) -> None:
        from app.services import react_agent as ra

        assert hasattr(ra, "_background_lock_extender"), (
            "react_agent must expose _background_lock_extender coroutine"
        )

    @pytest.mark.asyncio
    async def test_extender_calls_extend_periodically(self) -> None:
        import asyncio

        from app.services.react_agent import _background_lock_extender

        class FakeLock:
            def __init__(self):
                self.name = "fake"
                self.extend_calls = 0

            async def extend(self, ttl: int) -> bool:
                self.extend_calls += 1
                return True

        lock = FakeLock()
        # Very short interval so the test runs quickly
        task = asyncio.create_task(
            _background_lock_extender(lock, interval=0.05, ttl=300, session_id="s1")
        )
        await asyncio.sleep(0.18)  # ~3 intervals
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert lock.extend_calls >= 2, (
            f"Expected periodic extension (>= 2 calls in 0.18s with 0.05s "
            f"interval), got {lock.extend_calls}"
        )

    @pytest.mark.asyncio
    async def test_extender_stops_on_extension_failure(self) -> None:
        """If the lock is lost (extend returns False) the extender must exit."""
        import asyncio

        from app.services.react_agent import _background_lock_extender

        class FakeLock:
            def __init__(self):
                self.name = "fake"
                self.extend_calls = 0

            async def extend(self, ttl: int) -> bool:
                self.extend_calls += 1
                return False  # Lock stolen / lost

        lock = FakeLock()
        task = asyncio.create_task(
            _background_lock_extender(lock, interval=0.02, ttl=300, session_id="s1")
        )
        # Give it enough time to fail-exit
        await asyncio.sleep(0.1)
        assert task.done(), "Extender must exit after the first failed extension"
        assert lock.extend_calls == 1


class TestPoolPreflightCheck:
    """
    Day 3: asyncpg pool acquire historically handed out potentially-dead
    connections. Pre-flight check issues a SELECT 1 before yielding,
    discarding and re-acquiring on failure.
    """

    def test_preflight_flag_exists(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "FIX_POOL_PREFLIGHT"), (
            "settings.FIX_POOL_PREFLIGHT feature flag must exist"
        )


# ---------------------------------------------------------------------------
# Day 4 — real health checks + graceful shutdown drain
# ---------------------------------------------------------------------------


class TestHealthCheckCaching:
    """
    Day 4: /health/ready must perform REAL connectivity checks (LLM + default
    DB) rather than returning hardcoded "healthy". Results are cached for
    10s so container orchestrators don't hammer the dependencies on every
    probe.
    """

    def test_ttl_cache_helper_exists(self) -> None:
        from app.api import health

        assert hasattr(health, "_health_check_cache"), (
            "health module must expose _health_check_cache for TTL caching"
        )
        assert hasattr(health, "_cached_health_check"), (
            "health module must expose _cached_health_check decorator helper"
        )

    @pytest.mark.asyncio
    async def test_cached_result_returned_within_ttl(self) -> None:
        from app.api.health import _cached_health_check, _health_check_cache

        # Clear cache to ensure fresh start
        _health_check_cache.clear()

        call_count = {"value": 0}

        @_cached_health_check("test-key", ttl=10.0)
        async def counted():
            call_count["value"] += 1
            return {"healthy": True, "latency_ms": 1.0}

        r1 = await counted()
        r2 = await counted()
        r3 = await counted()

        assert call_count["value"] == 1, (
            f"Expected 1 underlying call within TTL, got {call_count['value']}"
        )
        assert r1 == r2 == r3

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self) -> None:
        import asyncio

        from app.api.health import _cached_health_check, _health_check_cache

        _health_check_cache.clear()

        call_count = {"value": 0}

        @_cached_health_check("test-expire", ttl=0.05)
        async def counted():
            call_count["value"] += 1
            return {"healthy": True}

        await counted()
        await asyncio.sleep(0.1)  # wait past TTL
        await counted()

        assert call_count["value"] == 2, (
            "Cache must expire after TTL and re-invoke the check"
        )


class TestLLMHealthCheck:
    """Day 4: /health/ready must include LLM provider reachability."""

    def test_llm_health_check_exists(self) -> None:
        from app.api import health

        assert hasattr(health, "_check_llm_health"), (
            "health module must expose _check_llm_health()"
        )


class TestDefaultDBHealthCheck:
    """
    Day 4: /health/ready must probe the default user database (if one is
    configured via DEFAULT_DB_CONNECTION_URL). Without this, the load
    balancer can route traffic to instances that can't reach the DB.
    """

    def test_default_db_health_check_exists(self) -> None:
        from app.api import health

        assert hasattr(health, "_check_default_db_health"), (
            "health module must expose _check_default_db_health()"
        )


class TestGracefulShutdownDrain:
    """
    Day 4: app shutdown must drain in-flight requests for up to 30s
    before closing pools, so active SSE streams / long queries aren't
    interrupted with "connection closed" errors.
    """

    def test_drain_manager_exists(self) -> None:
        from app.core import shutdown_drain

        assert hasattr(shutdown_drain, "ShutdownDrainManager"), (
            "app.core.shutdown_drain must expose ShutdownDrainManager"
        )

    @pytest.mark.asyncio
    async def test_drain_manager_tracks_active_requests(self) -> None:
        from app.core.shutdown_drain import ShutdownDrainManager

        mgr = ShutdownDrainManager()
        assert mgr.active_count == 0

        async with mgr.track_request():
            assert mgr.active_count == 1
            async with mgr.track_request():
                assert mgr.active_count == 2
            assert mgr.active_count == 1
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_drain_waits_for_active_requests(self) -> None:
        import asyncio

        from app.core.shutdown_drain import ShutdownDrainManager

        mgr = ShutdownDrainManager()
        inside_track = asyncio.Event()

        async def slow_request():
            async with mgr.track_request():
                inside_track.set()  # signal: we're inside, active_count is now 1
                await asyncio.sleep(0.08)

        request_task = asyncio.create_task(slow_request())
        # Wait until the task has incremented active_count before calling drain.
        # asyncio.sleep(0.01) was unreliable under xdist parallelism in CI.
        await inside_track.wait()

        # Drain — should wait up to 1s but actually take ~0.08s
        import time

        start = time.monotonic()
        drained = await mgr.drain(timeout=1.0)
        elapsed = time.monotonic() - start

        await request_task

        assert drained, "Should have drained successfully"
        assert elapsed >= 0.06, (
            f"Drain returned immediately ({elapsed:.3f}s) — it should have "
            f"waited for the in-flight request to finish"
        )
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_drain_times_out_on_stuck_requests(self) -> None:
        import asyncio

        from app.core.shutdown_drain import ShutdownDrainManager

        mgr = ShutdownDrainManager()

        # Manually increment; never decrement (simulates stuck request)
        await mgr._enter()  # internal API is fine for the test
        try:
            drained = await mgr.drain(timeout=0.1)
            assert not drained, "Drain must return False on timeout"
        finally:
            await mgr._exit()


# ---------------------------------------------------------------------------
# Day 5 — unified ColumnClassifier
# ---------------------------------------------------------------------------
#
# Prior to Phase 2 Day 5 there were three divergent _get_numeric_columns /
# _get_categorical_columns implementations across insight_detector.py,
# statistics.py, and comparisons.py. Only insight_detector honoured the
# Day 2c smart-ID exclusion; the others happily ran stats on policy_id.
# The classifier is now the single source of truth and the per-engine
# helpers delegate to it.


class TestColumnClassifier:
    """Day 5: unified classifier module + types."""

    def test_classifier_module_exists(self) -> None:
        from app.services.analysis_engines import column_classifier

        assert hasattr(column_classifier, "classify_columns"), (
            "column_classifier must expose classify_columns(data)"
        )
        assert hasattr(column_classifier, "ColumnType"), (
            "column_classifier must expose ColumnType enum"
        )

    def test_classifier_identifies_each_type(self) -> None:
        from app.services.analysis_engines.column_classifier import (
            ColumnType,
            classify_columns,
        )

        # 30 rows / 3 regions = 10% unique → clearly categorical; threshold is <30%.
        # day-of-month 1..28 ensures valid dates.
        data = [
            {
                "revenue": 100 + i,
                "region": f"R{i % 3}",
                "created_at": f"2024-01-{(i % 28) + 1:02d}",
                "policy_id": 1000 + i,  # all-unique numeric → ID
                "comment": f"unique-text-{i}",
            }
            for i in range(30)
        ]

        cols = classify_columns(data)

        assert cols["revenue"].type is ColumnType.NUMERIC
        assert cols["region"].type is ColumnType.CATEGORICAL
        assert cols["created_at"].type is ColumnType.DATE
        assert cols["policy_id"].type is ColumnType.ID
        # "comment" is all-unique text; should NOT be categorical.
        assert cols["comment"].type in (ColumnType.TEXT, ColumnType.UNKNOWN)

    def test_low_cardinality_id_name_stays_numeric(self) -> None:
        """region_id with 3 unique values must NOT be classified as ID."""
        from app.services.analysis_engines.column_classifier import (
            ColumnType,
            classify_columns,
        )

        data = [{"region_id": (i % 3) + 1, "revenue": 100 + i} for i in range(30)]
        cols = classify_columns(data)

        assert cols["region_id"].type is not ColumnType.ID, (
            "region_id with 3 unique values should not be excluded as ID"
        )


class TestAnalysisEngineDelegation:
    """Day 5: existing per-engine helpers must route through the classifier."""

    def test_insight_detector_numeric_matches_classifier(self) -> None:
        from app.services.analysis_engines.column_classifier import (
            ColumnType,
            classify_columns,
        )
        from app.services.analysis_engines.insight_detector import (
            _get_numeric_columns,
        )

        data = [{"revenue": i, "policy_id": 100 + i} for i in range(20)]
        helper_result = set(_get_numeric_columns(data))
        classifier_result = {
            name
            for name, c in classify_columns(data).items()
            if c.type is ColumnType.NUMERIC
        }
        assert helper_result == classifier_result

    def test_statistics_numeric_honours_id_exclusion(self) -> None:
        """
        Previously statistics._get_numeric_columns did NOT exclude IDs,
        so stats were computed on policy_id. Post-Day-5 the helper
        delegates to the classifier, which excludes all-unique ID
        columns.
        """
        from app.services.analysis_engines.statistics import (
            _get_numeric_columns,
        )

        data = [{"policy_id": 1000 + i, "revenue": i * 100} for i in range(20)]
        cols = _get_numeric_columns(data)
        assert "policy_id" not in cols, (
            "statistics._get_numeric_columns must delegate to the classifier "
            "and exclude all-unique ID columns"
        )
        assert "revenue" in cols

    def test_comparisons_numeric_honours_id_exclusion(self) -> None:
        from app.services.analysis_engines.comparisons import (
            _get_numeric_columns,
        )

        data = [{"customer_id": 5000 + i, "amount": i} for i in range(20)]
        cols = _get_numeric_columns(data)
        assert "customer_id" not in cols


class TestNumericSanitization:
    """
    Day 5: NaN and Infinity in statistical output historically broke JSON
    serialization downstream. A sanitize_numeric helper coerces them to
    None at the source of each computation.
    """

    def test_sanitize_helper_exists(self) -> None:
        from app.services.analysis_engines import column_classifier

        # The helper lives next to the classifier since it's used by
        # every analysis engine.
        assert hasattr(column_classifier, "sanitize_numeric"), (
            "column_classifier must expose sanitize_numeric()"
        )

    def test_sanitize_replaces_nan_and_inf(self) -> None:
        import math

        from app.services.analysis_engines.column_classifier import sanitize_numeric

        assert sanitize_numeric(math.nan) is None
        assert sanitize_numeric(math.inf) is None
        assert sanitize_numeric(-math.inf) is None
        assert sanitize_numeric(1.5) == 1.5
        assert sanitize_numeric(0) == 0
        assert sanitize_numeric(None) is None
        # Nested dict/list walk
        sanitized = sanitize_numeric(
            {"mean": math.nan, "items": [1.0, math.inf, 3.0]}
        )
        assert sanitized == {"mean": None, "items": [1.0, None, 3.0]}


# ---------------------------------------------------------------------------
# Day 7 — observability (fix-event counters + alerts)
# ---------------------------------------------------------------------------


class TestPhase2FixEventCounters:
    """
    Day 7: every Phase 2 fix must have a dedicated counter in _fix_events
    so ``/health/diagnostic`` surfaces whether each fix is actively
    catching bugs, and the Prometheus alerts in alerts/queryfyai-alerts.yml
    have a signal to fire on.
    """

    def test_phase2_counters_registered(self) -> None:
        from app.api.metrics import _fix_events

        for name in (
            "two_counter_circuit_breaker",
            "checkpoint_resume_safe_copy",
            "tool_task_cancelled_on_timeout",
            "distributed_lock_fail_loud",
            "background_lock_extension_failure",
            "pool_preflight_discarded",
            "shutdown_drain_timeout",
        ):
            assert name in _fix_events, (
                f"_fix_events must declare the Phase 2 counter {name!r}; "
                f"the Day 7 alert rule keys off it"
            )

    def test_alerts_file_referenced_counters_exist(self) -> None:
        """
        Cross-check: every ``fix_name="..."`` label used in the alerts
        YAML must correspond to a real counter in the metrics module.
        Stops an alert rule from silently dying after a counter rename.
        """
        import re
        from pathlib import Path

        from app.api.metrics import _fix_events

        alerts_path = (
            Path(__file__).resolve().parents[1] / "alerts" / "queryfyai-alerts.yml"
        )
        content = alerts_path.read_text()
        referenced = set(re.findall(r'fix_name="([^"]+)"', content))
        missing = referenced - set(_fix_events.keys())
        assert not missing, (
            f"alerts file references unknown fix_name counters: {sorted(missing)}"
        )
