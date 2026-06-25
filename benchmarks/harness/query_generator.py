"""
QueryfyAI Benchmarks - Query Generator

Implements the ``QueryGenerator`` protocol defined in ``core.runner``.
Sends natural-language questions through the backend LLM service and
captures the generated query.

Two modes:
- ``DirectQueryGenerator``: calls ``LLMService.generate_sql`` directly
  (fast, tests generation quality in isolation).
- ``ChatAPIQueryGenerator``: calls the ``/api/v1/chat`` HTTP endpoint
  (tests the full system including ReAct agent and self-correction).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, Optional

from benchmarks.core.types import BenchmarkCase

logger = logging.getLogger(__name__)

# Ensure the backend package is importable
_backend_root = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _backend_root not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_root))


class DirectQueryGenerator:
    """Generate queries by calling LLMService directly.

    Bypasses the session / security / caching layers to test pure
    generation quality.  Supports all 15 LLM providers including
    oauth_gateway, azure, ollama, bedrock, and custom.

    Args:
        provider: LLM provider name (e.g. ``"openai"``, ``"oauth_gateway"``).
        model: Model identifier (e.g. ``"gpt-4o"``).
        api_key: API key string.  Falls back to the ``OPENAI_API_KEY``
            environment variable when not provided.
        temperature: Sampling temperature.
        base_url: Base URL for azure, ollama, bedrock, custom, deepseek.
        token_url: OAuth2 token endpoint (oauth_gateway).
        client_id: OAuth2 client ID (oauth_gateway).
        client_secret: OAuth2 client secret (oauth_gateway).
        auth_scope: OAuth2 scope (oauth_gateway).
        auth_type: OAuth2 grant type (oauth_gateway).
        tenant: Tenant identifier (oauth_gateway).
        star: Star identifier (oauth_gateway).
        chat_endpoint: Chat endpoint path (oauth_gateway).
        fast_model: Faster model for complexity routing.
        enable_complexity_routing: Enable automatic model selection.
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        temperature: float = 0.0,
        base_url: Optional[str] = None,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        auth_scope: Optional[str] = None,
        auth_type: Optional[str] = "client_credentials",
        tenant: Optional[str] = None,
        star: Optional[str] = None,
        chat_endpoint: Optional[str] = None,
        fast_model: Optional[str] = None,
        enable_complexity_routing: bool = False,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.temperature = temperature
        self.base_url = base_url
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_scope = auth_scope
        self.auth_type = auth_type
        self.tenant = tenant
        self.star = star
        self.chat_endpoint = chat_endpoint
        self.fast_model = fast_model
        self.enable_complexity_routing = enable_complexity_routing

    async def generate(self, case: BenchmarkCase) -> Dict[str, Any]:
        """Generate a query for *case* using the LLM service.

        Returns:
            Dictionary with ``query``, ``tokens_used``, ``cost_usd``,
            and ``error`` keys.
        """
        try:
            from app.services.llm_service import LLMService
        except ImportError as exc:
            return {"query": None, "error": f"Backend import failed: {exc}"}

        # Determine db_type string from the DatabaseCategory enum
        db_type = case.db_type.value if hasattr(case.db_type, "value") else str(case.db_type)
        # Map category to executor db_type
        db_type_map = {
            "sql": "sqlite",
            "nosql_document": "mongodb",
            "nosql_wide_column": "cassandra",
            "nosql_key_value": "dynamodb",
        }
        executor_db_type = db_type_map.get(db_type, db_type)

        # Build schema context
        schema = case.schema_context or ""

        # Include evidence (BIRD external knowledge) in the prompt
        nl = case.natural_language
        if case.evidence:
            nl = f"{nl}\n\nAdditional context: {case.evidence}"

        try:
            # Build LLMConfig with all provider-specific fields
            from app.models.schemas import LLMConfig

            llm_kwargs: Dict[str, Any] = {
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
            }
            # Add optional fields only when set (avoids overriding defaults)
            if self.base_url:
                llm_kwargs["base_url"] = self.base_url
            if self.token_url:
                llm_kwargs["token_url"] = self.token_url
            if self.client_id:
                llm_kwargs["client_id"] = self.client_id
            if self.client_secret:
                llm_kwargs["client_secret"] = self.client_secret
            if self.auth_scope:
                llm_kwargs["auth_scope"] = self.auth_scope
            if self.auth_type:
                llm_kwargs["auth_type"] = self.auth_type
            if self.tenant:
                llm_kwargs["tenant"] = self.tenant
            if self.star:
                llm_kwargs["star"] = self.star
            if self.chat_endpoint:
                llm_kwargs["chat_endpoint"] = self.chat_endpoint
            if self.fast_model:
                llm_kwargs["fast_model"] = self.fast_model
            if self.enable_complexity_routing:
                llm_kwargs["enable_complexity_routing"] = True

            llm_config = LLMConfig(**llm_kwargs)

            raw_sql, usage = await LLMService.generate_sql(
                config=llm_config,
                prompt=nl,
                schema=schema,
                history=[],
                db_type=executor_db_type,
            )

            predicted = LLMService.clean_sql_response(raw_sql, db_type=executor_db_type)
            tokens = usage.total_tokens if usage else 0
            cost = usage.cost_usd if usage else 0.0

            return {
                "query": predicted,
                "tokens_used": tokens,
                "cost_usd": cost,
                "error": None,
            }
        except Exception as exc:
            logger.error("LLM generation failed for %s: %s", case.case_id, exc)
            return {"query": None, "error": str(exc)}


class ChatAPIQueryGenerator:
    """Generate queries via the running backend HTTP API.

    Tests the full system including the ReAct agent, self-correction,
    tool usage, and security checks.

    Args:
        base_url: Backend API base URL.
        session_id: Pre-created session ID configured for the target DB.
        mode: Chat mode (``"standard"`` or ``"analyst"``).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        session_id: str = "",
        mode: str = "standard",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.mode = mode

    async def generate(self, case: BenchmarkCase) -> Dict[str, Any]:
        """POST to ``/api/v1/chat`` and extract the SQL from the response."""
        try:
            import httpx
        except ImportError:
            return {"query": None, "error": "httpx not installed"}

        nl = case.natural_language
        if case.evidence:
            nl = f"{nl}\n\nAdditional context: {case.evidence}"

        payload = {
            "session_id": self.session_id,
            "message": nl,
            "mode": self.mode,
            "stream": False,
            "continue_conversation": False,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            return {
                "query": data.get("sql"),
                "tokens_used": (data.get("usage") or {}).get("total_tokens", 0),
                "cost_usd": (data.get("usage") or {}).get("cost_usd", 0.0),
                "tools_used": data.get("tools_used", []),
                "retries": 0,
                "error": data.get("error"),
            }
        except Exception as exc:
            logger.error("Chat API call failed for %s: %s", case.case_id, exc)
            return {"query": None, "error": str(exc)}
