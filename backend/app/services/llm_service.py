"""
QueryfyAI - LLM Service (LiteLLM-based)

Unified LLM interface with:
- LiteLLM for all standard providers (OpenAI, Anthropic, Azure, custom)
- Custom OAuth gateway handling (LiteLLM doesn't support OAuth)
- Response caching via cache_service
- Automatic retries and error handling
- Database-specific prompts via PromptProvider registry
- Cost tracking per LLM call
- Complexity-based model routing (fast model for simple queries)
- Circuit breaker for resilience against provider failures
"""

# Disable LiteLLM telemetry before import
import os

os.environ.setdefault("LITELLM_TELEMETRY", "False")

import copy
import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import litellm
from litellm import acompletion

from app.api.metrics import record_llm_request
from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.telemetry import get_tracer
from app.models.schemas import LLMConfig
from app.services.prompt_providers import get_prompt_provider

logger = get_logger(__name__)

# Get tracer for this module
_tracer = get_tracer(__name__)


# ============================================================================
# CIRCUIT BREAKER FOR LLM PROVIDERS
# ============================================================================


class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerState:
    """State for a single provider's circuit breaker"""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    consecutive_successes: int = 0


class CircuitBreaker:
    """
    Circuit breaker for LLM providers to prevent cascading failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are rejected immediately
    - HALF_OPEN: Testing recovery, allowing limited requests

    Configuration:
    - FAILURE_THRESHOLD: Number of failures before opening circuit
    - RECOVERY_TIMEOUT: Seconds to wait before testing recovery
    - SUCCESS_THRESHOLD: Successes needed to close circuit from half-open

    Thread Safety: Uses threading.Lock for concurrent access protection.
    """

    FAILURE_THRESHOLD = 5  # Open circuit after 5 consecutive failures
    RECOVERY_TIMEOUT = 60  # Wait 60 seconds before testing recovery
    SUCCESS_THRESHOLD = 2  # Need 2 successes to close circuit
    HALF_OPEN_MAX_REQUESTS = 3  # Max concurrent requests in half-open state

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._states: Dict[str, CircuitBreakerState] = {}
        self._half_open_requests: Dict[str, int] = {}

    def _get_provider_key(self, config: LLMConfig) -> str:
        """Get unique key for provider (base_url + model)"""
        return f"{config.provider}:{config.base_url or 'default'}:{config.model or 'default'}"

    def _get_state(self, key: str) -> CircuitBreakerState:
        """Get or create state for provider"""
        if key not in self._states:
            self._states[key] = CircuitBreakerState()
        return self._states[key]

    def can_execute(self, config: LLMConfig) -> Tuple[bool, str]:
        """
        Check if request should be allowed through.
        Thread-safe via lock.

        Returns: (allowed, reason)
        """
        key = self._get_provider_key(config)
        now = time.time()

        with self._lock:
            state = self._get_state(key)

            if state.state == CircuitState.CLOSED:
                return True, "Circuit closed"

            if state.state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                time_since_failure = now - state.last_failure_time
                if time_since_failure >= self.RECOVERY_TIMEOUT:
                    # Transition to half-open
                    state.state = CircuitState.HALF_OPEN
                    state.consecutive_successes = 0
                    self._half_open_requests[key] = 1  # Count this first request
                    logger.info(f"Circuit breaker: {key} transitioning to HALF_OPEN")
                    return True, "Circuit half-open, testing recovery"
                else:
                    remaining = self.RECOVERY_TIMEOUT - time_since_failure
                    return False, f"Circuit open, retry in {int(remaining)}s"

            if state.state == CircuitState.HALF_OPEN:
                # Allow limited requests in half-open state
                current_requests = self._half_open_requests.get(key, 0)
                if current_requests < self.HALF_OPEN_MAX_REQUESTS:
                    self._half_open_requests[key] = current_requests + 1
                    return True, "Circuit half-open, testing"
                else:
                    return False, "Circuit half-open, max test requests reached"

            return True, "Unknown state, allowing"

    def record_success(self, config: LLMConfig):
        """Record successful request. Thread-safe via lock."""
        key = self._get_provider_key(config)
        now = time.time()

        with self._lock:
            state = self._get_state(key)

            state.last_success_time = now
            state.failure_count = 0

            if state.state == CircuitState.HALF_OPEN:
                # Decrement active request counter
                if (
                    key in self._half_open_requests
                    and self._half_open_requests[key] > 0
                ):
                    self._half_open_requests[key] -= 1

                state.consecutive_successes += 1
                if state.consecutive_successes >= self.SUCCESS_THRESHOLD:
                    state.state = CircuitState.CLOSED
                    self._half_open_requests.pop(key, None)  # Clean up counter
                    logger.info(f"Circuit breaker: {key} closed after recovery")
            elif state.state == CircuitState.OPEN:
                # Shouldn't happen, but handle gracefully
                state.state = CircuitState.CLOSED

    def record_failure(self, config: LLMConfig, error: str = ""):
        """Record failed request. Thread-safe via lock."""
        key = self._get_provider_key(config)
        now = time.time()

        with self._lock:
            state = self._get_state(key)

            state.failure_count += 1
            state.last_failure_time = now

            if state.state == CircuitState.HALF_OPEN:
                # Decrement active request counter
                if (
                    key in self._half_open_requests
                    and self._half_open_requests[key] > 0
                ):
                    self._half_open_requests[key] -= 1

                # Failed during recovery test - reopen circuit
                state.state = CircuitState.OPEN
                state.consecutive_successes = 0
                logger.warning(
                    f"Circuit breaker: {key} reopened after failed recovery test"
                )

            elif state.state == CircuitState.CLOSED:
                if state.failure_count >= self.FAILURE_THRESHOLD:
                    state.state = CircuitState.OPEN
                    logger.warning(
                        f"Circuit breaker: {key} opened after {state.failure_count} failures",
                        error_preview=error[:100] if error else "",
                    )

    def get_status(self) -> Dict[str, Any]:
        """Get status of all circuit breakers"""
        return {
            key: {
                "state": state.state.value,
                "failure_count": state.failure_count,
                "last_failure": state.last_failure_time,
                "last_success": state.last_success_time,
            }
            for key, state in self._states.items()
        }

    def reset(self, config: Optional[LLMConfig] = None):
        """Reset circuit breaker state"""
        if config:
            key = self._get_provider_key(config)
            if key in self._states:
                self._states[key] = CircuitBreakerState()
        else:
            self._states.clear()
            self._half_open_requests.clear()


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker()


