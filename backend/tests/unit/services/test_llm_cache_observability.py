"""
Unit tests for Anthropic prompt-cache observability.

Cover the ``LLMUsageData`` cache-token fields and the two attach
helpers that read counts from a LiteLLM response object or an
OAuth-gateway-shaped JSON dict. The helpers are pure, easy to
unit-test without the full LLM service stack.
"""

from types import SimpleNamespace

from app.services.llm_service import (
    LLMMetricsTracker,
    LLMUsageData,
    _attach_cache_metrics,
    _attach_cache_metrics_from_dict,
)


class TestLLMUsageDataCacheFields:
    """The two new fields default to 0 and serialise correctly."""

    def test_defaults_zero(self):
        usage = LLMUsageData()
        assert usage.cache_creation_input_tokens == 0
        assert usage.cache_read_input_tokens == 0
        assert usage.cached is False

    def test_to_dict_includes_cache_fields(self):
        usage = LLMUsageData(
            prompt_tokens=100,
            cache_creation_input_tokens=80,
            cache_read_input_tokens=20,
        )
        d = usage.to_dict()
        assert d["cache_creation_input_tokens"] == 80
        assert d["cache_read_input_tokens"] == 20
        # Existing fields preserved
        assert d["prompt_tokens"] == 100
        assert d["cached"] is False  # still default; helper sets it


class TestAttachCacheMetrics:
    """Defensive read of LiteLLM response.usage attributes."""

    def test_response_with_anthropic_cache_fields(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cache_creation_input_tokens=80,
                cache_read_input_tokens=20,
            )
        )
        usage = LLMUsageData(prompt_tokens=100)
        _attach_cache_metrics(usage, response)
        assert usage.cache_creation_input_tokens == 80
        assert usage.cache_read_input_tokens == 20
        assert usage.cached is True  # cache_read > 0

    def test_response_without_cache_fields_noop(self):
        """OpenAI-shaped response — no cache_* attributes."""
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            )
        )
        usage = LLMUsageData(prompt_tokens=100)
        _attach_cache_metrics(usage, response)
        assert usage.cache_creation_input_tokens == 0
        assert usage.cache_read_input_tokens == 0
        assert usage.cached is False  # not flipped

    def test_response_without_usage_attribute_noop(self):
        """Error path — response object has no usage at all."""
        response = SimpleNamespace()
        usage = LLMUsageData(prompt_tokens=100)
        # Must not raise.
        _attach_cache_metrics(usage, response)
        assert usage.cache_read_input_tokens == 0

    def test_cache_read_zero_does_not_set_cached_flag(self):
        """cache_creation alone (first cached request) doesn't count as a hit."""
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=100,
                cache_creation_input_tokens=80,
                cache_read_input_tokens=0,
            )
        )
        usage = LLMUsageData()
        _attach_cache_metrics(usage, response)
        assert usage.cache_creation_input_tokens == 80
        assert usage.cache_read_input_tokens == 0
        assert usage.cached is False  # only cache_read > 0 counts as hit

    def test_none_attribute_values_treated_as_zero(self):
        """LiteLLM may surface None when the field is absent — coerce to 0."""
        response = SimpleNamespace(
            usage=SimpleNamespace(
                cache_creation_input_tokens=None,
                cache_read_input_tokens=None,
            )
        )
        usage = LLMUsageData()
        _attach_cache_metrics(usage, response)
        assert usage.cache_creation_input_tokens == 0
        assert usage.cache_read_input_tokens == 0


class TestAttachCacheMetricsFromDict:
    """OAuth-gateway path uses dict access, not attribute access."""

    def test_dict_with_cache_fields(self):
        usage = LLMUsageData()
        _attach_cache_metrics_from_dict(
            usage,
            {
                "prompt_tokens": 100,
                "cache_creation_input_tokens": 80,
                "cache_read_input_tokens": 20,
            },
        )
        assert usage.cache_creation_input_tokens == 80
        assert usage.cache_read_input_tokens == 20
        assert usage.cached is True

    def test_dict_missing_cache_fields_noop(self):
        usage = LLMUsageData()
        _attach_cache_metrics_from_dict(
            usage, {"prompt_tokens": 100, "completion_tokens": 50}
        )
        assert usage.cache_creation_input_tokens == 0
        assert usage.cache_read_input_tokens == 0

    def test_none_dict_noop(self):
        usage = LLMUsageData()
        # Defensive — gateway response without usage block.
        _attach_cache_metrics_from_dict(usage, None)
        assert usage.cache_creation_input_tokens == 0


class TestMetricsTrackerCacheTotals:
    """LLMMetricsTracker tallies per-call cache tokens across requests."""

    def test_records_cache_tokens(self):
        tracker = LLMMetricsTracker()
        tracker.record_usage(
            LLMUsageData(
                prompt_tokens=100,
                cache_creation_input_tokens=80,
                cache_read_input_tokens=20,
                cached=True,
            )
        )
        tracker.record_usage(
            LLMUsageData(
                prompt_tokens=100,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=80,
                cached=True,
            )
        )
        m = tracker.get_metrics()
        assert m["total_cache_creation_tokens"] == 80
        assert m["total_cache_read_tokens"] == 100
        assert m["cache_hits"] == 2  # both requests had cache_read > 0

    def test_zero_cache_tokens_when_no_anthropic_traffic(self):
        tracker = LLMMetricsTracker()
        tracker.record_usage(LLMUsageData(prompt_tokens=100))
        m = tracker.get_metrics()
        assert m["total_cache_creation_tokens"] == 0
        assert m["total_cache_read_tokens"] == 0
        assert m["cache_token_savings_usd_estimate"] == 0
