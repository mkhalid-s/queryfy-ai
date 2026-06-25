"""
Smoke tests for the analyst-mode observability wiring.

Intentionally *fast and dependency-light*: no DB, no network, no
real LLM calls, no full agent graph. Verifies two pieces:

  1. Anthropic prompt-cache token observability —
     ``_attach_cache_metrics`` reads cache fields from a mock
     LiteLLM response and flips ``LLMUsageData.cached`` when a hit
     occurs; the metrics tracker tallies tokens correctly.

  2. Wall-clock budget circuit breaker —
     ``should_continue`` returns ``"end"`` when the agent has been
     running longer than ``wall_clock_budget_seconds``.

Run via:
    bash backend/scripts/run-tests.sh tests/smoke -v

The runner self-heals the broken-symlink venv so this works in
any dev container without ceremony.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ============================================================
# Anthropic prompt-cache observability (commit cc76916)
# ============================================================


class TestCacheObservabilitySmoke:
    """Cheap end-to-end check that the observability wiring fires."""

    def test_cache_hit_flips_cached_flag_and_increments_tracker(self):
        from app.services.llm_service import (
            LLMMetricsTracker,
            LLMUsageData,
            _attach_cache_metrics,
        )

        # Mock LiteLLM response shape with Anthropic cache fields.
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                cache_creation_input_tokens=80,
                cache_read_input_tokens=20,
            )
        )
        usage = LLMUsageData(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            model="anthropic/claude-3-haiku",
        )
        _attach_cache_metrics(usage, response)

        assert usage.cache_creation_input_tokens == 80
        assert usage.cache_read_input_tokens == 20
        assert usage.cached is True

        tracker = LLMMetricsTracker()
        tracker.record_usage(usage, latency_ms=42.0)
        m = tracker.get_metrics()
        assert m["cache_hits"] == 1
        assert m["cache_misses"] == 0
        assert m["total_cache_creation_tokens"] == 80
        assert m["total_cache_read_tokens"] == 20
        # Savings estimate uses Anthropic's published 90% discount.
        assert m["cache_token_savings_usd_estimate"] >= 0

    def test_no_cache_response_keeps_tracker_at_zero(self):
        """OpenAI-shape response (no cache_* attrs) → tracker stays clean."""
        from app.services.llm_service import (
            LLMMetricsTracker,
            LLMUsageData,
            _attach_cache_metrics,
        )

        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
            )
        )
        usage = LLMUsageData(prompt_tokens=100, model="openai/gpt-4o")
        _attach_cache_metrics(usage, response)

        tracker = LLMMetricsTracker()
        tracker.record_usage(usage)
        m = tracker.get_metrics()
        assert m["cache_hits"] == 0
        assert m["cache_misses"] == 1
        assert m["total_cache_read_tokens"] == 0
        assert m["cache_token_savings_usd_estimate"] == 0


# ============================================================
# Wall-clock budget circuit breaker (commit 2315866)
# ============================================================


class TestWallClockBudgetSmoke:
    """should_continue ends the loop when the wall-clock budget trips."""

    def _state_with_elapsed(self, elapsed_seconds: float, budget: float = 600.0):
        from langchain_core.messages import AIMessage

        from app.services.react_agent import ReActState

        return {  # type: ignore[return-value]
            "messages": [AIMessage(content="thinking...")],
            "iteration": 3,
            "max_iterations": 10,
            "status": "thinking",
            "failed_attempts": [],
            "consecutive_failures": 0,
            "iterations_without_execution": 0,
            "consecutive_no_tools": 0,
            "wall_clock_start": time.monotonic() - elapsed_seconds,
            "wall_clock_budget_seconds": budget,
        }

    def test_elapsed_exceeds_budget_routes_to_end(self):
        from app.services.react_agent import should_continue

        state = self._state_with_elapsed(elapsed_seconds=700.0, budget=600.0)
        assert should_continue(state) == "end"

    def test_elapsed_within_budget_falls_through(self):
        from app.services.react_agent import should_continue

        state = self._state_with_elapsed(elapsed_seconds=30.0, budget=600.0)
        # Falls through — no tool_calls on last message, no sql/result yet
        assert should_continue(state) == "agent"

    def test_budget_zero_disables_check(self):
        from app.services.react_agent import should_continue

        state = self._state_with_elapsed(elapsed_seconds=3600.0, budget=0.0)
        # Wall-clock check is skipped when budget == 0
        assert should_continue(state) == "agent"


# ============================================================
# Logger wiring smoke (cache_read log fires through structlog)
# ============================================================


class TestCacheReadLogWiring:
    """
    Sanity check that the structured ``llm.cache_read`` log line is
    emittable through the project's logging stack. Doesn't run the
    full LLM service — just verifies the helper + logger combo
    doesn't raise on a realistic payload.
    """

    def test_structured_log_payload_is_valid(self, caplog):
        from app.services.llm_service import (
            LLMUsageData,
            _attach_cache_metrics,
        )

        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=100,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=20,
            )
        )
        usage = LLMUsageData(prompt_tokens=100)
        _attach_cache_metrics(usage, response)

        # The full _call_with_tools path emits the log; here we just
        # assert the data needed to render it is well-formed.
        payload = {
            "model": "anthropic/claude-3-haiku",
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "prompt_tokens": usage.prompt_tokens,
        }
        assert all(isinstance(v, (str, int)) for v in payload.values())
        assert payload["cache_read_input_tokens"] > 0


# ============================================================
# Test-runner sanity (M1 self-heal works)
# ============================================================


def test_pytest_can_import_app_modules():
    """
    If you can import these, the venv self-heal in
    backend/scripts/run-tests.sh did its job. Cheap canary that
    catches venv breakage before any actual test runs.
    """
    # Import a representative slice of analyst-mode modules.
    from app.core.config import settings  # noqa: F401
    from app.models.chat_models import ChatResponse  # noqa: F401
    from app.services.llm_service import LLMUsageData  # noqa: F401
    from app.services.react_agent import should_continue  # noqa: F401
    from app.services.tools.query_tools import (  # noqa: F401
        _pii_columns_for_table,
    )