# ============================================================================
# LLM PRICING (per 1K tokens, USD)
# ============================================================================

LLM_PRICING: Dict[str, Dict[str, float]] = {
    # OpenAI
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    # Anthropic
    "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
    "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    # Azure (same as OpenAI)
    "azure/gpt-4": {"input": 0.03, "output": 0.06},
    "azure/gpt-4-turbo": {"input": 0.01, "output": 0.03},
    # Groq (free tier, estimate)
    "llama-3.1-70b-versatile": {"input": 0.0, "output": 0.0},
    "llama-3.1-8b-instant": {"input": 0.0, "output": 0.0},
    # Together AI
    "meta-llama/Llama-3-70b-chat-hf": {"input": 0.0009, "output": 0.0009},
    # Mistral
    "mistral-large-latest": {"input": 0.004, "output": 0.012},
    # DeepSeek
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    # Default fallback for unknown models
    "_default": {"input": 0.001, "output": 0.002},
}


@dataclass
class LLMUsageData:
    """Token usage and cost data from LLM call"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0
    cached: bool = False
    # Anthropic prompt-caching metrics. LiteLLM passes these through
    # from ``response.usage`` when the model supports prompt caching;
    # they stay 0 for providers that don't (OpenAI, OAuth gateway).
    # Pure observability — no ``cache_control`` injection yet. The
    # ``cached`` boolean is computed as ``cache_read_input_tokens > 0``
    # so existing dashboards keep working.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "cost_usd": round(self.cost_usd, 6),
            "cached": self.cached,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
        }


def _attach_cache_metrics(usage: LLMUsageData, response: Any) -> LLMUsageData:
    """
    Defensively read Anthropic prompt-cache metrics from a LiteLLM
    response object and attach them to the usage dataclass. Safe
    no-op when:
      - ``response.usage`` is missing (older LiteLLM, error path)
      - the provider doesn't support prompt caching (OpenAI, etc.)
      - the model didn't hit a cache breakpoint this request

    Sets ``cached=True`` whenever ``cache_read_input_tokens > 0`` so
    the existing ``LLMMetricsTracker.cache_hits`` counter actually
    counts Anthropic cache reads instead of always incrementing
    cache_misses.
    """
    response_usage = getattr(response, "usage", None)
    if response_usage is None:
        return usage
    usage.cache_creation_input_tokens = int(
        getattr(response_usage, "cache_creation_input_tokens", 0) or 0
    )
    usage.cache_read_input_tokens = int(
        getattr(response_usage, "cache_read_input_tokens", 0) or 0
    )
    if usage.cache_read_input_tokens > 0:
        usage.cached = True
    return usage


def _attach_cache_metrics_from_dict(
    usage: LLMUsageData, usage_dict: Optional[Dict[str, Any]]
) -> LLMUsageData:
    """
    Same as ``_attach_cache_metrics`` but for the OAuth-gateway path,
    which receives an OpenAI-shaped JSON dict instead of a LiteLLM
    response object. Reads the same Anthropic field names defensively.
    Gateway must forward Anthropic's ``cache_creation_input_tokens`` /
    ``cache_read_input_tokens`` into ``data.usage`` for these to be
    populated; otherwise stays 0.
    """
    if not usage_dict:
        return usage
    usage.cache_creation_input_tokens = int(
        usage_dict.get("cache_creation_input_tokens", 0) or 0
    )
    usage.cache_read_input_tokens = int(
        usage_dict.get("cache_read_input_tokens", 0) or 0
    )
    if usage.cache_read_input_tokens > 0:
        usage.cached = True
    return usage


# Global metrics tracking
@dataclass
class LLMMetricsTracker:
    """Track cumulative LLM usage metrics"""

    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    # Aggregate Anthropic cache-token accounting so /metrics/detailed
    # can show "we saved X tokens via prompt caching" before any
    # decision on explicit ``cache_control`` injection.
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0

    def record_usage(self, usage: LLMUsageData, latency_ms: float = 0):
        self.total_requests += 1
        if usage.cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        self.total_prompt_tokens += usage.prompt_tokens
        self.total_completion_tokens += usage.completion_tokens
        self.total_cost_usd += usage.cost_usd
        self.total_latency_ms += latency_ms
        # Tally per-call cache token accounting.
        self.total_cache_creation_tokens += usage.cache_creation_input_tokens
        self.total_cache_read_tokens += usage.cache_read_input_tokens

    def record_error(self):
        self.errors += 1

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.cache_hits / max(self.total_requests, 1),
            "errors": self.errors,
            "avg_latency_ms": self.total_latency_ms / max(self.total_requests, 1),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "estimated_cost_usd": round(self.total_cost_usd, 4),
            # Anthropic prompt-cache totals — stay 0 when no
            # Anthropic traffic. Tokens-saved estimate uses
            # Anthropic's published 90% discount on cached reads.
            "total_cache_creation_tokens": self.total_cache_creation_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "cache_token_savings_usd_estimate": round(
                self.total_cache_read_tokens * 0.9 * 0.000003, 4
            ),
        }


# Global metrics instance
_metrics_tracker = LLMMetricsTracker()


# ============================================================================
# TOOL CALLING SUPPORT
# ============================================================================


@dataclass
class ToolCall:
    """Represents a single tool call from LLM response."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolCallingResponse:
    """Response from LLM with potential tool calls."""
    content: Optional[str]
    tool_calls: List[ToolCall]
    has_tool_calls: bool
    usage: Optional[LLMUsageData]


def is_anthropic_model(model: str) -> bool:
    """
    Detect if the model is an Anthropic model.

    Anthropic models include:
    - Direct Anthropic API: claude-*
    - AWS Bedrock: anthropic.claude-*
    - OAuth Gateway with Bedrock: anthropic.claude-*
    """
    if not model:
        return False
    model_lower = model.lower()
    return (
        model_lower.startswith("claude-") or
        model_lower.startswith("anthropic.claude-") or
        "claude" in model_lower
    )


