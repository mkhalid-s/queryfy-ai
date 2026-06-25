"""
Comprehensive unit tests for LLM Service, SQL Generation, and Answer Generator.

Tests cover:
1. CircuitBreaker - state transitions, failure counting, reset, thread safety
2. LLMService - model string construction, API config, cost calculation, caching,
   generate_sql flow, explain_sql, response extraction/cleaning
3. SQLGenerationService - context preparation, SQL generation with self-correction,
   usage aggregation, validation, registration
4. AnswerGenerator - answer generation, result summarization, chart spec building,
   response parsing, fallback answers, edge cases

All external dependencies (LLM APIs, databases, Redis, vector DB) are mocked.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import LLMConfig, DatabaseConfig


# ---------------------------------------------------------------------------
# Helpers: factories for common mock objects
# ---------------------------------------------------------------------------

def make_llm_config(**overrides) -> LLMConfig:
    """Create a default LLMConfig for testing."""
    defaults = {
        "provider": "openai",
        "model": "gpt-4",
        "api_key": "sk-test-key-123",
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


def make_db_config(**overrides) -> DatabaseConfig:
    """Create a default DatabaseConfig for testing."""
    defaults = {
        "db_type": "postgresql",
        "connection_url": "postgresql://user:pass@localhost:5432/testdb",
    }
    defaults.update(overrides)
    return DatabaseConfig(**defaults)


def make_litellm_response(content="SELECT 1", prompt_tokens=100, completion_tokens=50):
    """Create a mock LiteLLM response object."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    mock_response.usage.prompt_tokens = prompt_tokens
    mock_response.usage.completion_tokens = completion_tokens
    mock_response.usage.total_tokens = prompt_tokens + completion_tokens
    return mock_response


# ============================================================================
# 1. CIRCUIT BREAKER TESTS
# ============================================================================


class TestCircuitBreakerStates:
    """Test CircuitBreaker state transitions and behavior."""

    def setup_method(self):
        """Fresh CircuitBreaker for each test."""
        from app.services.llm_service import CircuitBreaker
        self.cb = CircuitBreaker()
        self.config = make_llm_config()

    def test_initial_state_is_closed(self):
        """New circuit breaker should be in CLOSED state."""
        allowed, reason = self.cb.can_execute(self.config)
        assert allowed is True
        assert "closed" in reason.lower()

    def test_failure_count_increments(self):
        """Each failure should increment the count."""
        for i in range(3):
            self.cb.record_failure(self.config, f"error {i}")

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        assert state.failure_count == 3

    def test_circuit_opens_after_threshold(self):
        """Circuit should OPEN after FAILURE_THRESHOLD failures."""
        from app.services.llm_service import CircuitState

        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(self.config, f"error {i}")

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        assert state.state == CircuitState.OPEN

    def test_open_circuit_rejects_requests(self):
        """OPEN circuit should reject requests."""
        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(self.config, "error")

        allowed, reason = self.cb.can_execute(self.config)
        assert allowed is False
        assert "open" in reason.lower()

    def test_circuit_transitions_to_half_open_after_timeout(self):
        """After RECOVERY_TIMEOUT, circuit should transition to HALF_OPEN."""
        from app.services.llm_service import CircuitState

        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(self.config, "error")

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        state.last_failure_time = time.time() - self.cb.RECOVERY_TIMEOUT - 1

        allowed, reason = self.cb.can_execute(self.config)
        assert allowed is True
        assert "half" in reason.lower()
        assert state.state == CircuitState.HALF_OPEN

    def test_half_open_limits_requests(self):
        """HALF_OPEN should allow up to HALF_OPEN_MAX_REQUESTS requests."""

        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(self.config, "error")

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        state.last_failure_time = time.time() - self.cb.RECOVERY_TIMEOUT - 1

        self.cb.can_execute(self.config)

        for _ in range(self.cb.HALF_OPEN_MAX_REQUESTS - 1):
            allowed, _ = self.cb.can_execute(self.config)
            assert allowed is True

        allowed, reason = self.cb.can_execute(self.config)
        assert allowed is False
        assert "max test requests" in reason.lower()

    def test_half_open_closes_after_successes(self):
        """HALF_OPEN should close after SUCCESS_THRESHOLD successes."""
        from app.services.llm_service import CircuitState

        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(self.config, "error")

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        state.last_failure_time = time.time() - self.cb.RECOVERY_TIMEOUT - 1
        self.cb.can_execute(self.config)

        for _ in range(self.cb.SUCCESS_THRESHOLD):
            self.cb.record_success(self.config)

        assert state.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        """Failure in HALF_OPEN should reopen the circuit."""
        from app.services.llm_service import CircuitState

        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(self.config, "error")

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        state.last_failure_time = time.time() - self.cb.RECOVERY_TIMEOUT - 1
        self.cb.can_execute(self.config)

        self.cb.record_failure(self.config, "still broken")
        assert state.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        """Successful request should reset failure count."""
        self.cb.record_failure(self.config, "error1")
        self.cb.record_failure(self.config, "error2")
        self.cb.record_success(self.config)

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        assert state.failure_count == 0

    def test_success_in_open_state_closes_circuit(self):
        """Success in OPEN state (shouldn't normally happen) should close circuit."""
        from app.services.llm_service import CircuitState

        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(self.config, "error")

        key = self.cb._get_provider_key(self.config)
        state = self.cb._get_state(key)
        assert state.state == CircuitState.OPEN

        self.cb.record_success(self.config)
        assert state.state == CircuitState.CLOSED

    def test_different_providers_have_separate_circuits(self):
        """Each provider+model combo should have its own circuit."""
        config_a = make_llm_config(provider="openai", model="gpt-4")
        config_b = make_llm_config(provider="anthropic", model="claude-sonnet-4-20250514")

        for i in range(self.cb.FAILURE_THRESHOLD):
            self.cb.record_failure(config_a, "error")

        allowed_a, _ = self.cb.can_execute(config_a)
        assert allowed_a is False

        allowed_b, _ = self.cb.can_execute(config_b)
        assert allowed_b is True


class TestCircuitBreakerReset:
    """Test CircuitBreaker reset functionality."""

    def setup_method(self):
        from app.services.llm_service import CircuitBreaker
        self.cb = CircuitBreaker()

    def test_reset_specific_provider(self):
        """Reset should clear state for a specific provider."""
        config = make_llm_config()
        for i in range(5):
            self.cb.record_failure(config, "error")

        self.cb.reset(config)

        allowed, _ = self.cb.can_execute(config)
        assert allowed is True

    def test_reset_all(self):
        """Reset without config should clear all states."""
        config_a = make_llm_config(provider="openai", model="gpt-4")
        config_b = make_llm_config(provider="anthropic", model="claude-sonnet-4-20250514")

        for i in range(5):
            self.cb.record_failure(config_a, "error")
            self.cb.record_failure(config_b, "error")

        self.cb.reset()
        assert self.cb._states == {}
        assert self.cb._half_open_requests == {}


class TestCircuitBreakerStatus:
    """Test CircuitBreaker status reporting."""

    def setup_method(self):
        from app.services.llm_service import CircuitBreaker
        self.cb = CircuitBreaker()

    def test_status_empty_initially(self):
        """Status should be empty with no tracked providers."""
        assert self.cb.get_status() == {}

    def test_status_reports_all_providers(self):
        """Status should include all tracked providers."""
        config_a = make_llm_config(provider="openai", model="gpt-4")
        config_b = make_llm_config(provider="anthropic", model="claude-sonnet-4-20250514")

        self.cb.record_failure(config_a, "err")
        self.cb.record_success(config_b)

        status = self.cb.get_status()
        assert len(status) == 2
        for key, info in status.items():
            assert "state" in info
            assert "failure_count" in info

    def test_status_reflects_open_state(self):
        """Status should reflect circuit state accurately."""
        config = make_llm_config()
        for i in range(5):
            self.cb.record_failure(config, "error")

        status = self.cb.get_status()
        key = self.cb._get_provider_key(config)
        assert status[key]["state"] == "open"
        assert status[key]["failure_count"] == 5


class TestCircuitBreakerProviderKey:
    """Test provider key generation."""

    def setup_method(self):
        from app.services.llm_service import CircuitBreaker
        self.cb = CircuitBreaker()

    def test_key_includes_provider_and_model(self):
        config = make_llm_config(provider="openai", model="gpt-4")
        key = self.cb._get_provider_key(config)
        assert "openai" in key
        assert "gpt-4" in key

    def test_key_includes_base_url(self):
        config = make_llm_config(provider="custom", base_url="https://my-llm.example.com")
        key = self.cb._get_provider_key(config)
        assert "my-llm.example.com" in key

    def test_different_models_have_different_keys(self):
        config_a = make_llm_config(provider="openai", model="gpt-4")
        config_b = make_llm_config(provider="openai", model="gpt-3.5-turbo")
        assert self.cb._get_provider_key(config_a) != self.cb._get_provider_key(config_b)