class ToolCallingService:
    """
    Service for making LLM calls with tool/function calling support.

    Uses LiteLLM for provider-agnostic tool calling.
    """

    @classmethod
    async def call_with_tools(
        cls,
        config: "LLMConfig",
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> ToolCallingResponse:
        """
        Call LLM with tools/functions.

        Args:
            config: LLM configuration
            messages: Conversation messages
            tools: Tool definitions in OpenAI format
            temperature: Sampling temperature
            max_tokens: Max response tokens

        Returns:
            ToolCallingResponse with content and/or tool calls
        """
        try:
            logger.info(
                "Tool calling LLM request",
                provider=config.provider,
                model=config.model,
            )

            # Route OAuth Gateway calls to custom handler
            if config.provider == "oauth_gateway":
                return await cls._call_oauth_gateway_with_tools(
                    config, messages, tools, temperature, max_tokens
                )

            model = LLMService._get_model_string(config)
            api_config = LLMService._get_api_config(config)

            logger.info(
                "LiteLLM tool calling",
                model_string=model,
            )

            response = await litellm.acompletion(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens,
                num_retries=2,
                request_timeout=settings.AGENT_TIMEOUT_SECONDS,
                **api_config,
            )

            # Extract content and tool calls
            message = response.choices[0].message
            content = message.content

            tool_calls = []
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    except json.JSONDecodeError:
                        args = {"raw": tc.function.arguments}

                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    ))

            # Build usage data
            usage = None
            if hasattr(response, "usage") and response.usage:
                usage = LLMUsageData(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    model=model,
                    cost_usd=cls._calculate_cost(response.usage, model),
                    cached=False,
                )
                # Attach Anthropic prompt-cache metrics (no-op for
                # non-Anthropic providers or when no breakpoint hit).
                _attach_cache_metrics(usage, response)
                if usage.cache_read_input_tokens > 0:
                    logger.info(
                        "llm.cache_read",
                        extra={
                            # Provider label so dashboards can
                            # disambiguate "Anthropic cache hit" from
                            # "non-Anthropic provider didn't expose
                            # the field" (both look like zero in the
                            # bare model_name view).
                            "provider": getattr(config, "provider", "unknown"),
                            "model": model,
                            "cache_read_input_tokens": usage.cache_read_input_tokens,
                            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                            "prompt_tokens": usage.prompt_tokens,
                        },
                    )

            return ToolCallingResponse(
                content=content,
                tool_calls=tool_calls,
                has_tool_calls=len(tool_calls) > 0,
                usage=usage,
            )

        except Exception as e:
            logger.error("Tool calling failed", error=str(e))
            raise

    @classmethod
    async def _call_oauth_gateway_with_tools(
        cls,
        config: "LLMConfig",
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> "ToolCallingResponse":
        """
        Call OAuth Gateway with tool/function calling support.

        OAuth Gateway endpoints that support OpenAI-compatible tool calling.
        """
        import httpx

        from app.services.token_manager import token_manager

        logger.info(
            "OAuth Gateway tool calling",
            model=config.model,
            base_url=config.base_url,
        )

        # Get OAuth token
        token = await token_manager.get_token(config)

        # Build endpoint URL
        endpoint = config.chat_endpoint or "/v1/chat/completions"
        if not endpoint.startswith("http"):
            base_url = config.base_url or ""
            endpoint = f"{base_url.rstrip('/')}{endpoint}"

        # Validate and clean messages before sending
        # Some OAuth Gateways have strict requirements
        validated_messages = []
        for msg in messages:
            if msg.get("role") == "assistant":
                # Ensure assistant messages have content (even if empty string)
                if "content" not in msg or msg["content"] is None:
                    msg = dict(msg)
                    msg["content"] = ""
                # If has tool_calls, ensure it's a non-empty list
                if "tool_calls" in msg and not msg["tool_calls"]:
                    msg = dict(msg)
                    del msg["tool_calls"]  # Remove empty tool_calls array
            validated_messages.append(msg)

        payload = {
            "model": config.model,
            "messages": validated_messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Log message structure to help diagnose gateway errors
        logger.info(
            "OAuth Gateway request payload summary",
            message_count=len(validated_messages),
            message_roles=[m.get("role") for m in validated_messages],
            tool_count=len(tools) if tools else 0,
        )

        # Log first tool structure for debugging format issues
        if tools and len(tools) > 0:
            logger.info(
                "OAuth Gateway first tool structure",
                tool_sample=json.dumps(tools[0], indent=2)[:500]
            )

        # Detailed logging for troubleshooting gateway "list index out of range" errors
        for i, msg in enumerate(validated_messages):
            role = msg.get("role")
            has_tool_calls = "tool_calls" in msg and msg["tool_calls"]
            tool_call_id = msg.get("tool_call_id") if role == "tool" else None
            content_preview = (msg.get("content") or "")[:100] if msg.get("content") else "(empty)"

            # Log full message structure for debugging (truncate content)
            msg_copy = dict(msg)
            if "content" in msg_copy and isinstance(msg_copy["content"], str) and len(msg_copy["content"]) > 200:
                msg_copy["content"] = msg_copy["content"][:200] + "... (truncated)"

            logger.info(
                f"OAuth Gateway Message [{i}]",
                role=role,
                has_tool_calls=has_tool_calls,
                tool_call_count=len(msg["tool_calls"]) if has_tool_calls else 0,
                tool_call_id=tool_call_id,
                content_preview=content_preview,
                full_structure=json.dumps(msg_copy, indent=2)[:1000],
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=settings.AGENT_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)

                # Handle token expiry
                if response.status_code == 401:
                    logger.warning("OAuth token expired, refreshing")
                    token_manager.invalidate_token(config)
                    token = await token_manager.get_token(config)
                    headers["Authorization"] = f"Bearer {token}"
                    response = await client.post(endpoint, json=payload, headers=headers)

                response.raise_for_status()
                data = response.json()

                content = None
                tool_calls: List[ToolCall] = []

                # OAuth Gateway returns OpenAI format (it converts Anthropic responses internally)
                # Always parse as OpenAI format
                message = data.get("choices", [{}])[0].get("message", {})
                content = message.get("content")

                if message.get("tool_calls"):
                    for tc in message["tool_calls"]:
                        try:
                            args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                        except json.JSONDecodeError:
                            args = {"raw": tc["function"]["arguments"]}

                        tool_calls.append(ToolCall(
                            id=tc.get("id", f"call_{len(tool_calls)}"),
                            name=tc["function"]["name"],
                            arguments=args,
                        ))

                # Extract usage
                usage = None
                if "usage" in data:
                    usage = LLMUsageData(
                        prompt_tokens=data["usage"].get("prompt_tokens", 0),
                        completion_tokens=data["usage"].get("completion_tokens", 0),
                        total_tokens=data["usage"].get("total_tokens", 0),
                        model=config.model or "unknown",
                        cost_usd=0,  # OAuth gateway doesn't report cost
                        cached=False,
                    )
                    # Attach cache metrics from the gateway's OpenAI-
                    # shaped JSON. Gateway must forward Anthropic's
                    # cache token fields for these to be populated.
                    _attach_cache_metrics_from_dict(usage, data["usage"])
                    if usage.cache_read_input_tokens > 0:
                        logger.info(
                            "llm.cache_read",
                            extra={
                                # Always include provider so dashboards
                                # never confuse "Anthropic cache hit
                                # via gateway" with "OpenAI provider
                                # with no cache support".
                                "provider": getattr(config, "provider", "oauth_gateway"),
                                "model": config.model or "unknown",
                                "transport": "oauth_gateway",
                                "cache_read_input_tokens": usage.cache_read_input_tokens,
                                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                                "prompt_tokens": usage.prompt_tokens,
                            },
                        )

                logger.info(
                    "OAuth Gateway tool calling completed",
                    model=config.model,
                    has_tool_calls=len(tool_calls) > 0,
                    tool_count=len(tool_calls),
                )

                return ToolCallingResponse(
                    content=content,
                    tool_calls=tool_calls,
                    has_tool_calls=len(tool_calls) > 0,
                    usage=usage,
                )

            except httpx.HTTPStatusError as e:
                logger.error(
                    "OAuth Gateway tool calling error",
                    status_code=e.response.status_code,
                    response=e.response.text[:500],
                )
                raise Exception(f"OAuth gateway tool calling error: {e.response.status_code}")
            except Exception as e:
                logger.error("OAuth Gateway tool calling failed", error=str(e))
                raise

    @staticmethod
    def _calculate_cost(usage, model: str) -> float:
        """Estimate cost based on token usage."""
        cost_per_1k = {
            "gpt-4": (0.03, 0.06),
            "gpt-4o": (0.005, 0.015),
            "gpt-4o-mini": (0.00015, 0.0006),
            "claude-3-opus": (0.015, 0.075),
            "claude-3-sonnet": (0.003, 0.015),
            "claude-3-haiku": (0.00025, 0.00125),
        }

        input_cost_per_1k = 0.01
        output_cost_per_1k = 0.03

        for model_prefix, (input_c, output_c) in cost_per_1k.items():
            if model_prefix in model.lower():
                input_cost_per_1k = input_c
                output_cost_per_1k = output_c
                break

        input_cost = (usage.prompt_tokens / 1000) * input_cost_per_1k
        output_cost = (usage.completion_tokens / 1000) * output_cost_per_1k

        return round(input_cost + output_cost, 6)


def is_complex_query_for_routing(question: str, db_type: str) -> bool:
    """
    Determine if a query is complex enough to require the main model.

    This is used for complexity-based model routing to decide between
    fast_model (for simple queries) and model (for complex queries).

    Args:
        question: Natural language question
        db_type: Database type (postgresql, mongodb, etc.)

    Returns:
        True if the query is complex and should use the main model
    """
    # Import complexity detection from prompt providers
    from app.services.prompt_providers.mongodb import is_complex_mongodb_query
    from app.services.prompt_providers.sql import is_complex_query

    if db_type.lower() == "mongodb":
        return is_complex_mongodb_query(question)
    else:
        return is_complex_query(question)


class LLMService:
    """
    Unified LLM service using LiteLLM.

    Features:
    - All providers via single interface
    - Built-in retries (via LiteLLM)
    - Response caching
    - OAuth gateway support
    - Database-specific prompts via PromptProvider registry
    - Complexity-based model routing
    """

    # Legacy explain prompt (for backwards compatibility)
    # New code should use PromptProvider.get_explain_prompt()
    EXPLAIN_PROMPT = """Explain this query in plain English for a business user. Be concise and clear.

SQL Query:
```sql
{sql}
```

Database Schema:
{schema}

Format your response using this EXACT structure with proper line breaks:

**Summary:**
[One clear sentence describing what this query finds/calculates]

**How it works:**
- [First step - what data is being accessed]
- [Second step - any filtering or conditions]
- [Third step - any grouping or calculations]

**Results:**
[Brief description of output columns and what each means]

IMPORTANT FORMATTING RULES:
- Each section header (Summary, How it works, Results) MUST be on its own line
- Each bullet point MUST start on a new line with "- " prefix
- Use simple business language, not technical SQL terms
- Keep each point to 1-2 sentences max
- Focus on WHAT the query does, not HOW SQL works
- Skip steps that don't apply (e.g., no bullet for JOINs if there are none)"""

    @classmethod
    def _get_cache_service(cls):
        """Lazy import to avoid circular dependency"""
        try:
            from app.services.cache_service import cache_service

            return cache_service
        except ImportError:
            return None

    @classmethod
    def _hash_prompt(cls, prompt: str, schema: str, db_type: str) -> str:
        """Generate hash for caching"""
        content = f"{prompt}:{schema[:2000]}:{db_type}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    @classmethod
    def _calculate_cost(
        cls, model: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Calculate cost based on model and token counts"""
        # Try to find pricing for the model
        pricing = None

        # Direct match
        if model in LLM_PRICING:
            pricing = LLM_PRICING[model]
        else:
            # Try without provider prefix
            model_name = model.split("/")[-1] if "/" in model else model
            if model_name in LLM_PRICING:
                pricing = LLM_PRICING[model_name]
            else:
                # Try partial match
                for key in LLM_PRICING:
                    if key in model or model in key:
                        pricing = LLM_PRICING[key]
                        break

        # Fall back to default
        if not pricing:
            pricing = LLM_PRICING["_default"]

        input_cost = (prompt_tokens / 1000) * pricing["input"]
        output_cost = (completion_tokens / 1000) * pricing["output"]
        return input_cost + output_cost

    @classmethod
    def _extract_usage(cls, response, model: str) -> LLMUsageData:
        """Extract usage data from LiteLLM response"""
        usage = LLMUsageData(model=model)

        if hasattr(response, "usage") and response.usage:
            usage.prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
            usage.completion_tokens = (
                getattr(response.usage, "completion_tokens", 0) or 0
            )
            usage.total_tokens = getattr(response.usage, "total_tokens", 0) or (
                usage.prompt_tokens + usage.completion_tokens
            )

            # Calculate cost
            usage.cost_usd = cls._calculate_cost(
                model, usage.prompt_tokens, usage.completion_tokens
            )

            # Anthropic prompt-cache metrics. Defensive getattr —
            # no-op for non-Anthropic providers.
            _attach_cache_metrics(usage, response)

        return usage

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        """Get cumulative LLM metrics including cost"""
        return _metrics_tracker.get_metrics()

    @classmethod
    def _get_model_string(cls, config: LLMConfig) -> str:
        """
        Convert config to LiteLLM model string.
        LiteLLM uses format: provider/model

        See: https://docs.litellm.ai/docs/providers
        """
        provider_map = {
            # Major Cloud Providers
            "openai": f"openai/{config.model or 'gpt-4'}",
            "anthropic": f"anthropic/{config.model or 'claude-sonnet-4-20250514'}",
            "azure": f"azure/{config.model}",
            # AWS Bedrock
            "bedrock": f"bedrock/{config.model or 'anthropic.claude-3-sonnet-20240229-v1:0'}",
            # Google
            "vertex_ai": f"vertex_ai/{config.model or 'gemini-1.5-pro'}",
            "gemini": f"gemini/{config.model or 'gemini-1.5-pro'}",
            # Fast Inference
            "groq": f"groq/{config.model or 'llama-3.1-70b-versatile'}",
            # Local LLM
            "ollama": f"ollama/{config.model or 'llama3'}",
            # Open Source Model Providers
            "together": f"together_ai/{config.model or 'meta-llama/Llama-3-70b-chat-hf'}",
            "mistral": f"mistral/{config.model or 'mistral-large-latest'}",
            "cohere": f"cohere/{config.model or 'command-r-plus'}",
            "replicate": f"replicate/{config.model}",
            "deepseek": f"deepseek/{config.model or 'deepseek-chat'}",
            # Custom OpenAI-compatible endpoint (includes oauth_gateway)
            "custom": f"openai/{config.model}",
            "oauth_gateway": f"openai/{config.model}",  # OAuth gateway uses OpenAI-compatible API
        }

        model_string = provider_map.get(config.provider)
        if model_string is None:
            logger.warning(
                "Unknown LLM provider, falling back to OpenAI format",
                provider=config.provider,
                model=config.model,
            )
            model_string = f"openai/{config.model or 'gpt-4'}"

        return model_string

    @classmethod
    def _get_api_config(cls, config: LLMConfig) -> Dict[str, Any]:
        """
        Get API configuration for LiteLLM.

        Each provider may need specific configuration beyond just an API key.
        See: https://docs.litellm.ai/docs/providers
        """
        api_config = {}

        # ===== Major Cloud Providers =====
        if config.provider == "azure":
            api_config["api_base"] = config.base_url
            api_config["api_key"] = config.api_key
            api_config["api_version"] = "2024-02-15-preview"

        elif config.provider == "custom":
            api_config["api_base"] = config.base_url
            api_config["api_key"] = config.api_key or "none"

        # ===== AWS Bedrock =====
        # Uses boto3 credentials from environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        # base_url can be used to specify AWS region
        elif config.provider == "bedrock":
            if config.base_url:  # Region override
                api_config["aws_region_name"] = config.base_url

        # ===== Google Vertex AI =====
        # Uses Google Cloud credentials from environment (GOOGLE_APPLICATION_CREDENTIALS)
        # base_url = project ID, api_key = location
        elif config.provider == "vertex_ai":
            if config.base_url:  # Project ID
                api_config["vertex_project"] = config.base_url
            if config.api_key:  # Location (e.g., "us-central1")
                api_config["vertex_location"] = config.api_key

        # ===== Google Gemini (Direct API) =====
        elif config.provider == "gemini":
            if config.api_key:
                api_config["api_key"] = config.api_key

        # ===== Fast Inference (Groq) =====
        elif config.provider == "groq":
            if config.api_key:
                api_config["api_key"] = config.api_key

        # ===== Local LLM (Ollama) =====
        # No API key needed, just base URL
        elif config.provider == "ollama":
            api_config["api_base"] = config.base_url or "http://localhost:11434"

        # ===== Open Source Model Providers =====
        elif config.provider == "together":
            if config.api_key:
                api_config["api_key"] = config.api_key

        elif config.provider == "mistral":
            if config.api_key:
                api_config["api_key"] = config.api_key

        elif config.provider == "cohere":
            if config.api_key:
                api_config["api_key"] = config.api_key

        elif config.provider == "replicate":
            if config.api_key:
                api_config["api_key"] = config.api_key

        elif config.provider == "deepseek":
            if config.api_key:
                api_config["api_key"] = config.api_key
            api_config["api_base"] = config.base_url or "https://api.deepseek.com"

        # ===== Default: OpenAI and Anthropic =====
        elif config.api_key:
            api_config["api_key"] = config.api_key

        return api_config

    @classmethod
    async def generate_sql(
        cls,
        config: LLMConfig,
        prompt: str,
        schema: str,
        history: List[Dict],
        db_type: str = "postgresql",
        stream: bool = False,
        few_shot_examples: Optional[List[Dict]] = None,
    ) -> Tuple[Any, Optional[LLMUsageData]]:
        """
        Generate SQL from natural language.

        Args:
            config: LLM configuration
            prompt: Natural language question
            schema: Database schema
            history: Conversation history
            db_type: Database type
            stream: If True, returns async generator yielding chunks.
                    If False, returns complete SQL string.
            few_shot_examples: Optional list of similar query examples for few-shot learning.
                               Each dict should have 'natural_query' and 'sql' keys.

        Returns:
            Tuple of (generated SQL query or async generator, usage data).
            For streaming, usage_data is None.
        """
        # Start tracing span for the entire operation
        span = _tracer.start_span("llm.generate_sql")
        span.set_attribute("llm.provider", config.provider)
        span.set_attribute("llm.model", config.model or "default")
        span.set_attribute("llm.db_type", db_type)
        span.set_attribute("llm.stream", stream)
        span.set_attribute("llm.prompt_length", len(prompt))

        try:
            # 1. Check cache (skip for streaming - can't cache partial responses)
            if not stream:
                cache_service = cls._get_cache_service()
                prompt_hash = cls._hash_prompt(prompt, schema, db_type)

                if cache_service:
                    try:
                        cached = await cache_service.get_llm_response(prompt_hash)
                        if cached:
                            logger.debug("LLM cache hit", prompt_hash=prompt_hash[:16])
                            # Return cached with usage indicating cache hit
                            cached_usage = LLMUsageData(
                                cached=True, model=config.model or "unknown"
                            )
                            _metrics_tracker.record_usage(cached_usage)
                            span.set_attribute("llm.cache_hit", True)
                            return cached, cached_usage
                    except Exception as e:
                        logger.warning("Cache read error", error=str(e))

            # 2. Complexity-based model routing
            # Use fast_model for simple queries, main model for complex ones
            effective_config = config
            if config.enable_complexity_routing and config.fast_model:
                is_complex = is_complex_query_for_routing(prompt, db_type)
                if not is_complex:
                    # Simple query - use fast model
                    effective_config = copy.copy(config)
                    effective_config.model = config.fast_model
                    logger.debug(
                        "Complexity routing: using fast model",
                        model=config.fast_model,
                        query_preview=prompt[:50],
                    )
                else:
                    logger.debug(
                        "Complexity routing: using main model",
                        model=config.model,
                        query_preview=prompt[:50],
                    )

            # 3. Format conversation history
            history_text = (
                "\n".join(
                    [
                        f"User: {h.get('user', h.get('query', ''))[:300]}\n"
                        f"Query: {h.get('sql', '')[:500]}\n"
                        f"Answer: {h.get('answer', 'N/A')[:200]}"
                        for h in (history or [])[-5:]  # Last 5 exchanges
                    ]
                )
                if history
                else "No previous conversation"
            )

            # 4. Get database-specific prompt provider
            prompt_provider = get_prompt_provider(db_type)
            system_prompt = prompt_provider.get_system_prompt(
                schema=schema[: settings.MAX_SCHEMA_TOKENS * 4],
                history=history_text,
                db_type=db_type,  # Pass for SQL dialects that need it
                few_shot_examples=few_shot_examples
                or [],  # Pass few-shot examples for learning
                question=prompt,  # Pass user question for complexity detection (CoT)
            )

            # 5. Build messages
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            # 6. Call LLM with effective config (may have fast_model for simple queries)
            if effective_config.provider == "oauth_gateway":
                response, usage = await cls._call_oauth_gateway(
                    effective_config, messages, stream=stream
                )
            else:
                response, usage = await cls._call_litellm(
                    effective_config, messages, stream=stream
                )

            # 7. For streaming, return generator directly (caller handles cleaning)
            if stream:
                return response, None

            # 8. Clean response using database-specific provider
            sql = prompt_provider.clean_response(response)

            # 9. Cache the cleaned response (non-streaming only)
            cache_service = cls._get_cache_service()
            prompt_hash = cls._hash_prompt(prompt, schema, db_type)
            if cache_service and sql:
                try:
                    await cache_service.set_llm_response(
                        prompt_hash, sql, ttl=settings.CACHE_TTL_LLM
                    )
                except Exception as e:
                    logger.warning("Cache write error", error=str(e))

            # Record usage in span
            if usage:
                span.set_attribute("llm.tokens.input", usage.prompt_tokens)
                span.set_attribute("llm.tokens.output", usage.completion_tokens)
                span.set_attribute("llm.cost_usd", usage.cost_usd)

            return sql, usage

        except Exception as e:
            span.record_exception(e)
            raise
        finally:
            span.end()

    @classmethod
    async def explain_sql(
        cls,
        config: LLMConfig,
        sql: str,
        schema: str,
        db_type: str = "postgresql",
        stream: bool = False,
    ) -> Tuple[Any, Optional[LLMUsageData]]:
        """
        Explain query in plain language.

        Args:
            config: LLM configuration
            sql: Query to explain
            schema: Database schema
            db_type: Database type (for database-specific explanations)
            stream: If True, returns async generator yielding chunks.
                    If False, returns complete explanation string.

        Returns:
            Tuple of (content, usage_data). For streaming, usage_data is None.
        """
        # Use database-specific explain prompt
        prompt_provider = get_prompt_provider(db_type)
        prompt = prompt_provider.get_explain_prompt(sql, schema[:4000])

        query_lang = prompt_provider.QUERY_LANGUAGE
        messages = [
            {
                "role": "system",
                "content": f"You are a helpful {query_lang} expert who explains queries in simple, clear terms.",
            },
            {"role": "user", "content": prompt},
        ]

        if config.provider == "oauth_gateway":
            return await cls._call_oauth_gateway(
                config, messages, temperature=0.3, stream=stream
            )
        else:
            return await cls._call_litellm(
                config, messages, temperature=0.3, stream=stream
            )

    @classmethod
    def _parse_sse_chunk(cls, line: str) -> str:
        """Parse a single SSE line and extract content."""
        if not line or not line.startswith("data:"):
            return ""

        data = line[5:].strip()
        if data == "[DONE]":
            return ""

        try:
            import json

            parsed = json.loads(data)
            # OpenAI format
            if "choices" in parsed and parsed["choices"]:
                delta = parsed["choices"][0].get("delta", {})
                return delta.get("content", "")
            return ""
        except (json.JSONDecodeError, KeyError, IndexError):
            return ""

    @classmethod
    async def _call_litellm(
        cls,
        config: LLMConfig,
        messages: List[Dict],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        stream: bool = False,
    ) -> Tuple[Any, Optional[LLMUsageData]]:
        """
        Call LLM via LiteLLM library.

        Handles: OpenAI, Anthropic, Azure, custom OpenAI-compatible endpoints.
        Includes circuit breaker protection against provider failures.

        Args:
            stream: If True, returns async generator yielding text chunks.
                    If False, returns complete response string.

        Returns:
            Tuple of (content, usage_data). For streaming, usage_data is None.
        """
        # Check circuit breaker
        can_proceed, reason = _circuit_breaker.can_execute(config)
        if not can_proceed:
            raise Exception(f"LLM provider unavailable: {reason}")

        start_time = time.time()

        model = cls._get_model_string(config)
        api_config = cls._get_api_config(config)

        try:
            response = await acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                num_retries=3,
                request_timeout=settings.AGENT_TIMEOUT_SECONDS,
                stream=stream,
                **api_config,
            )

            if stream:
                # Return async generator for streaming (no usage data available)
                # Note: Circuit breaker tracks via finally to handle abandoned streams
                async def generate():
                    recorded = False
                    try:
                        async for chunk in response:
                            if chunk.choices and chunk.choices[0].delta.content:
                                yield chunk.choices[0].delta.content
                        # Record success after stream completes
                        _circuit_breaker.record_success(config)
                        recorded = True
                    except GeneratorExit:
                        # Client disconnected / generator abandoned
                        # Record as failure to decrement counter (prevents stuck HALF_OPEN)
                        if not recorded:
                            _circuit_breaker.record_failure(config, "Stream abandoned")
                            recorded = True
                        raise
                    except Exception as e:
                        if not recorded:
                            _circuit_breaker.record_failure(config, str(e))
                            recorded = True
                        raise
                    finally:
                        # Fallback: ensure counter is decremented if not already recorded
                        if not recorded:
                            _circuit_breaker.record_failure(config, "Stream cleanup")

                return generate(), None
            else:
                # Record success
                _circuit_breaker.record_success(config)

                # Extract usage data
                usage = cls._extract_usage(response, model)
                latency_ms = (time.time() - start_time) * 1000

                # Log usage with structured logging
                logger.info(
                    "LLM call completed",
                    provider=config.provider,
                    model=model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=round(usage.cost_usd, 6),
                    latency_ms=round(latency_ms, 2),
                )

                # Track metrics
                _metrics_tracker.record_usage(usage, latency_ms)

                # Record Prometheus metrics
                record_llm_request(
                    provider=config.provider,
                    model=model,
                    status="success",
                    duration_seconds=latency_ms / 1000,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    cache_hit=False,
                    cost_usd=usage.cost_usd,
                )

                return response.choices[0].message.content.strip(), usage

        except Exception as e:
            # Record failure for circuit breaker
            _circuit_breaker.record_failure(config, str(e))
            _metrics_tracker.record_error()

            # Record Prometheus error metric
            record_llm_request(
                provider=config.provider,
                model=model,
                status="error",
                duration_seconds=(time.time() - start_time),
                cache_hit=False,
            )

            logger.error(
                "LiteLLM error",
                provider=config.provider,
                model=model,
                error=str(e),
            )
            raise Exception(
                f"LLM {'streaming ' if stream else ''}request failed: {str(e)}"
            )

    @classmethod
    async def _call_oauth_gateway(
        cls,
        config: LLMConfig,
        messages: List[Dict],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        stream: bool = False,
    ) -> Tuple[Any, Optional[LLMUsageData]]:
        """
        Call LLM through corporate OAuth gateway.

        LiteLLM doesn't support OAuth natively, so we handle it manually.

        Args:
            stream: If True, returns async generator yielding text chunks.
                    If False, returns complete response string.

        Returns:
            Tuple of (content, usage_data). For streaming, usage_data is None.
        """
        import time

        import httpx

        from app.services.token_manager import token_manager

        # Check circuit breaker before making request
        can_execute, reason = _circuit_breaker.can_execute(config)
        if not can_execute:
            _metrics_tracker.record_error()
            raise Exception(f"OAuth gateway circuit breaker open: {reason}")

        start_time = time.time()

        # Get OAuth token
        token = await token_manager.get_token(config)

        # Build endpoint URL
        endpoint = config.chat_endpoint or "/v1/chat/completions"
        if not endpoint.startswith("http"):
            base_url = config.base_url or ""
            endpoint = f"{base_url.rstrip('/')}{endpoint}"

        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        if stream:
            headers["Accept"] = "text/event-stream"
            generator = await cls._oauth_gateway_stream(
                config, endpoint, payload, headers, token_manager
            )
            return generator, None

        # Non-streaming request
        async with httpx.AsyncClient(timeout=settings.AGENT_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)

                # Handle token expiry
                if response.status_code == 401:
                    logger.warning("OAuth token expired, refreshing")
                    token_manager.invalidate_token(config)
                    token = await token_manager.get_token(config)
                    headers["Authorization"] = f"Bearer {token}"
                    response = await client.post(
                        endpoint, json=payload, headers=headers
                    )

                response.raise_for_status()
                data = response.json()

                # Extract usage from OAuth gateway response
                usage = LLMUsageData(model=config.model or "unknown")
                if "usage" in data:
                    usage.prompt_tokens = data["usage"].get("prompt_tokens", 0)
                    usage.completion_tokens = data["usage"].get("completion_tokens", 0)
                    usage.total_tokens = data["usage"].get("total_tokens", 0)
                    usage.cost_usd = cls._calculate_cost(
                        config.model or "unknown",
                        usage.prompt_tokens,
                        usage.completion_tokens,
                    )

                latency_ms = (time.time() - start_time) * 1000

                # Log usage
                logger.info(
                    "OAuth gateway call completed",
                    model=config.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=round(usage.cost_usd, 6),
                    latency_ms=round(latency_ms, 2),
                )

                _metrics_tracker.record_usage(usage, latency_ms)

                # Record success for circuit breaker
                _circuit_breaker.record_success(config)

                # Record Prometheus metrics
                record_llm_request(
                    provider="oauth_gateway",
                    model=config.model or "unknown",
                    status="success",
                    duration_seconds=latency_ms / 1000,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    cache_hit=False,
                    cost_usd=usage.cost_usd,
                )

                return cls._extract_response(data), usage

            except httpx.TimeoutException:
                _circuit_breaker.record_failure(config, "Timeout")
                _metrics_tracker.record_error()
                record_llm_request(
                    provider="oauth_gateway",
                    model=config.model or "unknown",
                    status="error",
                    duration_seconds=(time.time() - start_time),
                    cache_hit=False,
                )
                raise Exception("OAuth gateway request timed out")
            except httpx.HTTPStatusError as e:
                _circuit_breaker.record_failure(
                    config, f"HTTP {e.response.status_code}"
                )
                _metrics_tracker.record_error()
                record_llm_request(
                    provider="oauth_gateway",
                    model=config.model or "unknown",
                    status="error",
                    duration_seconds=(time.time() - start_time),
                    cache_hit=False,
                )
                raise Exception(f"OAuth gateway error: {e.response.status_code}")
            except Exception as e:
                _circuit_breaker.record_failure(config, str(e))
                _metrics_tracker.record_error()
                record_llm_request(
                    provider="oauth_gateway",
                    model=config.model or "unknown",
                    status="error",
                    duration_seconds=(time.time() - start_time),
                    cache_hit=False,
                )
                logger.error("OAuth Gateway error", error=str(e))
                raise Exception(f"OAuth gateway request failed: {str(e)}")

    @classmethod
    async def _oauth_gateway_stream(
        cls,
        config: LLMConfig,
        endpoint: str,
        payload: Dict,
        headers: Dict,
        token_manager,
    ):
        """
        Stream LLM response through corporate OAuth gateway.

        Returns async generator yielding text chunks via SSE.
        """
        import httpx

        async def generate():
            recorded = False
            async with httpx.AsyncClient(
                timeout=settings.AGENT_TIMEOUT_SECONDS
            ) as client:
                try:
                    async with client.stream(
                        "POST", endpoint, json=payload, headers=headers
                    ) as response:
                        if response.status_code == 401:
                            # Token expired - refresh and retry
                            token_manager.invalidate_token(config)
                            token = await token_manager.get_token(config)
                            headers["Authorization"] = f"Bearer {token}"
                            async with client.stream(
                                "POST", endpoint, json=payload, headers=headers
                            ) as retry_response:
                                retry_response.raise_for_status()
                                async for line in retry_response.aiter_lines():
                                    chunk = cls._parse_sse_chunk(line)
                                    if chunk:
                                        yield chunk
                        else:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                chunk = cls._parse_sse_chunk(line)
                                if chunk:
                                    yield chunk

                    # Record success after stream completes without error
                    _circuit_breaker.record_success(config)
                    recorded = True

                except GeneratorExit:
                    # Client disconnected / generator abandoned
                    if not recorded:
                        _circuit_breaker.record_failure(config, "Stream abandoned")
                        recorded = True
                    raise
                except httpx.TimeoutException:
                    if not recorded:
                        _circuit_breaker.record_failure(config, "Streaming timeout")
                        recorded = True
                    raise Exception("OAuth gateway streaming request timed out")
                except httpx.HTTPStatusError as e:
                    if not recorded:
                        _circuit_breaker.record_failure(
                            config, f"Streaming HTTP {e.response.status_code}"
                        )
                        recorded = True
                    raise Exception(
                        f"OAuth gateway streaming error: {e.response.status_code}"
                    )
                except Exception as e:
                    if not recorded:
                        _circuit_breaker.record_failure(config, str(e))
                        recorded = True
                    logger.error("OAuth Gateway streaming error", error=str(e))
                    raise Exception(f"OAuth gateway streaming request failed: {str(e)}")
                finally:
                    # Fallback: ensure counter is decremented if not already recorded
                    if not recorded:
                        _circuit_breaker.record_failure(config, "Stream cleanup")

        return generate()

    @classmethod
    def _extract_response(cls, data: dict) -> str:
        """Extract text response from various API formats"""
        # OpenAI/Azure format
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        # Anthropic format
        if "content" in data:
            return data["content"][0]["text"].strip()
        # Generic
        if "response" in data:
            return data["response"].strip()
        if "text" in data:
            return data["text"].strip()

        raise ValueError("Unable to extract response from LLM output")

    @classmethod
    def clean_sql_response(cls, response: str, db_type: str = "postgresql") -> str:
        """
        Clean up query response from LLM.

        Delegates to database-specific PromptProvider for proper handling.
        This method is kept for backward compatibility.

        Args:
            response: Raw LLM response
            db_type: Database type

        Returns:
            Cleaned query string
        """
        prompt_provider = get_prompt_provider(db_type)
        return prompt_provider.clean_response(response)


# ============================================================================
# ALIASES FOR BACKWARD COMPATIBILITY
# ============================================================================

# Alias for sql_agent.py which imports SimpleLLMService
SimpleLLMService = LLMService


# ============================================================================
# FALLBACK CONFIGURATION
# ============================================================================

FALLBACK_MODELS = {
    "default": [
        "openai/gpt-4",
        "anthropic/claude-sonnet-4-20250514",
        "openai/gpt-3.5-turbo",
    ],
    "fast": ["openai/gpt-3.5-turbo", "anthropic/claude-3-haiku-20240307"],
    "smart": ["anthropic/claude-opus-4-20250514", "openai/gpt-4-turbo", "openai/gpt-4"],
}


async def completion_with_fallback(
    messages: List[Dict], model_tier: str = "default", **kwargs
) -> str:
    """
    Make LLM call with automatic fallbacks.

    Usage:
        result = await completion_with_fallback(messages, model_tier="fast")
    """
    models = FALLBACK_MODELS.get(model_tier, FALLBACK_MODELS["default"])

    last_error = None
    for model in models:
        try:
            response = await acompletion(
                model=model,
                messages=messages,
                num_retries=2,
                request_timeout=settings.AGENT_TIMEOUT_SECONDS,
                **kwargs,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning("Model failed, trying next", model=model, error=str(e))
            last_error = e
            continue

    raise last_error or Exception("All models failed")


# ============================================================================
# LITELLM INITIALIZATION
# ============================================================================


def setup_litellm():
    """
    Configure LiteLLM on startup.
    Called from main.py lifespan.
    """
    litellm.num_retries = 3
    litellm.request_timeout = settings.AGENT_TIMEOUT_SECONDS
    litellm.drop_params = True  # Ignore unsupported params
    litellm.set_verbose = settings.DEBUG

    logger.info("LiteLLM configured", timeout=settings.AGENT_TIMEOUT_SECONDS, retries=3)