# ============================================================================
# 2. LLM SERVICE TESTS
# ============================================================================


class TestLLMServiceModelString:
    """Test _get_model_string for various providers."""

    def test_openai_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="openai", model="gpt-4o")
        assert LLMService._get_model_string(config) == "openai/gpt-4o"

    def test_anthropic_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="anthropic", model="claude-sonnet-4-20250514")
        assert LLMService._get_model_string(config) == "anthropic/claude-sonnet-4-20250514"

    def test_azure_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="azure", model="gpt-4-turbo")
        assert LLMService._get_model_string(config) == "azure/gpt-4-turbo"

    def test_bedrock_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="bedrock", model="anthropic.claude-3-sonnet-20240229-v1:0")
        assert LLMService._get_model_string(config) == "bedrock/anthropic.claude-3-sonnet-20240229-v1:0"

    def test_groq_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="groq", model="llama-3.1-70b-versatile")
        assert LLMService._get_model_string(config) == "groq/llama-3.1-70b-versatile"

    def test_ollama_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="ollama", model="llama3")
        assert LLMService._get_model_string(config) == "ollama/llama3"

    def test_custom_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="custom", model="my-model")
        assert LLMService._get_model_string(config) == "openai/my-model"

    def test_deepseek_model_string(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="deepseek", model="deepseek-chat")
        assert LLMService._get_model_string(config) == "deepseek/deepseek-chat"

    def test_unknown_provider_falls_back_to_openai(self):
        """Unknown provider should fall back to openai/ prefix."""
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="openai", model="gpt-4")
        object.__setattr__(config, "provider", "unknown_provider")
        result = LLMService._get_model_string(config)
        assert result.startswith("openai/")

    def test_default_model_when_none_for_openai(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="openai")
        result = LLMService._get_model_string(config)
        assert result.startswith("openai/")


class TestLLMServiceApiConfig:
    """Test _get_api_config for different providers."""

    def test_azure_config_includes_base_url_and_version(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(
            provider="azure",
            model="gpt-4",
            base_url="https://my-azure.openai.azure.com",
            api_key="azure-key-123",
        )
        api_config = LLMService._get_api_config(config)
        assert api_config["api_base"] == "https://my-azure.openai.azure.com"
        assert api_config["api_key"] == "azure-key-123"
        assert "api_version" in api_config

    def test_custom_config_includes_base_url(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(
            provider="custom",
            base_url="http://localhost:8080",
            api_key="custom-key",
        )
        api_config = LLMService._get_api_config(config)
        assert api_config["api_base"] == "http://localhost:8080"
        assert api_config["api_key"] == "custom-key"

    def test_custom_config_defaults_api_key_to_none(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="custom", base_url="http://localhost:8080")
        object.__setattr__(config, "api_key", None)
        api_config = LLMService._get_api_config(config)
        assert api_config["api_key"] == "none"

    def test_ollama_config_has_base_url(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="ollama", model="llama3")
        object.__setattr__(config, "api_key", None)
        object.__setattr__(config, "base_url", None)
        api_config = LLMService._get_api_config(config)
        assert api_config["api_base"] == "http://localhost:11434"

    def test_deepseek_config_has_default_base(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="deepseek", model="deepseek-chat")
        object.__setattr__(config, "base_url", None)
        api_config = LLMService._get_api_config(config)
        assert api_config["api_base"] == "https://api.deepseek.com"

    def test_bedrock_config_uses_base_url_as_region(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="bedrock", model="anthropic.claude-3-sonnet")
        object.__setattr__(config, "base_url", "us-west-2")
        object.__setattr__(config, "api_key", None)
        api_config = LLMService._get_api_config(config)
        assert api_config["aws_region_name"] == "us-west-2"

    def test_openai_config_passes_api_key(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="openai", api_key="sk-test-key")
        api_config = LLMService._get_api_config(config)
        assert api_config["api_key"] == "sk-test-key"

    def test_groq_config_passes_api_key(self):
        from app.services.llm_service import LLMService
        config = make_llm_config(provider="groq", api_key="groq-key")
        api_config = LLMService._get_api_config(config)
        assert api_config["api_key"] == "groq-key"


class TestLLMServiceCostCalculation:
    """Test cost calculation for different models."""

    def test_known_model_cost(self):
        from app.services.llm_service import LLMService
        cost = LLMService._calculate_cost("gpt-4", 1000, 500)
        expected = (1000 / 1000) * 0.03 + (500 / 1000) * 0.06
        assert abs(cost - expected) < 0.0001

    def test_gpt4o_mini_cost(self):
        from app.services.llm_service import LLMService
        cost = LLMService._calculate_cost("gpt-4o-mini", 2000, 1000)
        expected = (2000 / 1000) * 0.00015 + (1000 / 1000) * 0.0006
        assert abs(cost - expected) < 0.0001

    def test_provider_prefixed_model_cost(self):
        from app.services.llm_service import LLMService
        cost = LLMService._calculate_cost("azure/gpt-4", 1000, 500)
        expected = (1000 / 1000) * 0.03 + (500 / 1000) * 0.06
        assert abs(cost - expected) < 0.0001

    def test_unknown_model_uses_default_cost(self):
        from app.services.llm_service import LLMService
        cost = LLMService._calculate_cost("completely-unknown-model", 1000, 1000)
        expected = (1000 / 1000) * 0.001 + (1000 / 1000) * 0.002
        assert abs(cost - expected) < 0.0001

    def test_zero_tokens_zero_cost(self):
        from app.services.llm_service import LLMService
        cost = LLMService._calculate_cost("gpt-4", 0, 0)
        assert cost == 0.0


class TestLLMServiceExtractUsage:
    """Test _extract_usage from LiteLLM responses."""

    def test_extracts_usage_from_response(self):
        from app.services.llm_service import LLMService
        response = make_litellm_response(prompt_tokens=200, completion_tokens=100)
        usage = LLMService._extract_usage(response, "openai/gpt-4")

        assert usage.prompt_tokens == 200
        assert usage.completion_tokens == 100
        assert usage.total_tokens == 300
        assert usage.model == "openai/gpt-4"
        assert usage.cost_usd > 0

    def test_handles_missing_usage(self):
        from app.services.llm_service import LLMService
        response = MagicMock()
        response.usage = None

        usage = LLMService._extract_usage(response, "gpt-4")
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0

    def test_handles_missing_usage_attribute(self):
        from app.services.llm_service import LLMService
        response = MagicMock(spec=[])

        usage = LLMService._extract_usage(response, "gpt-4")
        assert usage.prompt_tokens == 0


class TestLLMServiceHashPrompt:
    """Test prompt hashing for caching."""

    def test_same_input_same_hash(self):
        from app.services.llm_service import LLMService
        h1 = LLMService._hash_prompt("SELECT * FROM users", "schema1", "postgresql")
        h2 = LLMService._hash_prompt("SELECT * FROM users", "schema1", "postgresql")
        assert h1 == h2

    def test_different_input_different_hash(self):
        from app.services.llm_service import LLMService
        h1 = LLMService._hash_prompt("SELECT * FROM users", "schema1", "postgresql")
        h2 = LLMService._hash_prompt("SELECT * FROM orders", "schema1", "postgresql")
        assert h1 != h2

    def test_different_db_type_different_hash(self):
        from app.services.llm_service import LLMService
        h1 = LLMService._hash_prompt("query", "schema", "postgresql")
        h2 = LLMService._hash_prompt("query", "schema", "mysql")
        assert h1 != h2

    def test_hash_is_32_chars(self):
        from app.services.llm_service import LLMService
        h = LLMService._hash_prompt("test", "schema", "postgresql")
        assert len(h) == 32


class TestLLMServiceExtractResponse:
    """Test _extract_response for different API formats."""

    def test_openai_format(self):
        from app.services.llm_service import LLMService
        data = {"choices": [{"message": {"content": "  SELECT 1  "}}]}
        assert LLMService._extract_response(data) == "SELECT 1"

    def test_anthropic_format(self):
        from app.services.llm_service import LLMService
        data = {"content": [{"text": "  Hello World  "}]}
        assert LLMService._extract_response(data) == "Hello World"

    def test_generic_response_format(self):
        from app.services.llm_service import LLMService
        data = {"response": "  Some response  "}
        assert LLMService._extract_response(data) == "Some response"

    def test_text_format(self):
        from app.services.llm_service import LLMService
        data = {"text": "  Some text  "}
        assert LLMService._extract_response(data) == "Some text"

    def test_unrecognized_format_raises(self):
        from app.services.llm_service import LLMService
        with pytest.raises(ValueError, match="Unable to extract"):
            LLMService._extract_response({"unknown_key": "value"})


class TestLLMServiceCleanSqlResponse:
    """Test clean_sql_response delegation to prompt providers."""

    @patch("app.services.llm_service.get_prompt_provider")
    def test_delegates_to_prompt_provider(self, mock_get_provider):
        from app.services.llm_service import LLMService
        mock_provider = MagicMock()
        mock_provider.clean_response.return_value = "SELECT * FROM users"
        mock_get_provider.return_value = mock_provider

        result = LLMService.clean_sql_response("```sql\nSELECT * FROM users\n```", "postgresql")
        mock_get_provider.assert_called_once_with("postgresql")
        mock_provider.clean_response.assert_called_once()
        assert result == "SELECT * FROM users"


class TestLLMServiceParseSSEChunk:
    """Test SSE chunk parsing."""

    def test_valid_sse_data(self):
        from app.services.llm_service import LLMService
        chunk_json = json.dumps({"choices": [{"delta": {"content": "Hello"}}]})
        line = f"data: {chunk_json}"
        assert LLMService._parse_sse_chunk(line) == "Hello"

    def test_done_marker(self):
        from app.services.llm_service import LLMService
        assert LLMService._parse_sse_chunk("data: [DONE]") == ""

    def test_empty_line(self):
        from app.services.llm_service import LLMService
        assert LLMService._parse_sse_chunk("") == ""

    def test_non_data_line(self):
        from app.services.llm_service import LLMService
        assert LLMService._parse_sse_chunk("event: message") == ""

    def test_invalid_json(self):
        from app.services.llm_service import LLMService
        assert LLMService._parse_sse_chunk("data: {invalid json}") == ""

    def test_missing_content_in_delta(self):
        from app.services.llm_service import LLMService
        chunk_json = json.dumps({"choices": [{"delta": {}}]})
        assert LLMService._parse_sse_chunk(f"data: {chunk_json}") == ""


@pytest.mark.asyncio
class TestLLMServiceGenerateSQL:
    """Test the generate_sql method end-to-end."""

    @patch("app.services.llm_service._circuit_breaker")
    @patch("app.services.llm_service.acompletion", new_callable=AsyncMock)
    @patch("app.services.llm_service.get_prompt_provider")
    @patch("app.services.llm_service.record_llm_request")
    @patch("app.services.llm_service._tracer")
    async def test_generate_sql_non_streaming_success(
        self, mock_tracer, mock_record, mock_get_provider, mock_acompletion, mock_cb
    ):
        """Generate SQL should return cleaned SQL and usage data."""
        from app.services.llm_service import LLMService

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        mock_cb.can_execute.return_value = (True, "Circuit closed")

        mock_provider = MagicMock()
        mock_provider.get_system_prompt.return_value = "You are a SQL expert."
        mock_provider.clean_response.return_value = "SELECT id, name FROM users WHERE active = true"
        mock_get_provider.return_value = mock_provider

        mock_acompletion.return_value = make_litellm_response(
            content="SELECT id, name FROM users WHERE active = true",
            prompt_tokens=150,
            completion_tokens=30,
        )

        with patch.object(LLMService, "_get_cache_service") as mock_cache:
            mock_cache_svc = AsyncMock()
            mock_cache_svc.get_llm_response = AsyncMock(return_value=None)
            mock_cache_svc.set_llm_response = AsyncMock()
            mock_cache.return_value = mock_cache_svc

            config = make_llm_config()

            sql, usage = await LLMService.generate_sql(
                config=config,
                prompt="Show me active users",
                schema="CREATE TABLE users (id INT, name TEXT, active BOOL);",
                history=[],
                db_type="postgresql",
            )

            assert sql == "SELECT id, name FROM users WHERE active = true"
            assert usage is not None
            assert usage.prompt_tokens == 150

    @patch("app.services.llm_service._tracer")
    async def test_generate_sql_cache_hit(self, mock_tracer):
        """Should return cached response when available."""
        from app.services.llm_service import LLMService

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        with patch.object(LLMService, "_get_cache_service") as mock_cache:
            mock_cache_svc = AsyncMock()
            mock_cache_svc.get_llm_response = AsyncMock(return_value="SELECT cached_result")
            mock_cache.return_value = mock_cache_svc

            config = make_llm_config()

            sql, usage = await LLMService.generate_sql(
                config=config,
                prompt="cached query",
                schema="schema",
                history=[],
            )
            assert sql == "SELECT cached_result"
            assert usage is not None
            assert usage.cached is True

    @patch("app.services.llm_service._circuit_breaker")
    @patch("app.services.llm_service._tracer")
    async def test_generate_sql_circuit_breaker_rejects(self, mock_tracer, mock_cb):
        """Should raise when circuit breaker is open."""
        from app.services.llm_service import LLMService

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        mock_cb.can_execute.return_value = (False, "Circuit open, retry in 45s")

        with patch.object(LLMService, "_get_cache_service") as mock_cache:
            mock_cache_svc = AsyncMock()
            mock_cache_svc.get_llm_response = AsyncMock(return_value=None)
            mock_cache.return_value = mock_cache_svc

            config = make_llm_config()

            with pytest.raises(Exception, match="unavailable"):
                await LLMService.generate_sql(
                    config=config,
                    prompt="test",
                    schema="schema",
                    history=[],
                )


@pytest.mark.asyncio
class TestLLMServiceCallLitellm:
    """Test _call_litellm error handling."""

    @patch("app.services.llm_service._circuit_breaker")
    @patch("app.services.llm_service._metrics_tracker")
    @patch("app.services.llm_service.acompletion", new_callable=AsyncMock)
    @patch("app.services.llm_service.record_llm_request")
    async def test_call_litellm_api_error(
        self, mock_record, mock_acompletion, mock_metrics, mock_cb
    ):
        """API errors should be recorded and re-raised."""
        from app.services.llm_service import LLMService

        mock_cb.can_execute.return_value = (True, "ok")
        mock_acompletion.side_effect = Exception("API rate limit exceeded")

        config = make_llm_config()
        messages = [{"role": "user", "content": "test"}]

        with pytest.raises(Exception, match="request failed"):
            await LLMService._call_litellm(config, messages)

        mock_cb.record_failure.assert_called_once()
        mock_metrics.record_error.assert_called_once()

    @patch("app.services.llm_service._circuit_breaker")
    @patch("app.services.llm_service._metrics_tracker")
    @patch("app.services.llm_service.acompletion", new_callable=AsyncMock)
    @patch("app.services.llm_service.record_llm_request")
    async def test_call_litellm_records_success(
        self, mock_record, mock_acompletion, mock_metrics, mock_cb
    ):
        """Successful calls should record success on circuit breaker."""
        from app.services.llm_service import LLMService

        mock_cb.can_execute.return_value = (True, "ok")
        mock_acompletion.return_value = make_litellm_response("SELECT 1")

        config = make_llm_config()
        messages = [{"role": "user", "content": "test"}]

        content, usage = await LLMService._call_litellm(config, messages)
        assert content == "SELECT 1"
        mock_cb.record_success.assert_called_once()


class TestLLMUsageData:
    """Test LLMUsageData dataclass."""

    def test_to_dict(self):
        from app.services.llm_service import LLMUsageData
        usage = LLMUsageData(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4",
            cost_usd=0.009,
            cached=False,
        )
        d = usage.to_dict()
        assert d["prompt_tokens"] == 100
        assert d["model"] == "gpt-4"
        assert d["cost_usd"] == 0.009
        assert d["cached"] is False

    def test_to_dict_rounds_cost(self):
        from app.services.llm_service import LLMUsageData
        usage = LLMUsageData(cost_usd=0.00000123456789)
        d = usage.to_dict()
        assert d["cost_usd"] == round(0.00000123456789, 6)


class TestLLMMetricsTracker:
    """Test LLMMetricsTracker."""

    def test_record_usage_increments(self):
        from app.services.llm_service import LLMMetricsTracker, LLMUsageData

        tracker = LLMMetricsTracker()
        usage = LLMUsageData(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4",
            cost_usd=0.009,
            cached=False,
        )
        tracker.record_usage(usage, latency_ms=200.0)

        assert tracker.total_requests == 1
        assert tracker.cache_misses == 1
        assert tracker.total_prompt_tokens == 100

    def test_cache_hit_tracking(self):
        from app.services.llm_service import LLMMetricsTracker, LLMUsageData

        tracker = LLMMetricsTracker()
        cached_usage = LLMUsageData(cached=True)
        tracker.record_usage(cached_usage)

        assert tracker.cache_hits == 1
        assert tracker.cache_misses == 0

    def test_error_tracking(self):
        from app.services.llm_service import LLMMetricsTracker

        tracker = LLMMetricsTracker()
        tracker.record_error()
        tracker.record_error()

        metrics = tracker.get_metrics()
        assert metrics["errors"] == 2

    def test_get_metrics_with_no_requests(self):
        from app.services.llm_service import LLMMetricsTracker

        tracker = LLMMetricsTracker()
        metrics = tracker.get_metrics()
        assert metrics["total_requests"] == 0
        assert metrics["cache_hit_rate"] == 0.0
        assert metrics["avg_latency_ms"] == 0.0


class TestIsAnthropicModel:
    """Test is_anthropic_model helper."""

    def test_claude_model(self):
        from app.services.llm_service import is_anthropic_model
        assert is_anthropic_model("claude-sonnet-4-20250514") is True

    def test_bedrock_claude(self):
        from app.services.llm_service import is_anthropic_model
        assert is_anthropic_model("anthropic.claude-3-sonnet-20240229-v1:0") is True

    def test_non_anthropic(self):
        from app.services.llm_service import is_anthropic_model
        assert is_anthropic_model("gpt-4o") is False

    def test_empty_string(self):
        from app.services.llm_service import is_anthropic_model
        assert is_anthropic_model("") is False

    def test_none_returns_false(self):
        from app.services.llm_service import is_anthropic_model
        assert is_anthropic_model(None) is False


class TestIsComplexQueryForRouting:
    """Test complexity detection for model routing."""

    @patch("app.services.prompt_providers.sql.is_complex_query")
    @patch("app.services.prompt_providers.mongodb.is_complex_mongodb_query")
    def test_sql_query_delegates_to_sql_complexity(self, mock_mongo, mock_sql):
        from app.services.llm_service import is_complex_query_for_routing
        mock_sql.return_value = True

        result = is_complex_query_for_routing("complex JOIN query", "postgresql")
        assert result is True
        mock_sql.assert_called_once_with("complex JOIN query")
        mock_mongo.assert_not_called()

    @patch("app.services.prompt_providers.sql.is_complex_query")
    @patch("app.services.prompt_providers.mongodb.is_complex_mongodb_query")
    def test_mongodb_query_delegates_to_mongo_complexity(self, mock_mongo, mock_sql):
        from app.services.llm_service import is_complex_query_for_routing
        mock_mongo.return_value = False

        result = is_complex_query_for_routing("simple find", "mongodb")
        assert result is False
        mock_mongo.assert_called_once_with("simple find")
        mock_sql.assert_not_called()


@pytest.mark.asyncio
class TestCompletionWithFallback:
    """Test completion_with_fallback function."""

    @patch("app.services.llm_service.acompletion", new_callable=AsyncMock)
    async def test_first_model_succeeds(self, mock_acompletion):
        from app.services.llm_service import completion_with_fallback

        mock_acompletion.return_value = make_litellm_response("Success!")
        result = await completion_with_fallback(
            [{"role": "user", "content": "test"}],
            model_tier="default",
        )
        assert result == "Success!"
        assert mock_acompletion.call_count == 1

    @patch("app.services.llm_service.acompletion", new_callable=AsyncMock)
    async def test_fallback_on_first_model_failure(self, mock_acompletion):
        from app.services.llm_service import completion_with_fallback

        mock_acompletion.side_effect = [
            Exception("Model 1 failed"),
            make_litellm_response("Fallback success"),
        ]

        result = await completion_with_fallback(
            [{"role": "user", "content": "test"}],
            model_tier="default",
        )
        assert result == "Fallback success"
        assert mock_acompletion.call_count == 2

    @patch("app.services.llm_service.acompletion", new_callable=AsyncMock)
    async def test_all_models_fail_raises(self, mock_acompletion):
        from app.services.llm_service import completion_with_fallback

        mock_acompletion.side_effect = Exception("All fail")

        with pytest.raises(Exception, match="All fail"):
            await completion_with_fallback(
                [{"role": "user", "content": "test"}],
                model_tier="fast",
            )

    @patch("app.services.llm_service.acompletion", new_callable=AsyncMock)
    async def test_unknown_tier_uses_default(self, mock_acompletion):
        from app.services.llm_service import completion_with_fallback

        mock_acompletion.return_value = make_litellm_response("ok")
        await completion_with_fallback(
            [{"role": "user", "content": "test"}],
            model_tier="nonexistent_tier",
        )
        assert mock_acompletion.called


# ============================================================================
# 3. SQL GENERATION SERVICE TESTS
# ============================================================================


class TestSQLGenerationResult:
    """Test the SQLGenerationResult dataclass."""

    def test_default_values(self):
        from app.services.sql_generation import SQLGenerationResult
        result = SQLGenerationResult(success=True)
        assert result.sql is None
        assert result.error is None
        assert result.warnings is None
        assert result.attempts == 1

    def test_success_result(self):
        from app.services.sql_generation import SQLGenerationResult
        result = SQLGenerationResult(
            success=True,
            sql="SELECT 1",
            query_id="abc-123",
            sql_hash="hash123",
        )
        assert result.success is True
        assert result.sql == "SELECT 1"

    def test_error_result(self):
        from app.services.sql_generation import SQLGenerationResult
        result = SQLGenerationResult(
            success=False,
            error="Generation failed",
            message="Rate limit exceeded",
            attempts=3,
        )
        assert result.success is False
        assert result.attempts == 3


class TestSQLGenerationServiceAggregateUsage:
    """Test _aggregate_usage method."""

    def test_aggregate_with_no_existing(self):
        from app.services.sql_generation import SQLGenerationService
        from app.services.llm_service import LLMUsageData

        usage = LLMUsageData(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4",
            cost_usd=0.009,
        )
        result = SQLGenerationService._aggregate_usage({}, usage)
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50
        assert result["model"] == "gpt-4"

    def test_aggregate_multiple_usages(self):
        from app.services.sql_generation import SQLGenerationService
        from app.services.llm_service import LLMUsageData

        existing = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "model": "gpt-4",
            "cost_usd": 0.009,
            "cached": False,
            "calls": 1,
        }
        new_usage = LLMUsageData(
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            model="gpt-4",
            cost_usd=0.018,
        )
        result = SQLGenerationService._aggregate_usage(existing, new_usage)
        assert result["prompt_tokens"] == 300
        assert result["completion_tokens"] == 150
        assert result["calls"] == 2
        assert abs(result["cost_usd"] - 0.027) < 0.001

    def test_aggregate_with_none_usage(self):
        from app.services.sql_generation import SQLGenerationService

        existing = {"prompt_tokens": 100}
        result = SQLGenerationService._aggregate_usage(existing, None)
        assert result == existing


@pytest.mark.asyncio
class TestSQLGenerationServicePrepareContext:
    """Test prepare_context method."""

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.SecurityService")
    async def test_prepare_context_with_security_warning(
        self, mock_security, mock_vector_db
    ):
        """Security warnings should return an error result."""
        from app.services.sql_generation import SQLGenerationService

        mock_security.sanitize_input.return_value = (
            "sanitized",
            ["Potential SQL injection detected"],
        )

        ctx, error = await SQLGenerationService.prepare_context(
            session_id="test-session",
            session={
                "llm_config": make_llm_config().model_dump(),
                "db_config": make_db_config().model_dump(),
            },
            natural_language="DROP TABLE users; --",
        )

        assert ctx is None
        assert error is not None
        assert error.success is False
        assert error.warnings is not None
        assert len(error.warnings) > 0

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.SecurityService")
    @patch("app.services.sql_generation.SQLGenerationService._get_data_dictionary_context", new_callable=AsyncMock)
    async def test_prepare_context_success(
        self, mock_dd, mock_security, mock_vector_db
    ):
        """Valid input should return a GenerationContext."""
        from app.services.sql_generation import SQLGenerationService

        mock_security.sanitize_input.return_value = ("show me all users", [])
        mock_vector_db._hash_connection.return_value = "conn_hash_123"
        mock_vector_db.get_relevant_schema.return_value = "CREATE TABLE users (id INT);"
        mock_dd.return_value = (None, None)

        with patch.dict("sys.modules", {"app.api.chat": MagicMock(_detect_follow_up=MagicMock(return_value=False))}):
            ctx, error = await SQLGenerationService.prepare_context(
                session_id="test-session",
                session={
                    "llm_config": make_llm_config().model_dump(),
                    "db_config": make_db_config().model_dump(),
                    "context_window": [],
                },
                natural_language="show me all users",
            )

        assert error is None
        assert ctx is not None
        assert ctx.sanitized_query == "show me all users"
        assert ctx.session_id == "test-session"


@pytest.mark.asyncio
class TestSQLGenerationServiceGenerateSQL:
    """Test generate_sql with self-correction."""

    def _make_context(self):
        """Build a GenerationContext for testing."""
        from app.services.sql_generation import GenerationContext
        return GenerationContext(
            session_id="test-session-123",
            session={"context_window": []},
            llm_config=make_llm_config(),
            db_config=make_db_config(),
            natural_language="show all users",
            sanitized_query="show all users",
            relevant_schema="CREATE TABLE users (id INT, name TEXT);",
            conversation_history=[],
        )

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.session_store")
    @patch("app.services.sql_generation.sql_integrity")
    @patch("app.services.sql_generation.query_history_service", new_callable=AsyncMock)
    @patch("app.services.sql_generation.SecurityService")
    @patch("app.services.sql_generation.LLMService")
    async def test_successful_generation(
        self,
        mock_llm,
        mock_security,
        mock_qh,
        mock_integrity,
        mock_session_store,
        mock_vector_db,
    ):
        """Should generate SQL successfully on first attempt."""
        from app.services.sql_generation import SQLGenerationService
        from app.services.llm_service import LLMUsageData

        mock_vector_db.find_similar_queries.return_value = []
        mock_llm.generate_sql = AsyncMock(
            return_value=("SELECT id, name FROM users", LLMUsageData(prompt_tokens=100, completion_tokens=30))
        )
        mock_llm.clean_sql_response.return_value = "SELECT id, name FROM users"
        mock_security.validate_generated_sql.return_value = (True, "OK")
        mock_session_store.add_history.return_value = "entry-id-123"
        mock_integrity.register_sql.return_value = "hash-abc"
        mock_vector_db.store_successful_query.return_value = None
        mock_qh.save_query = AsyncMock()

        ctx = self._make_context()
        result = await SQLGenerationService.generate_sql(ctx, validate_sql=False)

        assert result.success is True
        assert result.sql == "SELECT id, name FROM users"
        assert result.query_id == "entry-id-123"
        assert result.attempts == 1

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.SecurityService")
    @patch("app.services.sql_generation.LLMService")
    async def test_llm_returns_error_response(
        self, mock_llm, mock_security, mock_vector_db
    ):
        """Should detect error markers in LLM response."""
        from app.services.sql_generation import SQLGenerationService
        from app.services.llm_service import LLMUsageData

        mock_vector_db.find_similar_queries.return_value = []
        mock_llm.generate_sql = AsyncMock(
            return_value=("-- ERROR: Cannot generate SQL for this question", LLMUsageData())
        )

        ctx = self._make_context()
        result = await SQLGenerationService.generate_sql(ctx)

        assert result.success is False
        assert "Unable to generate SQL" in result.error

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.SecurityService")
    @patch("app.services.sql_generation.LLMService")
    async def test_unsafe_sql_rejected(self, mock_llm, mock_security, mock_vector_db):
        """Generated SQL that fails safety validation should be rejected."""
        from app.services.sql_generation import SQLGenerationService
        from app.services.llm_service import LLMUsageData

        mock_vector_db.find_similar_queries.return_value = []
        mock_llm.generate_sql = AsyncMock(
            return_value=("DROP TABLE users;", LLMUsageData())
        )
        mock_llm.clean_sql_response.return_value = "DROP TABLE users;"
        mock_security.validate_generated_sql.return_value = (
            False,
            "DML/DDL statements not allowed",
        )

        ctx = self._make_context()
        result = await SQLGenerationService.generate_sql(ctx, validate_sql=False)

        assert result.success is False
        assert "validation" in result.error.lower()

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.session_store")
    @patch("app.services.sql_generation.sql_integrity")
    @patch("app.services.sql_generation.query_history_service", new_callable=AsyncMock)
    @patch("app.services.sql_generation.SecurityService")
    @patch("app.services.sql_generation.LLMService")
    @patch("app.services.sql_generation.DatabaseService")
    async def test_self_correction_on_validation_failure(
        self,
        mock_db_service,
        mock_llm,
        mock_security,
        mock_qh,
        mock_integrity,
        mock_session_store,
        mock_vector_db,
    ):
        """Should retry with error context when SQL validation fails."""
        from app.services.sql_generation import SQLGenerationService
        from app.services.llm_service import LLMUsageData

        mock_vector_db.find_similar_queries.return_value = []
        mock_vector_db.store_successful_query.return_value = None

        mock_llm.generate_sql = AsyncMock(
            side_effect=[
                ("SELECT * FROM nonexistent_table", LLMUsageData(prompt_tokens=100, completion_tokens=30)),
                ("SELECT id, name FROM users", LLMUsageData(prompt_tokens=150, completion_tokens=30)),
            ]
        )
        mock_llm.clean_sql_response.side_effect = [
            "SELECT * FROM nonexistent_table",
            "SELECT id, name FROM users",
        ]
        mock_security.validate_generated_sql.return_value = (True, "OK")
        mock_db_service.execute_query = AsyncMock(
            side_effect=[
                Exception("relation 'nonexistent_table' does not exist"),
                None,
            ]
        )
        mock_session_store.add_history.return_value = "entry-id"
        mock_integrity.register_sql.return_value = "hash-abc"
        mock_qh.save_query = AsyncMock()

        ctx = self._make_context()
        result = await SQLGenerationService.generate_sql(ctx, validate_sql=True)

        assert result.success is True
        assert result.attempts == 2
        assert mock_llm.generate_sql.call_count == 2

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.SecurityService")
    @patch("app.services.sql_generation.LLMService")
    async def test_max_retries_exhausted(self, mock_llm, mock_security, mock_vector_db):
        """Should return error after MAX_RETRY_ATTEMPTS."""
        from app.services.sql_generation import SQLGenerationService
        from app.services.llm_service import LLMUsageData

        mock_vector_db.find_similar_queries.return_value = []

        mock_llm.generate_sql = AsyncMock(
            return_value=("SELECT", LLMUsageData())
        )
        mock_llm.clean_sql_response.return_value = "SELECT"

        ctx = self._make_context()
        result = await SQLGenerationService.generate_sql(ctx, validate_sql=False)

        assert result.success is False
        assert result.attempts == 3
        assert "valid SQL" in result.message

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.SecurityService")
    @patch("app.services.sql_generation.LLMService")
    async def test_exception_during_generation(
        self, mock_llm, mock_security, mock_vector_db
    ):
        """Should handle exceptions during LLM calls."""
        from app.services.sql_generation import SQLGenerationService

        mock_vector_db.find_similar_queries.return_value = []
        mock_llm.generate_sql = AsyncMock(side_effect=Exception("LLM API timeout"))

        ctx = self._make_context()
        result = await SQLGenerationService.generate_sql(ctx, validate_sql=False)

        assert result.success is False
        assert "failed" in result.error.lower()


@pytest.mark.asyncio
class TestSQLGenerationServiceValidation:
    """Test _validate_sql_execution method."""

    def _make_context(self, db_type="postgresql"):
        from app.services.sql_generation import GenerationContext
        return GenerationContext(
            session_id="test-session",
            session={},
            llm_config=make_llm_config(),
            db_config=make_db_config(db_type=db_type),
            natural_language="test",
            sanitized_query="test",
            relevant_schema="schema",
            conversation_history=[],
        )

    @patch("app.services.sql_generation.DatabaseService")
    async def test_validation_passes(self, mock_db_service):
        """Successful execution should return None (no error)."""
        from app.services.sql_generation import SQLGenerationService

        mock_db_service.execute_query = AsyncMock(return_value=None)
        ctx = self._make_context()

        error = await SQLGenerationService._validate_sql_execution(
            ctx, "SELECT * FROM users"
        )
        assert error is None

    @patch("app.services.sql_generation.DatabaseService")
    async def test_validation_syntax_error(self, mock_db_service):
        """Syntax errors should be reported."""
        from app.services.sql_generation import SQLGenerationService

        mock_db_service.execute_query = AsyncMock(
            side_effect=Exception("syntax error at or near 'SELCT'")
        )
        ctx = self._make_context()

        error = await SQLGenerationService._validate_sql_execution(
            ctx, "SELCT * FROM users"
        )
        assert error is not None
        assert "syntax error" in error.lower()

    @patch("app.services.sql_generation.DatabaseService")
    async def test_validation_table_not_found(self, mock_db_service):
        """Table/column errors should be reported."""
        from app.services.sql_generation import SQLGenerationService

        mock_db_service.execute_query = AsyncMock(
            side_effect=Exception("relation 'nonexistent' does not exist")
        )
        ctx = self._make_context()

        error = await SQLGenerationService._validate_sql_execution(
            ctx, "SELECT * FROM nonexistent"
        )
        assert error is not None
        assert "invalid table" in error.lower()

    @patch("app.services.sql_generation.DatabaseService")
    async def test_validation_permission_denied_ignored(self, mock_db_service):
        """Permission errors should not be treated as generation errors."""
        from app.services.sql_generation import SQLGenerationService

        mock_db_service.execute_query = AsyncMock(
            side_effect=Exception("permission denied for relation users")
        )
        ctx = self._make_context()

        error = await SQLGenerationService._validate_sql_execution(
            ctx, "SELECT * FROM users"
        )
        assert error is None

    async def test_mongodb_skips_validation(self):
        """MongoDB queries should skip execution validation."""
        from app.services.sql_generation import SQLGenerationService

        ctx = self._make_context(db_type="mongodb")
        error = await SQLGenerationService._validate_sql_execution(
            ctx, "db.users.find({})"
        )
        assert error is None

    async def test_dynamodb_skips_validation(self):
        """DynamoDB queries should skip execution validation."""
        from app.services.sql_generation import SQLGenerationService

        ctx = self._make_context(db_type="dynamodb")
        error = await SQLGenerationService._validate_sql_execution(
            ctx, "SELECT * FROM MyTable"
        )
        assert error is None

    async def test_cassandra_skips_validation(self):
        """Cassandra queries should skip execution validation."""
        from app.services.sql_generation import SQLGenerationService

        ctx = self._make_context(db_type="cassandra")
        error = await SQLGenerationService._validate_sql_execution(
            ctx, "SELECT * FROM keyspace.table"
        )
        assert error is None


@pytest.mark.asyncio
class TestSQLGenerationServiceDataDictionary:
    """Test data dictionary context retrieval."""

    async def test_disabled_returns_none(self):
        """When DATA_DICTIONARY_ENABLED is False, should return None, None."""
        from app.services.sql_generation import SQLGenerationService

        with patch("app.services.sql_generation.DATA_DICTIONARY_ENABLED", False):
            terms, cols = await SQLGenerationService._get_data_dictionary_context(
                "conn_hash", "show users"
            )
            assert terms is None
            assert cols is None

    async def test_exception_returns_none(self):
        """Exceptions during data dictionary fetch should be handled gracefully."""
        from app.services.sql_generation import SQLGenerationService

        with patch("app.services.sql_generation.DATA_DICTIONARY_ENABLED", True):
            with patch.dict("sys.modules", {"app.services.data_dictionary": MagicMock(
                data_dictionary=MagicMock(
                    get_relevant_terms=AsyncMock(side_effect=Exception("DB not ready")),
                )
            )}):
                terms, cols = await SQLGenerationService._get_data_dictionary_context(
                    "conn_hash", "show users"
                )
                assert terms is None
                assert cols is None


@pytest.mark.asyncio
class TestSQLGenerationServiceRegisterAgentResult:
    """Test register_agent_result method."""

    @patch("app.services.sql_generation.vector_db")
    @patch("app.services.sql_generation.session_store")
    @patch("app.services.sql_generation.sql_integrity")
    @patch("app.services.sql_generation.query_history_service", new_callable=AsyncMock)
    async def test_registers_agent_result(
        self, mock_qh, mock_integrity, mock_session_store, mock_vector_db
    ):
        from app.services.sql_generation import SQLGenerationService, GenerationContext

        mock_session_store.add_history.return_value = "entry-id"
        mock_integrity.register_sql.return_value = "hash-123"
        mock_vector_db.store_successful_query.return_value = None
        mock_qh.save_query = AsyncMock()

        ctx = GenerationContext(
            session_id="sess-1",
            session={"context_window": []},
            llm_config=make_llm_config(),
            db_config=make_db_config(),
            natural_language="show users",
            sanitized_query="show users",
            relevant_schema="schema",
            conversation_history=[],
            connection_hash="conn-hash",
        )

        result = await SQLGenerationService.register_agent_result(
            ctx,
            generated_sql="SELECT * FROM users",
            agent_attempts=2,
            agent_explanation="Used users table",
        )

        assert result.success is True
        assert result.sql == "SELECT * FROM users"
        call_args = mock_session_store.add_history.call_args[0]
        history_entry = call_args[1]
        assert history_entry["agent_attempts"] == 2
        assert history_entry["explanation"] == "Used users table"


# ============================================================================
# 4. ANSWER GENERATOR TESTS
# ============================================================================


class TestAnswerGeneratorSummarizeResult:
    """Test _summarize_result method."""

    def test_summarize_with_dict_rows(self):
        from app.services.answer_generator import AnswerGenerator

        result = {
            "columns": ["name", "revenue"],
            "rows": [
                {"name": "Acme", "revenue": 1000},
                {"name": "Beta", "revenue": 2000},
            ],
            "row_count": 2,
        }
        summary = AnswerGenerator._summarize_result(result)
        assert "name" in summary
        assert "revenue" in summary
        assert "Total rows: 2" in summary
        assert "Acme" in summary

    def test_summarize_with_list_rows(self):
        from app.services.answer_generator import AnswerGenerator

        result = {
            "columns": ["id", "value"],
            "rows": [[1, 100], [2, 200]],
            "row_count": 2,
        }
        summary = AnswerGenerator._summarize_result(result)
        assert "id" in summary
        assert "100" in summary

    def test_summarize_empty_result(self):
        from app.services.answer_generator import AnswerGenerator

        result = {"columns": ["id"], "rows": [], "row_count": 0}
        summary = AnswerGenerator._summarize_result(result)
        assert "Total rows: 0" in summary

    def test_summarize_truncates_large_results(self):
        from app.services.answer_generator import AnswerGenerator

        result = {
            "columns": ["id"],
            "rows": [{"id": i} for i in range(100)],
            "row_count": 100,
        }
        summary = AnswerGenerator._summarize_result(result, max_rows=5)
        assert "5 of 100" in summary
        assert "95 more rows" in summary

    def test_summarize_truncates_long_values(self):
        from app.services.answer_generator import AnswerGenerator

        long_text = "x" * 100
        result = {
            "columns": ["data"],
            "rows": [{"data": long_text}],
            "row_count": 1,
        }
        summary = AnswerGenerator._summarize_result(result)
        assert "..." in summary


class TestAnswerGeneratorComputeBasicStats:
    """Test _compute_basic_stats method."""

    def test_numeric_stats(self):
        from app.services.answer_generator import AnswerGenerator

        columns = ["revenue"]
        rows = [{"revenue": 100}, {"revenue": 200}, {"revenue": 300}]
        stats = AnswerGenerator._compute_basic_stats(columns, rows)
        assert "sum=600" in stats
        assert "avg=200" in stats
        assert "min=100" in stats
        assert "max=300" in stats

    def test_string_numeric_parsing(self):
        from app.services.answer_generator import AnswerGenerator

        columns = ["amount"]
        rows = [{"amount": "$1,000"}, {"amount": "$2,000"}, {"amount": "$3,000"}]
        stats = AnswerGenerator._compute_basic_stats(columns, rows)
        assert "sum=" in stats

    def test_empty_rows(self):
        from app.services.answer_generator import AnswerGenerator

        stats = AnswerGenerator._compute_basic_stats(["col"], [])
        assert stats == ""

    def test_non_numeric_columns_skipped(self):
        from app.services.answer_generator import AnswerGenerator

        columns = ["name"]
        rows = [{"name": "Alice"}, {"name": "Bob"}]
        stats = AnswerGenerator._compute_basic_stats(columns, rows)
        assert stats == ""

    def test_few_values_skipped(self):
        """Should not show stats for fewer than 3 values."""
        from app.services.answer_generator import AnswerGenerator

        columns = ["val"]
        rows = [{"val": 1}, {"val": 2}]
        stats = AnswerGenerator._compute_basic_stats(columns, rows)
        assert stats == ""

    def test_list_rows(self):
        from app.services.answer_generator import AnswerGenerator

        columns = ["val"]
        rows = [[10], [20], [30]]
        stats = AnswerGenerator._compute_basic_stats(columns, rows)
        assert "sum=60" in stats


class TestAnswerGeneratorBuildPrompt:
    """Test _build_prompt method."""

    def test_prompt_contains_question(self):
        from app.services.answer_generator import AnswerGenerator

        prompt = AnswerGenerator._build_prompt(
            "Who are top customers?",
            "SELECT * FROM customers",
            "summary data",
        )
        assert "Who are top customers?" in prompt
        assert "SELECT * FROM customers" in prompt
        assert "summary data" in prompt


class TestAnswerGeneratorParseResponse:
    """Test _parse_response method."""

    def test_parses_json_in_code_block(self):
        from app.services.answer_generator import AnswerGenerator

        response = '''Some text before.
```json
{
  "answer": "Test answer",
  "key_findings": ["Finding 1"],
  "confidence": 0.9,
  "chart_recommendation": {"should_chart": false}
}
```
Some text after.'''

        result_data = {"columns": [], "rows": [], "row_count": 0}
        parsed = AnswerGenerator._parse_response(response, result_data)
        assert parsed["answer"] == "Test answer"
        assert parsed["confidence"] == 0.9
        assert len(parsed["key_findings"]) == 1

    def test_parses_bare_json(self):
        from app.services.answer_generator import AnswerGenerator

        response = '{"answer": "Direct JSON", "key_findings": [], "confidence": 0.8}'
        parsed = AnswerGenerator._parse_response(response, {})
        assert parsed["answer"] == "Direct JSON"

    def test_parses_json_with_preamble(self):
        from app.services.answer_generator import AnswerGenerator

        response = 'Here is the analysis: {"answer": "Preamble JSON", "key_findings": ["one"], "confidence": 0.85}'
        parsed = AnswerGenerator._parse_response(response, {})
        assert parsed["answer"] == "Preamble JSON"

    def test_manual_extraction_fallback(self):
        from app.services.answer_generator import AnswerGenerator

        response = """This is the main answer for the analysis.

- First important finding
- Second important finding
- Third finding with details"""

        parsed = AnswerGenerator._parse_response(response, {})
        assert "answer" in parsed
        assert len(parsed["key_findings"]) >= 2
        assert parsed["confidence"] == 0.7


class TestAnswerGeneratorExtractManually:
    """Test _extract_manually method."""

    def test_extracts_answer_and_findings(self):
        from app.services.answer_generator import AnswerGenerator

        text = """The revenue grew 20% this quarter.

- Top customer contributed 40% of revenue
- Growth was driven by enterprise segment
* New customer acquisition up 15%
"""
        result = AnswerGenerator._extract_manually(text)
        assert "revenue grew" in result["answer"]
        assert len(result["key_findings"]) == 3

    def test_numbered_findings(self):
        from app.services.answer_generator import AnswerGenerator

        text = """Summary here.

1. First finding of significance
2. Second finding of significance"""

        result = AnswerGenerator._extract_manually(text)
        assert len(result["key_findings"]) == 2

    def test_empty_text(self):
        from app.services.answer_generator import AnswerGenerator

        result = AnswerGenerator._extract_manually("")
        assert "Analysis complete" in result["answer"]
        assert result["key_findings"] == []

    def test_short_findings_filtered(self):
        """Findings shorter than 10 chars should be filtered out."""
        from app.services.answer_generator import AnswerGenerator

        text = """Answer text here.

- OK
- This is a sufficiently long finding to be included"""

        result = AnswerGenerator._extract_manually(text)
        assert len(result["key_findings"]) == 1


class TestAnswerGeneratorBuildChartSpec:
    """Test _build_chart_spec method."""

    def test_builds_bar_chart(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {
            "chart_type": "bar",
            "x_column": "name",
            "y_column": "revenue",
            "reason": "Compare revenue",
        }
        result = {
            "columns": ["name", "revenue"],
            "rows": [
                {"name": "A", "revenue": 100},
                {"name": "B", "revenue": 200},
            ],
        }
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is not None
        assert chart.chart_type.value == "bar"
        assert chart.x_axis == "name"
        assert chart.y_axis == "revenue"
        assert len(chart.data) == 2

    def test_builds_line_chart(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {
            "chart_type": "line",
            "x_column": "month",
            "y_column": "sales",
        }
        result = {
            "columns": ["month", "sales"],
            "rows": [["Jan", 100], ["Feb", 150], ["Mar", 200]],
        }
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is not None
        assert chart.chart_type.value == "line"
        assert len(chart.data) == 3

    def test_returns_none_when_column_missing(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {
            "chart_type": "bar",
            "x_column": "nonexistent",
            "y_column": "revenue",
        }
        result = {"columns": ["name", "revenue"], "rows": []}
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is None

    def test_returns_none_when_x_column_is_none(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {"chart_type": "bar", "x_column": None, "y_column": "revenue"}
        result = {"columns": ["revenue"], "rows": []}
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is None

    def test_returns_none_when_no_data(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {
            "chart_type": "bar",
            "x_column": "name",
            "y_column": "revenue",
        }
        result = {"columns": ["name", "revenue"], "rows": []}
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is None

    def test_limits_data_points_to_50(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {
            "chart_type": "bar",
            "x_column": "id",
            "y_column": "val",
        }
        result = {
            "columns": ["id", "val"],
            "rows": [{"id": i, "val": i * 10} for i in range(100)],
        }
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is not None
        assert len(chart.data) == 50

    def test_unknown_chart_type_defaults_to_bar(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {
            "chart_type": "unknown_type",
            "x_column": "name",
            "y_column": "val",
        }
        result = {
            "columns": ["name", "val"],
            "rows": [{"name": "A", "val": 1}],
        }
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is not None
        assert chart.chart_type.value == "bar"

    def test_handles_none_values_in_rows(self):
        from app.services.answer_generator import AnswerGenerator

        recommendation = {
            "chart_type": "bar",
            "x_column": "name",
            "y_column": "val",
        }
        result = {
            "columns": ["name", "val"],
            "rows": [
                {"name": "A", "val": 10},
                {"name": None, "val": 20},
                {"name": "C", "val": None},
            ],
        }
        chart = AnswerGenerator._build_chart_spec(recommendation, result)
        assert chart is not None
        assert len(chart.data) == 1


class TestAnswerGeneratorFallbackAnswer:
    """Test _generate_fallback_answer method."""

    def test_zero_rows(self):
        from app.services.answer_generator import AnswerGenerator

        answer = AnswerGenerator._generate_fallback_answer(
            "How many users?",
            {"row_count": 0, "columns": ["count"]},
        )
        assert "no results" in answer.lower()

    def test_one_row(self):
        from app.services.answer_generator import AnswerGenerator

        answer = AnswerGenerator._generate_fallback_answer(
            "What is the total?",
            {"row_count": 1, "columns": ["total"]},
        )
        assert "1 result" in answer.lower()

    def test_many_rows(self):
        from app.services.answer_generator import AnswerGenerator

        answer = AnswerGenerator._generate_fallback_answer(
            "Show users",
            {"row_count": 42, "columns": ["id", "name", "email", "status"]},
        )
        assert "42" in answer
        assert "4 columns" in answer
        assert "..." in answer

    def test_many_rows_few_columns(self):
        from app.services.answer_generator import AnswerGenerator

        answer = AnswerGenerator._generate_fallback_answer(
            "Show users",
            {"row_count": 10, "columns": ["id", "name"]},
        )
        assert "10" in answer
        assert "..." not in answer


@pytest.mark.asyncio
class TestAnswerGeneratorGenerate:
    """Test the main generate method."""

    @patch("app.services.answer_generator._tracer")
    @patch("app.services.answer_generator.acompletion", new_callable=AsyncMock)
    @patch("app.services.answer_generator.LLMService")
    async def test_successful_generation(self, mock_llm_svc, mock_acompletion, mock_tracer):
        """Should generate answer with findings and optional chart."""
        from app.services.answer_generator import AnswerGenerator

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        json_response = json.dumps({
            "answer": "Revenue grew 20% this quarter.",
            "key_findings": [
                "Q4 revenue was $1.5M",
                "Growth rate accelerated in December",
            ],
            "confidence": 0.92,
            "chart_recommendation": {
                "should_chart": True,
                "chart_type": "line",
                "x_column": "month",
                "y_column": "revenue",
                "reason": "Shows trend over time",
            },
        })

        mock_response = make_litellm_response(
            content=json_response,
            prompt_tokens=500,
            completion_tokens=200,
        )
        mock_acompletion.return_value = mock_response
        mock_llm_svc._get_model_string.return_value = "openai/gpt-4"
        mock_llm_svc._get_api_config.return_value = {"api_key": "test"}

        config = make_llm_config()
        result_data = {
            "columns": ["month", "revenue"],
            "rows": [
                {"month": "Oct", "revenue": 1200000},
                {"month": "Nov", "revenue": 1350000},
                {"month": "Dec", "revenue": 1500000},
            ],
            "row_count": 3,
        }

        answer_result = await AnswerGenerator.generate(
            llm_config=config,
            question="How did revenue change this quarter?",
            sql="SELECT month, revenue FROM sales WHERE quarter = 'Q4'",
            result=result_data,
        )

        assert answer_result.answer == "Revenue grew 20% this quarter."
        assert len(answer_result.key_findings) == 2
        assert answer_result.confidence == 0.92
        assert answer_result.chart is not None
        assert answer_result.chart.chart_type.value == "line"

    @patch("app.services.answer_generator._tracer")
    @patch("app.services.answer_generator.acompletion", new_callable=AsyncMock)
    @patch("app.services.answer_generator.LLMService")
    async def test_llm_failure_returns_fallback(self, mock_llm_svc, mock_acompletion, mock_tracer):
        """LLM failure should return a fallback answer."""
        from app.services.answer_generator import AnswerGenerator

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        mock_acompletion.side_effect = Exception("API timeout")
        mock_llm_svc._get_model_string.return_value = "openai/gpt-4"
        mock_llm_svc._get_api_config.return_value = {"api_key": "test"}

        config = make_llm_config()
        result_data = {
            "columns": ["count"],
            "rows": [{"count": 42}],
            "row_count": 1,
        }

        answer_result = await AnswerGenerator.generate(
            llm_config=config,
            question="How many users?",
            sql="SELECT COUNT(*) FROM users",
            result=result_data,
        )

        assert answer_result.confidence == 0.5
        assert answer_result.chart is None
        assert answer_result.key_findings == []
        assert "1 result" in answer_result.answer.lower()

    @patch("app.services.answer_generator._tracer")
    @patch("app.services.answer_generator.acompletion", new_callable=AsyncMock)
    @patch("app.services.answer_generator.LLMService")
    async def test_no_chart_when_not_recommended(self, mock_llm_svc, mock_acompletion, mock_tracer):
        """Should not include chart when should_chart is false."""
        from app.services.answer_generator import AnswerGenerator

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        json_response = json.dumps({
            "answer": "The count is 42.",
            "key_findings": ["Single scalar result"],
            "confidence": 0.95,
            "chart_recommendation": {"should_chart": False},
        })

        mock_acompletion.return_value = make_litellm_response(content=json_response)
        mock_llm_svc._get_model_string.return_value = "openai/gpt-4"
        mock_llm_svc._get_api_config.return_value = {"api_key": "test"}

        config = make_llm_config()
        result_data = {"columns": ["count"], "rows": [{"count": 42}], "row_count": 1}

        answer_result = await AnswerGenerator.generate(
            llm_config=config,
            question="How many users?",
            sql="SELECT COUNT(*) FROM users",
            result=result_data,
        )

        assert answer_result.chart is None

    @patch("app.services.answer_generator._tracer")
    @patch("app.services.answer_generator.acompletion", new_callable=AsyncMock)
    @patch("app.services.answer_generator.LLMService")
    async def test_include_reasoning(self, mock_llm_svc, mock_acompletion, mock_tracer):
        """Should include raw reasoning when requested."""
        from app.services.answer_generator import AnswerGenerator

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        json_response = json.dumps({
            "answer": "Test answer",
            "key_findings": [],
            "confidence": 0.8,
            "chart_recommendation": {"should_chart": False},
        })

        mock_acompletion.return_value = make_litellm_response(content=json_response)
        mock_llm_svc._get_model_string.return_value = "openai/gpt-4"
        mock_llm_svc._get_api_config.return_value = {"api_key": "test"}

        config = make_llm_config()
        result_data = {"columns": ["id"], "rows": [], "row_count": 0}

        answer_result = await AnswerGenerator.generate(
            llm_config=config,
            question="test",
            sql="SELECT 1",
            result=result_data,
            include_reasoning=True,
        )

        assert answer_result.reasoning is not None
        assert answer_result.reasoning == json_response

    @patch("app.services.answer_generator._tracer")
    @patch("app.services.answer_generator.acompletion", new_callable=AsyncMock)
    @patch("app.services.answer_generator.LLMService")
    async def test_empty_result_set(self, mock_llm_svc, mock_acompletion, mock_tracer):
        """Should handle empty result sets gracefully."""
        from app.services.answer_generator import AnswerGenerator

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        json_response = json.dumps({
            "answer": "No data matches your criteria.",
            "key_findings": ["No records found"],
            "confidence": 0.95,
            "chart_recommendation": {"should_chart": False},
        })

        mock_acompletion.return_value = make_litellm_response(content=json_response)
        mock_llm_svc._get_model_string.return_value = "openai/gpt-4"
        mock_llm_svc._get_api_config.return_value = {"api_key": "test"}

        config = make_llm_config()
        result_data = {"columns": ["id", "name"], "rows": [], "row_count": 0}

        answer_result = await AnswerGenerator.generate(
            llm_config=config,
            question="Show deleted users",
            sql="SELECT * FROM users WHERE deleted = true",
            result=result_data,
        )

        assert "No data" in answer_result.answer

    @patch("app.services.answer_generator._tracer")
    @patch("app.services.answer_generator.LLMService")
    async def test_oauth_gateway_routing(self, mock_llm_svc, mock_tracer):
        """OAuth gateway calls should be routed to _call_oauth_gateway."""
        from app.services.answer_generator import AnswerGenerator
        from app.services.llm_service import LLMUsageData

        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        json_response = json.dumps({
            "answer": "Answer via OAuth",
            "key_findings": [],
            "confidence": 0.8,
            "chart_recommendation": {"should_chart": False},
        })

        mock_llm_svc._call_oauth_gateway = AsyncMock(
            return_value=(json_response, LLMUsageData(prompt_tokens=100, completion_tokens=50))
        )

        config = make_llm_config(
            provider="oauth_gateway",
            base_url="https://gateway.example.com",
            model="claude-3-sonnet",
        )
        result_data = {"columns": ["id"], "rows": [{"id": 1}], "row_count": 1}

        answer_result = await AnswerGenerator.generate(
            llm_config=config,
            question="test",
            sql="SELECT 1",
            result=result_data,
        )

        assert answer_result.answer == "Answer via OAuth"
        mock_llm_svc._call_oauth_gateway.assert_called_once()


@pytest.mark.asyncio
class TestAnswerGeneratorCallLLM:
    """Test _call_llm routing."""

    @patch("app.services.answer_generator.acompletion", new_callable=AsyncMock)
    @patch("app.services.answer_generator.LLMService")
    async def test_standard_provider_uses_litellm(self, mock_llm_svc, mock_acompletion):
        from app.services.answer_generator import AnswerGenerator

        mock_acompletion.return_value = make_litellm_response("response text")
        mock_llm_svc._get_model_string.return_value = "openai/gpt-4"
        mock_llm_svc._get_api_config.return_value = {"api_key": "test"}

        config = make_llm_config(provider="openai")
        messages = [{"role": "user", "content": "test"}]

        content, usage = await AnswerGenerator._call_llm(config, messages)
        assert content == "response text"
        mock_acompletion.assert_called_once()

    @patch("app.services.answer_generator.LLMService")
    async def test_oauth_provider_uses_oauth_gateway(self, mock_llm_svc):
        from app.services.answer_generator import AnswerGenerator
        from app.services.llm_service import LLMUsageData

        mock_llm_svc._call_oauth_gateway = AsyncMock(
            return_value=("oauth response", LLMUsageData())
        )

        config = make_llm_config(
            provider="oauth_gateway",
            base_url="https://gw.example.com",
        )
        messages = [{"role": "user", "content": "test"}]

        content, usage = await AnswerGenerator._call_llm(config, messages)
        assert content == "oauth response"
        mock_llm_svc._call_oauth_gateway.assert_called_once()

    @patch("app.services.answer_generator.acompletion", new_callable=AsyncMock)
    @patch("app.services.answer_generator.LLMService")
    async def test_call_llm_propagates_exceptions(self, mock_llm_svc, mock_acompletion):
        from app.services.answer_generator import AnswerGenerator

        mock_acompletion.side_effect = Exception("Network error")
        mock_llm_svc._get_model_string.return_value = "openai/gpt-4"
        mock_llm_svc._get_api_config.return_value = {}

        config = make_llm_config()
        with pytest.raises(Exception, match="Network error"):
            await AnswerGenerator._call_llm(config, [{"role": "user", "content": "test"}])


class TestAnswerGeneratorCalculateCost:
    """Test _calculate_cost in AnswerGenerator."""

    def test_known_model_cost(self):
        from app.services.answer_generator import AnswerGenerator

        usage = MagicMock()
        usage.prompt_tokens = 1000
        usage.completion_tokens = 500

        # "gpt-4" prefix matches first in dict iteration for "gpt-4o"
        cost = AnswerGenerator._calculate_cost(usage, "gpt-4o")
        expected = (1000 / 1000) * 0.03 + (500 / 1000) * 0.06
        assert abs(cost - expected) < 0.0001

    def test_unknown_model_default_cost(self):
        from app.services.answer_generator import AnswerGenerator

        usage = MagicMock()
        usage.prompt_tokens = 1000
        usage.completion_tokens = 500

        cost = AnswerGenerator._calculate_cost(usage, "unknown-model")
        expected = (1000 / 1000) * 0.01 + (500 / 1000) * 0.03
        assert abs(cost - expected) < 0.0001


class TestAnswerResult:
    """Test the AnswerResult dataclass."""

    def test_answer_result_construction(self):
        from app.services.answer_generator import AnswerResult

        result = AnswerResult(
            answer="Test answer",
            key_findings=["finding1", "finding2"],
            confidence=0.9,
            chart=None,
            reasoning=None,
            usage={"prompt_tokens": 100},
        )
        assert result.answer == "Test answer"
        assert len(result.key_findings) == 2
        assert result.confidence == 0.9
        assert result.chart is None
