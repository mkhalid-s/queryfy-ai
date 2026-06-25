"""
Comprehensive unit tests for:
1. app/main.py - FastAPI app setup, middleware, CORS, lifespan events
2. app/models/schemas.py - All Pydantic request/response models
3. app/models/chat_models.py - Chat-related Pydantic models
4. app/services/message_truncator.py - Message truncation logic
5. app/core/dependencies.py - Dependency injection and validation
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


# ============================================================================
# 1. SCHEMAS TESTS (app/models/schemas.py)
# ============================================================================


class TestLLMConfig:
    def test_valid_openai_config(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(provider="openai", api_key="sk-test123", model="gpt-4")
        assert config.provider == "openai"
        assert config.api_key == "sk-test123"
        assert config.model == "gpt-4"

    def test_valid_anthropic_config(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(provider="anthropic", api_key="key", model="claude-3-opus")
        assert config.provider == "anthropic"

    def test_valid_oauth_gateway_config(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(
            provider="oauth_gateway", base_url="https://gateway.example.com",
            token_url="https://auth.example.com/token", client_id="my-client",
            client_secret="my-secret", auth_scope="api.read",
            auth_type="client_credentials", tenant="my-tenant",
            chat_endpoint="/v1/chat",
        )
        assert config.provider == "oauth_gateway"
        assert config.base_url == "https://gateway.example.com"

    def test_default_model(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(provider="openai")
        assert config.model == "gpt-4"

    def test_default_auth_type(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(provider="openai")
        assert config.auth_type == "client_credentials"

    def test_optional_fields_default_none(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(provider="openai")
        assert config.base_url is None
        assert config.token_url is None
        assert config.client_id is None
        assert config.client_secret is None
        assert config.auth_scope is None
        assert config.api_key is None
        assert config.fast_model is None
        assert config.star is None
        assert config.chat_endpoint is None
        assert config.tenant is None

    def test_complexity_routing_defaults(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(provider="openai")
        assert config.fast_model is None
        assert config.enable_complexity_routing is False

    def test_complexity_routing_enabled(self):
        from app.models.schemas import LLMConfig
        config = LLMConfig(provider="openai", fast_model="gpt-4o-mini", enable_complexity_routing=True)
        assert config.fast_model == "gpt-4o-mini"
        assert config.enable_complexity_routing is True

    def test_invalid_provider_raises_validation_error(self):
        from app.models.schemas import LLMConfig
        with pytest.raises(ValidationError):
            LLMConfig(provider="invalid_provider")

    def test_all_valid_providers(self):
        from app.models.schemas import LLMConfig
        valid_providers = [
            "oauth_gateway", "openai", "anthropic", "azure", "bedrock",
            "vertex_ai", "gemini", "groq", "ollama", "together",
            "mistral", "cohere", "replicate", "deepseek", "custom",
        ]
        for provider in valid_providers:
            config = LLMConfig(provider=provider)
            assert config.provider == provider


class TestDatabaseConfig:
    def test_valid_postgresql_config(self):
        from app.models.schemas import DatabaseConfig
        config = DatabaseConfig(db_type="postgresql", connection_url="postgresql://user:pass@localhost:5432/mydb")
        assert config.db_type == "postgresql"

    def test_valid_mysql_config(self):
        from app.models.schemas import DatabaseConfig
        config = DatabaseConfig(db_type="mysql", connection_url="mysql://user:pass@localhost:3306/mydb")
        assert config.db_type == "mysql"

    def test_optional_name_field(self):
        from app.models.schemas import DatabaseConfig
        config = DatabaseConfig(db_type="postgresql", connection_url="postgresql://user:pass@localhost:5432/mydb")
        assert config.name is None
        config_named = DatabaseConfig(db_type="postgresql", connection_url="postgresql://user:pass@localhost:5432/mydb", name="Production DB")
        assert config_named.name == "Production DB"

    def test_invalid_db_type(self):
        from app.models.schemas import DatabaseConfig
        with pytest.raises(ValidationError):
            DatabaseConfig(db_type="invalid_db", connection_url="postgresql://user:pass@localhost:5432/mydb")

    def test_connection_url_too_short(self):
        from app.models.schemas import DatabaseConfig
        with pytest.raises(ValidationError) as exc_info:
            DatabaseConfig(db_type="postgresql", connection_url="short")
        assert "Invalid connection URL" in str(exc_info.value)

    def test_connection_url_empty_string(self):
        from app.models.schemas import DatabaseConfig
        with pytest.raises(ValidationError) as exc_info:
            DatabaseConfig(db_type="postgresql", connection_url="")
        assert "Invalid connection URL" in str(exc_info.value)

    def test_all_valid_db_types(self):
        from app.models.schemas import DatabaseConfig
        valid_db_types = [
            "postgresql", "mysql", "mongodb", "snowflake", "bigquery",
            "databricks", "redshift", "sqlserver", "oracle", "athena",
            "trino", "presto", "clickhouse", "hive", "spark",
            "duckdb", "sqlite", "cassandra", "dynamodb",
        ]
        for db_type in valid_db_types:
            config = DatabaseConfig(db_type=db_type, connection_url="some://valid-connection-url-here")
            assert config.db_type == db_type


class TestMaskConnectionUrl:
    def test_mask_password_in_url(self):
        from app.models.schemas import mask_connection_url
        url = "postgresql://admin:secretpassword@localhost:5432/mydb"
        masked = mask_connection_url(url)
        assert "secretpassword" not in masked
        assert "****" in masked
        assert "admin" in masked
        assert "localhost" in masked
        assert "5432" in masked

    def test_url_without_password(self):
        from app.models.schemas import mask_connection_url
        url = "postgresql://localhost:5432/mydb"
        masked = mask_connection_url(url)
        assert masked == url

    def test_empty_url(self):
        from app.models.schemas import mask_connection_url
        assert mask_connection_url("") == ""

    def test_url_with_special_chars_in_password(self):
        from app.models.schemas import mask_connection_url
        url = "postgresql://user:p%40ss%23word@host:5432/db"
        masked = mask_connection_url(url)
        assert "p%40ss%23word" not in masked
        assert "****" in masked

    def test_url_with_port(self):
        from app.models.schemas import mask_connection_url
        url = "mysql://root:password@db.example.com:3306/production"
        masked = mask_connection_url(url)
        assert "password" not in masked
        assert "3306" in masked

    def test_url_without_port(self):
        from app.models.schemas import mask_connection_url
        url = "postgresql://user:pass@localhost/mydb"
        masked = mask_connection_url(url)
        assert "****" in masked
        assert "localhost" in masked

    def test_invalid_url_returns_as_is(self):
        from app.models.schemas import mask_connection_url
        result = mask_connection_url("not-a-url")
        assert result == "not-a-url"


class TestSessionModels:
    def test_session_create_request(self):
        from app.models.schemas import DatabaseConfig, LLMConfig, SessionCreateRequest
        req = SessionCreateRequest(
            llm_config=LLMConfig(provider="openai", api_key="key"),
            db_config=DatabaseConfig(db_type="postgresql", connection_url="postgresql://user:pass@localhost:5432/db"),
        )
        assert req.llm_config.provider == "openai"
        assert req.db_config.db_type == "postgresql"

    def test_session_response_defaults(self):
        from app.models.schemas import SessionResponse
        resp = SessionResponse(session_id="abc123", message="Session created")
        assert resp.locked is False
        assert resp.csrf_token is None
        assert resp.schema_ready is True
        assert resp.connection_hash is None
        assert resp.db_type is None

    def test_session_response_all_fields(self):
        from app.models.schemas import SessionResponse
        resp = SessionResponse(
            session_id="abc123", message="Session created", locked=True,
            csrf_token="csrf-token-xyz", schema_ready=False,
            connection_hash="hash123", db_type="postgresql",
        )
        assert resp.locked is True
        assert resp.csrf_token == "csrf-token-xyz"

    def test_session_info(self):
        from app.models.schemas import SessionInfo
        info = SessionInfo(
            id="sess-1", created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T01:00:00Z", locked=False,
            history_count=5, db_type="mysql", llm_provider="openai",
        )
        assert info.id == "sess-1"
        assert info.history_count == 5


class TestQueryModels:
    def test_query_request_valid(self):
        from app.models.schemas import QueryRequest
        req = QueryRequest(session_id="abc", natural_language="Show me all customers")
        assert req.natural_language == "Show me all customers"

    def test_query_request_min_length(self):
        from app.models.schemas import QueryRequest
        with pytest.raises(ValidationError):
            QueryRequest(session_id="abc", natural_language="ab")

    def test_query_request_max_length(self):
        from app.models.schemas import QueryRequest
        with pytest.raises(ValidationError):
            QueryRequest(session_id="abc", natural_language="x" * 5001)

    def test_query_request_boundary_min(self):
        from app.models.schemas import QueryRequest
        req = QueryRequest(session_id="abc", natural_language="abc")
        assert len(req.natural_language) == 3

    def test_query_request_boundary_max(self):
        from app.models.schemas import QueryRequest
        req = QueryRequest(session_id="abc", natural_language="x" * 5000)
        assert len(req.natural_language) == 5000

    def test_query_response_defaults(self):
        from app.models.schemas import QueryResponse
        resp = QueryResponse()
        assert resp.sql is None
        assert resp.query_id is None
        assert resp.error is None

    def test_execute_query_request_defaults(self):
        from app.models.schemas import ExecuteQueryRequest
        req = ExecuteQueryRequest(session_id="abc", sql_query="SELECT 1")
        assert req.limit == 500
        assert req.force_refresh is False

    def test_execute_query_request_limit_below_min(self):
        from app.models.schemas import ExecuteQueryRequest
        with pytest.raises(ValidationError):
            ExecuteQueryRequest(session_id="abc", sql_query="SELECT 1", limit=0)

    def test_execute_query_request_limit_above_max(self):
        from app.models.schemas import ExecuteQueryRequest
        with pytest.raises(ValidationError):
            ExecuteQueryRequest(session_id="abc", sql_query="SELECT 1", limit=1000001)

    def test_execute_query_response(self):
        from app.models.schemas import ExecuteQueryResponse
        resp = ExecuteQueryResponse(columns=["id", "name"], rows=[{"id": 1, "name": "Alice"}], row_count=1, execution_time=0.05)
        assert resp.row_count == 1
        assert resp.has_more is False
        assert resp.from_cache is False

    def test_explain_request(self):
        from app.models.schemas import ExplainRequest
        req = ExplainRequest(session_id="abc", sql_query="SELECT * FROM users")
        assert req.stream is False


class TestFeedbackModels:
    def test_feedback_request_valid(self):
        from app.models.schemas import FeedbackRequest
        req = FeedbackRequest(session_id="abc", query_id="q-1", rating=5)
        assert req.rating == 5
        assert req.comment is None

    def test_feedback_request_rating_below_min(self):
        from app.models.schemas import FeedbackRequest
        with pytest.raises(ValidationError):
            FeedbackRequest(session_id="abc", query_id="q-1", rating=0)

    def test_feedback_request_rating_above_max(self):
        from app.models.schemas import FeedbackRequest
        with pytest.raises(ValidationError):
            FeedbackRequest(session_id="abc", query_id="q-1", rating=6)

    def test_feedback_request_comment_max_length(self):
        from app.models.schemas import FeedbackRequest
        with pytest.raises(ValidationError):
            FeedbackRequest(session_id="abc", query_id="q-1", rating=3, comment="x" * 1001)


class TestHistoryModels:
    def test_history_entry_minimal(self):
        from app.models.schemas import HistoryEntry
        entry = HistoryEntry(id="h-1", query="Show all users", sql="SELECT * FROM users", timestamp="2025-01-01T00:00:00Z")
        assert entry.pinned is False
        assert entry.mode is None

    def test_history_entry_full(self):
        from app.models.schemas import HistoryEntry
        entry = HistoryEntry(
            id="h-1", query="Who are top customers?",
            sql="SELECT * FROM customers ORDER BY revenue DESC",
            timestamp="2025-01-01T00:00:00Z", feedback_rating=5, pinned=True,
            mode="analyst", key_findings=["Finding 1", "Finding 2"], confidence=0.95,
        )
        assert entry.pinned is True
        assert entry.confidence == 0.95

    def test_history_search_request_defaults(self):
        from app.models.schemas import HistorySearchRequest
        req = HistorySearchRequest()
        assert req.limit == 50
        assert req.offset == 0

    def test_history_search_request_limit_out_of_range(self):
        from app.models.schemas import HistorySearchRequest
        with pytest.raises(ValidationError):
            HistorySearchRequest(limit=201)
        with pytest.raises(ValidationError):
            HistorySearchRequest(limit=0)

    def test_history_search_request_negative_offset(self):
        from app.models.schemas import HistorySearchRequest
        with pytest.raises(ValidationError):
            HistorySearchRequest(offset=-1)


class TestDMLModels:
    def test_dml_mode_enum_values(self):
        from app.models.schemas import DMLMode
        assert DMLMode.DISABLED == "disabled"
        assert DMLMode.PREVIEW == "preview"
        assert DMLMode.SANDBOX == "sandbox"
        assert DMLMode.CONFIRM == "confirm"

    def test_dml_mode_is_string_enum(self):
        from app.models.schemas import DMLMode
        assert isinstance(DMLMode.DISABLED, str)

    def test_dml_preview_result(self):
        from app.models.schemas import DMLPreviewResult
        result = DMLPreviewResult(operation="UPDATE", table="users", estimated_rows_affected=10, sql="UPDATE users SET active=true")
        assert result.sample_changes == []
        assert result.warnings == []

    def test_dml_execute_response_defaults(self):
        from app.models.schemas import DMLExecuteResponse
        resp = DMLExecuteResponse(success=True, message="Done")
        assert resp.rows_affected == 0
        assert resp.rollback_performed is False

    def test_dml_confirmation_response_defaults(self):
        from app.models.schemas import DMLConfirmationResponse
        resp = DMLConfirmationResponse(confirmation_token="tok-123")
        assert resp.expires_in_seconds == 300


class TestHealthModels:
    def test_health_check_response(self):
        from app.models.schemas import HealthCheckResponse
        resp = HealthCheckResponse(status="healthy", timestamp="2025-01-01T00:00:00Z", app="QueryfyAI", version="1.0.0", redis_connected=True)
        assert resp.redis_connected is True

    def test_liveness_response(self):
        from app.models.schemas import LivenessResponse
        resp = LivenessResponse(status="alive", timestamp="2025-01-01T00:00:00Z")
        assert resp.status == "alive"

    def test_readiness_response(self):
        from app.models.schemas import ReadinessResponse
        resp = ReadinessResponse(ready=True, timestamp="2025-01-01T00:00:00Z", checks={"database": True})
        assert resp.ready is True

    def test_detailed_health_response(self):
        from app.models.schemas import DetailedHealthResponse
        resp = DetailedHealthResponse(healthy=True, timestamp="2025-01-01T00:00:00Z", check_duration_ms=5.0, app="QueryfyAI", version="1.0.0", checks={})
        assert resp.check_duration_ms == 5.0


class TestTokenModels:
    def test_token_info(self):
        from app.models.schemas import TokenInfo
        now = datetime.now()
        info = TokenInfo(access_token="token-xyz", expires_in=3600, expires_at=now, obtained_at=now)
        assert info.token_type == "Bearer"
        assert info.scope is None


class TestLLMUsageModel:
    def test_llm_usage_defaults(self):
        from app.models.schemas import LLMUsage
        usage = LLMUsage()
        assert usage.prompt_tokens == 0
        assert usage.total_tokens == 0
        assert usage.cached is False

    def test_llm_usage_with_data(self):
        from app.models.schemas import LLMUsage
        usage = LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, model="gpt-4", cost_usd=0.0045, cached=True)
        assert usage.total_tokens == 150
        assert usage.cached is True


class TestMetricsModels:
    def test_request_metrics(self):
        from app.models.schemas import RequestMetrics
        m = RequestMetrics(total=100, success=95, errors=5, success_rate=0.95)
        assert m.success_rate == 0.95

    def test_agent_metrics(self):
        from app.models.schemas import AgentMetrics
        m = AgentMetrics(total_runs=10, total_retries=3, successes=8, failures=2, success_rate=0.8, avg_attempts=1.3)
        assert m.success_rate == 0.8


class TestErrorModels:
    def test_error_detail(self):
        from app.models.schemas import ErrorDetail
        detail = ErrorDetail(message="Something went wrong")
        assert detail.field is None

    def test_error_response(self):
        from app.models.schemas import ErrorResponse
        resp = ErrorResponse(error="ValidationError", message="Invalid input", status_code=400)
        assert resp.request_id is None

    def test_error_responses_dict(self):
        from app.models.schemas import ERROR_RESPONSES
        assert 400 in ERROR_RESPONSES
        assert 404 in ERROR_RESPONSES
        assert 500 in ERROR_RESPONSES


class TestNegativeExampleModel:
    def test_negative_example(self):
        from app.models.schemas import NegativeExample
        ex = NegativeExample(question="Show all users", failed_sql="SELCT * FROM users", error_message="syntax error", error_type="syntax")
        assert ex.error_type == "syntax"
        assert isinstance(ex.timestamp, datetime)


class TestMiscSchemaModels:
    def test_db_type_info(self):
        from app.models.schemas import DBTypeInfo
        info = DBTypeInfo(id="postgresql", name="PostgreSQL", port=5432, example="postgresql://...")
        assert info.icon is None

    def test_llm_provider_info_defaults(self):
        from app.models.schemas import LLMProviderInfo
        info = LLMProviderInfo(id="openai", name="OpenAI")
        assert info.requiresApiKey is True

    def test_default_llm_config(self):
        from app.models.schemas import DefaultLLMConfig
        config = DefaultLLMConfig(
            provider="openai", base_url="", token_url="", client_id="",
            client_secret_set=False, auth_scope="", auth_type="",
            tenant="", star="", chat_endpoint="", api_key_set=True, model="gpt-4",
        )
        assert config.api_key_set is True

    def test_default_db_config(self):
        from app.models.schemas import DefaultDBConfig
        config = DefaultDBConfig(db_type="postgresql", connection_url="postgresql://user:****@localhost:5432/db", connection_url_set=True, name="My DB")
        assert config.connection_url_set is True

    def test_message_response(self):
        from app.models.schemas import MessageResponse
        resp = MessageResponse(message="OK")
        assert resp.message == "OK"

    def test_schema_response(self):
        from app.models.schemas import SchemaResponse
        resp = SchemaResponse()
        assert resp.schema_text is None

    def test_csrf_token_response(self):
        from app.models.schemas import CSRFTokenResponse
        resp = CSRFTokenResponse(csrf_token="abc123")
        assert resp.csrf_token == "abc123"

    def test_session_detail_response(self):
        from app.models.schemas import SessionDetailResponse
        resp = SessionDetailResponse(
            id="sess-1", created_at="2025-01-01", updated_at="2025-01-01",
            locked=False, history_count=0, db_type="postgresql", llm_provider="openai",
        )
        assert resp.schema_ready is False
        assert resp.schema_table_count == 0


# ============================================================================
# 2. CHAT MODELS TESTS (app/models/chat_models.py)
# ============================================================================


class TestChatMode:
    def test_chat_mode_values(self):
        from app.models.chat_models import ChatMode
        assert ChatMode.STANDARD == "standard"
        assert ChatMode.ANALYST == "analyst"

    def test_chat_mode_is_string_enum(self):
        from app.models.chat_models import ChatMode
        assert isinstance(ChatMode.STANDARD, str)


class TestChatRequest:
    def test_valid_standard_request(self):
        from app.models.chat_models import ChatMode, ChatRequest
        req = ChatRequest(session_id="abc", message="Show top 10 customers")
        assert req.mode == ChatMode.STANDARD
        assert req.stream is False
        assert req.include_reasoning is False
        assert req.include_chart is True
        assert req.continue_conversation is True

    def test_valid_analyst_request(self):
        from app.models.chat_models import ChatMode, ChatRequest
        req = ChatRequest(session_id="abc", message="Who are my best customers?", mode=ChatMode.ANALYST, stream=True, include_reasoning=True, include_chart=False)
        assert req.mode == ChatMode.ANALYST
        assert req.stream is True

    def test_message_min_length(self):
        from app.models.chat_models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(session_id="abc", message="ab")

    def test_message_max_length(self):
        from app.models.chat_models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(session_id="abc", message="x" * 5001)

    def test_message_boundary_min(self):
        from app.models.chat_models import ChatRequest
        req = ChatRequest(session_id="abc", message="abc")
        assert len(req.message) == 3

    def test_message_boundary_max(self):
        from app.models.chat_models import ChatRequest
        req = ChatRequest(session_id="abc", message="x" * 5000)
        assert len(req.message) == 5000

    def test_missing_session_id(self):
        from app.models.chat_models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(message="Show me data")

    def test_missing_message(self):
        from app.models.chat_models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(session_id="abc")


class TestChartSpec:
    def test_chart_spec_minimal(self):
        from app.models.chat_models import ChartSpec
        spec = ChartSpec(chart_type="bar", x_axis="month", y_axis="revenue")
        assert spec.chart_type == "bar"
        assert spec.data == []

    def test_chart_spec_full(self):
        from app.models.chat_models import ChartSpec
        spec = ChartSpec(chart_type="line", title="Monthly Revenue", x_axis="month", y_axis="revenue", data=[{"month": "Jan", "revenue": 1000}], series=["revenue"])
        assert spec.title == "Monthly Revenue"
        assert len(spec.data) == 1


class TestChatResponse:
    def test_chat_response_defaults(self):
        from app.models.chat_models import ChatMode, ChatResponse
        resp = ChatResponse(mode=ChatMode.STANDARD)
        assert resp.success is True
        assert resp.sql is None
        assert resp.is_valid is True
        assert resp.key_findings == []
        assert resp.confidence == 0.8
        assert resp.tools_used == []
        # tool_calls_count, execution_time_ms, and usage have been
        # dropped from ChatResponse — they were produced but never
        # consumed by any client. Internal counters preserved on
        # LLMMetricsTracker (llm_service.py).
        assert resp.is_follow_up is False
        assert resp.conversation_turn == 1
        assert resp.warnings == []
        assert resp.error is None

    def test_chat_response_analyst_mode(self):
        from app.models.chat_models import ChatMode, ChatResponse
        resp = ChatResponse(
            mode=ChatMode.ANALYST, sql="SELECT * FROM customers",
            answer="Your top customers are...",
            key_findings=["Finding 1", "Finding 2"], confidence=0.95,
            tools_used=["search_tables", "execute_query"],
        )
        assert resp.confidence == 0.95
        assert len(resp.tools_used) == 2

    def test_chat_response_dropped_fields_no_longer_exist(self):
        """Drift guard — the three dropped fields must stay dropped."""
        from app.models.chat_models import ChatResponse
        fields = ChatResponse.model_fields
        assert "tool_calls_count" not in fields, (
            "tool_calls_count should be dropped — produced but never consumed"
        )
        assert "execution_time_ms" not in fields, (
            "execution_time_ms should be dropped — produced but never consumed"
        )
        assert "usage" not in fields, (
            "usage should be dropped — produced but never consumed"
        )

    def test_chat_response_confidence_boundaries(self):
        from app.models.chat_models import ChatMode, ChatResponse
        resp_min = ChatResponse(mode=ChatMode.STANDARD, confidence=0.0)
        assert resp_min.confidence == 0.0
        resp_max = ChatResponse(mode=ChatMode.STANDARD, confidence=1.0)
        assert resp_max.confidence == 1.0

    def test_chat_response_confidence_out_of_range(self):
        from app.models.chat_models import ChatMode, ChatResponse
        with pytest.raises(ValidationError):
            ChatResponse(mode=ChatMode.STANDARD, confidence=1.1)
        with pytest.raises(ValidationError):
            ChatResponse(mode=ChatMode.STANDARD, confidence=-0.1)

    def test_chat_response_error_case(self):
        from app.models.chat_models import ChatMode, ChatResponse
        resp = ChatResponse(success=False, mode=ChatMode.STANDARD, error="Failed to generate SQL", warnings=["Schema may be outdated"])
        assert resp.success is False
        assert resp.error == "Failed to generate SQL"

    def test_chat_response_follow_up(self):
        from app.models.chat_models import ChatMode, ChatResponse
        resp = ChatResponse(mode=ChatMode.ANALYST, is_follow_up=True, conversation_turn=3)
        assert resp.is_follow_up is True
        assert resp.conversation_turn == 3


class TestChatStreamEvent:
    def test_stream_event_thinking(self):
        from app.models.chat_models import ChatStreamEvent
        event = ChatStreamEvent(event="thinking", content="Analyzing query...")
        assert event.event == "thinking"
        assert event.data is None

    def test_stream_event_tool_call(self):
        from app.models.chat_models import ChatStreamEvent
        event = ChatStreamEvent(event="tool_call", tool_name="search_tables", tool_args={"query": "customers"}, step_number=1, progress=0.3)
        assert event.tool_name == "search_tables"
        assert event.step_number == 1

    def test_stream_event_done(self):
        from app.models.chat_models import ChatStreamEvent
        event = ChatStreamEvent(event="done", data={"sql": "SELECT * FROM users"})
        assert event.data is not None

    def test_stream_event_progress_out_of_range(self):
        from app.models.chat_models import ChatStreamEvent
        with pytest.raises(ValidationError):
            ChatStreamEvent(event="thinking", progress=1.1)
        with pytest.raises(ValidationError):
            ChatStreamEvent(event="thinking", progress=-0.1)


# ============================================================================
# 3. MESSAGE TRUNCATOR TESTS (app/services/message_truncator.py)
# ============================================================================


class TestMessageTruncator:
    def _make_truncator(self, max_messages=10, preserve_recent=5, max_tool_output=200):
        from app.services.message_truncator import MessageTruncator
        truncator = MessageTruncator.__new__(MessageTruncator)
        truncator.max_messages = max_messages
        truncator.preserve_recent = preserve_recent
        truncator.max_tool_output = max_tool_output
        return truncator

    def test_empty_messages(self):
        truncator = self._make_truncator()
        result, stats = truncator.truncate([], include_stats=False)
        assert result == []

    def test_empty_messages_with_stats(self):
        truncator = self._make_truncator()
        result, stats = truncator.truncate([], include_stats=True)
        assert result == []

    def test_messages_below_max_no_truncation(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        truncator = self._make_truncator(max_messages=10, max_tool_output=10000)
        messages = [SystemMessage(content="You are a helpful assistant"), HumanMessage(content="Hello")]
        result, stats = truncator.truncate(messages)
        assert len(result) == 2
        assert stats is None

    def test_messages_below_max_with_stats(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        truncator = self._make_truncator(max_messages=10, max_tool_output=10000)
        messages = [SystemMessage(content="System"), HumanMessage(content="Hello")]
        result, stats = truncator.truncate(messages, include_stats=True)
        assert len(result) == 2
        assert stats is not None
        assert stats.messages_removed == 0

    def test_truncation_preserves_system_message(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        truncator = self._make_truncator(max_messages=4, preserve_recent=2)
        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="First question"), AIMessage(content="First answer"),
            HumanMessage(content="Second question"), AIMessage(content="Second answer"),
            HumanMessage(content="Third question"), AIMessage(content="Third answer"),
        ]
        result, _ = truncator.truncate(messages)
        assert result[0].content == "System prompt"

    def test_truncation_preserves_first_human_message(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        truncator = self._make_truncator(max_messages=4, preserve_recent=2)
        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Original question"), AIMessage(content="First answer"),
            HumanMessage(content="Follow up 1"), AIMessage(content="Answer 2"),
            HumanMessage(content="Follow up 2"), AIMessage(content="Answer 3"),
        ]
        result, _ = truncator.truncate(messages)
        contents = [m.content for m in result]
        assert "Original question" in contents

    def test_truncation_adds_marker(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        truncator = self._make_truncator(max_messages=4, preserve_recent=1)
        messages = [
            SystemMessage(content="System"), HumanMessage(content="Q1"),
            AIMessage(content="A1"), HumanMessage(content="Q2"),
            AIMessage(content="A2"), HumanMessage(content="Q3"),
            AIMessage(content="A3"),
        ]
        result, _ = truncator.truncate(messages)
        contents = [m.content for m in result]
        assert any("truncated" in c.lower() for c in contents)

    def test_truncation_with_stats(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        truncator = self._make_truncator(max_messages=4, preserve_recent=1)
        messages = [
            SystemMessage(content="System"), HumanMessage(content="Q1"),
            AIMessage(content="A1"), HumanMessage(content="Q2"),
            AIMessage(content="A2"), HumanMessage(content="Q3"),
            AIMessage(content="A3"),
        ]
        result, stats = truncator.truncate(messages, include_stats=True)
        assert stats is not None
        assert stats.original_count == 7
        assert stats.messages_removed > 0

    def test_tool_output_truncation(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        truncator = self._make_truncator(max_messages=20, max_tool_output=50)
        long_output = "x" * 200
        messages = [
            SystemMessage(content="System"), HumanMessage(content="Question"),
            AIMessage(content="", tool_calls=[{"id": "tc-1", "name": "search", "args": {}}]),
            ToolMessage(content=long_output, tool_call_id="tc-1"),
        ]
        result, _ = truncator.truncate(messages)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1
        assert len(tool_msgs[0].content) < len(long_output)

    def test_tool_output_preserves_short_content(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        truncator = self._make_truncator(max_messages=20, max_tool_output=500)
        short_output = "Short result"
        messages = [
            SystemMessage(content="System"), HumanMessage(content="Question"),
            AIMessage(content="", tool_calls=[{"id": "tc-1", "name": "search", "args": {}}]),
            ToolMessage(content=short_output, tool_call_id="tc-1"),
        ]
        result, _ = truncator.truncate(messages)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert tool_msgs[0].content == short_output

    def test_estimate_tokens(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        truncator = self._make_truncator()
        messages = [SystemMessage(content="A" * 100), HumanMessage(content="B" * 80)]
        tokens = truncator.estimate_tokens(messages)
        assert tokens == 55  # (100+20+80+20)//4

    def test_estimate_tokens_empty(self):
        truncator = self._make_truncator()
        assert truncator.estimate_tokens([]) == 0

    def test_smart_truncate_content_short(self):
        truncator = self._make_truncator()
        assert truncator._smart_truncate_content("Short content", 100) == "Short content"

    def test_smart_truncate_content_long_non_tabular(self):
        truncator = self._make_truncator()
        content = "A" * 500
        result = truncator._smart_truncate_content(content, 100)
        assert len(result) <= 110
        assert "truncated" in result.lower()

    def test_smart_truncate_content_tabular(self):
        truncator = self._make_truncator()
        lines = ["col1 | col2 | col3", "-" * 30]
        for i in range(50):
            lines.append(f"val{i} | val{i} | val{i}")
        content = "\n".join(lines)
        result = truncator._smart_truncate_content(content, 200)
        assert len(result) <= 210
        assert "truncated" in result.lower()


class TestSafeTruncationBoundary:
    def _make_truncator(self):
        from app.services.message_truncator import MessageTruncator
        truncator = MessageTruncator.__new__(MessageTruncator)
        truncator.max_messages = 10
        truncator.preserve_recent = 5
        truncator.max_tool_output = 200
        return truncator

    def test_boundary_at_zero(self):
        from langchain_core.messages import HumanMessage
        truncator = self._make_truncator()
        assert truncator._find_safe_truncation_boundary([HumanMessage(content="test")], 0) == 0

    def test_boundary_beyond_length(self):
        from langchain_core.messages import HumanMessage
        truncator = self._make_truncator()
        assert truncator._find_safe_truncation_boundary([HumanMessage(content="test")], 5) == 5

    def test_boundary_at_human_message(self):
        from langchain_core.messages import AIMessage, HumanMessage
        truncator = self._make_truncator()
        messages = [AIMessage(content="answer"), HumanMessage(content="question"), AIMessage(content="answer 2")]
        assert truncator._find_safe_truncation_boundary(messages, 1) == 1

    def test_boundary_avoids_orphan_tool_messages(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        truncator = self._make_truncator()
        messages = [
            HumanMessage(content="q"),
            AIMessage(content="", tool_calls=[{"id": "tc-1", "name": "search", "args": {}}]),
            ToolMessage(content="result", tool_call_id="tc-1"),
            HumanMessage(content="follow up"),
        ]
        result = truncator._find_safe_truncation_boundary(messages, 2)
        assert result <= 2


class TestModuleLevelConvenienceFunctions:
    @patch("app.services.message_truncator.settings")
    def test_truncate_messages_convenience(self, mock_settings):
        from langchain_core.messages import HumanMessage, SystemMessage
        mock_settings.AGENT_MAX_MESSAGES = 50
        mock_settings.AGENT_PRESERVE_RECENT = 20
        mock_settings.AGENT_MAX_TOOL_OUTPUT = 4000
        from app.services.message_truncator import truncate_messages
        messages = [SystemMessage(content="System"), HumanMessage(content="Hello")]
        result = truncate_messages(messages)
        assert len(result) == 2

    @patch("app.services.message_truncator.settings")
    def test_truncate_messages_with_stats_convenience(self, mock_settings):
        from langchain_core.messages import HumanMessage, SystemMessage
        mock_settings.AGENT_MAX_MESSAGES = 50
        mock_settings.AGENT_PRESERVE_RECENT = 20
        mock_settings.AGENT_MAX_TOOL_OUTPUT = 4000
        from app.services.message_truncator import truncate_messages_with_stats
        messages = [SystemMessage(content="System"), HumanMessage(content="Hello")]
        result, stats = truncate_messages_with_stats(messages)
        assert len(result) == 2
        assert stats is not None
        assert stats.messages_removed == 0

    @patch("app.services.message_truncator.settings")
    def test_truncate_messages_with_custom_limits(self, mock_settings):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        mock_settings.AGENT_MAX_MESSAGES = 50
        mock_settings.AGENT_PRESERVE_RECENT = 20
        mock_settings.AGENT_MAX_TOOL_OUTPUT = 4000
        from app.services.message_truncator import truncate_messages
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Q1"), AIMessage(content="A1"),
            HumanMessage(content="Q2"), AIMessage(content="A2"),
            HumanMessage(content="Q3"), AIMessage(content="A3"),
        ]
        result = truncate_messages(messages, max_messages=3, preserve_recent=1)
        assert len(result) < len(messages)


class TestTruncationStats:
    def test_truncation_stats_creation(self):
        from app.services.message_truncator import TruncationStats
        stats = TruncationStats(original_count=20, truncated_count=10, messages_removed=10, tool_outputs_truncated=3, estimated_tokens_saved=500)
        assert stats.original_count == 20
        assert stats.estimated_tokens_saved == 500


# ============================================================================
# 4. DEPENDENCIES TESTS (app/core/dependencies.py)
# ============================================================================


class TestSessionValidationResult:
    def test_basic_properties(self):
        from app.core.dependencies import SessionValidationResult
        session = {"llm_config": {"provider": "openai"}, "db_config": {"db_type": "postgresql"}, "locked": False, "schema_ready": True, "schema_error": None}
        result = SessionValidationResult(session, "sess-1", "csrf-token")
        assert result.session_id == "sess-1"
        assert result.csrf_token == "csrf-token"
        assert result.llm_config == {"provider": "openai"}
        assert result.db_config == {"db_type": "postgresql"}
        assert result.is_locked is False
        assert result.schema_ready is True
        assert result.schema_error is None

    def test_locked_session(self):
        from app.core.dependencies import SessionValidationResult
        session = {"locked": True}
        result = SessionValidationResult(session, "sess-1")
        assert result.is_locked is True

    def test_missing_keys_return_defaults(self):
        from app.core.dependencies import SessionValidationResult
        session = {}
        result = SessionValidationResult(session, "sess-1")
        assert result.llm_config == {}
        assert result.db_config == {}
        assert result.is_locked is False
        assert result.schema_ready is False
        assert result.schema_error is None


class TestGetSession:
    @patch("app.core.dependencies.session_store")
    def test_get_session_found(self, mock_store):
        from app.core.dependencies import get_session
        mock_store.get.return_value = {"id": "sess-1", "db_config": {}}
        session = get_session("sess-1")
        assert session["id"] == "sess-1"
        mock_store.get.assert_called_once_with("sess-1")

    @patch("app.core.dependencies.session_store")
    def test_get_session_not_found(self, mock_store):
        from app.core.dependencies import get_session
        mock_store.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_session("nonexistent")
        assert exc_info.value.status_code == 404
        assert "Session not found" in exc_info.value.detail

    @patch("app.core.dependencies.session_store")
    def test_get_session_empty_dict_is_falsy(self, mock_store):
        """Empty dict is falsy in Python, so get_session raises 404."""
        from app.core.dependencies import get_session
        mock_store.get.return_value = {}
        with pytest.raises(HTTPException) as exc_info:
            get_session("sess-1")
        assert exc_info.value.status_code == 404

    @patch("app.core.dependencies.session_store")
    def test_get_session_returns_falsy_zero(self, mock_store):
        from app.core.dependencies import get_session
        mock_store.get.return_value = 0
        with pytest.raises(HTTPException) as exc_info:
            get_session("sess-1")
        assert exc_info.value.status_code == 404


class TestCheckRateLimit:
    @patch("app.core.dependencies.rate_limiter")
    def test_rate_limit_allowed(self, mock_limiter):
        from app.core.dependencies import check_rate_limit
        mock_limiter.check_rate_limit.return_value = (True, "OK")
        check_rate_limit("sess-1", "generate")

    @patch("app.core.dependencies.rate_limiter")
    def test_rate_limit_exceeded(self, mock_limiter):
        from app.core.dependencies import check_rate_limit
        mock_limiter.check_rate_limit.return_value = (False, "Rate limit exceeded")
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("sess-1", "generate")
        assert exc_info.value.status_code == 429


class TestValidateRequest:
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    def test_validate_request_success(self, mock_store, mock_csrf):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = {"id": "sess-1", "schema_ready": True}
        session = validate_request("sess-1", "csrf-token")
        assert session["id"] == "sess-1"

    @patch("app.core.dependencies.session_store")
    def test_validate_request_session_not_found(self, mock_store):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            validate_request("bad-id", "token")
        assert exc_info.value.status_code == 404

    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    def test_validate_request_csrf_failure(self, mock_store, mock_csrf):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = {"id": "sess-1"}
        mock_csrf.side_effect = HTTPException(status_code=403, detail="CSRF failed")
        with pytest.raises(HTTPException) as exc_info:
            validate_request("sess-1", "bad-csrf")
        assert exc_info.value.status_code == 403

    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    def test_validate_request_skip_csrf(self, mock_store, mock_csrf):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = {"id": "sess-1"}
        validate_request("sess-1", None, require_csrf=False)
        mock_csrf.assert_not_called()

    @patch("app.core.dependencies.rate_limiter")
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    def test_validate_request_rate_limit(self, mock_store, mock_csrf, mock_limiter):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = {"id": "sess-1"}
        mock_limiter.check_rate_limit.return_value = (False, "Too many requests")
        with pytest.raises(HTTPException) as exc_info:
            validate_request("sess-1", "token", rate_limit_action="generate")
        assert exc_info.value.status_code == 429

    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    def test_validate_request_schema_not_ready(self, mock_store, mock_csrf):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = {"id": "sess-1", "schema_ready": False}
        with pytest.raises(HTTPException) as exc_info:
            validate_request("sess-1", "token", require_schema_ready=True)
        assert exc_info.value.status_code == 400
        assert "Schema is still loading" in exc_info.value.detail

    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    def test_validate_request_schema_error(self, mock_store, mock_csrf):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = {"id": "sess-1", "schema_error": "Connection refused"}
        with pytest.raises(HTTPException) as exc_info:
            validate_request("sess-1", "token", require_schema_ready=True)
        assert exc_info.value.status_code == 400
        assert "Schema extraction failed" in exc_info.value.detail

    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    def test_validate_request_locked_session(self, mock_store, mock_csrf):
        from app.core.dependencies import validate_request
        mock_store.get.return_value = {"id": "sess-1", "locked": True}
        with pytest.raises(HTTPException) as exc_info:
            validate_request("sess-1", "token", require_unlocked=True)
        assert exc_info.value.status_code == 400
        assert "locked session" in exc_info.value.detail


class TestRaiseHelpers:
    @patch("app.core.dependencies.ErrorSanitizer")
    def test_raise_server_error(self, mock_sanitizer):
        from app.core.dependencies import raise_server_error
        mock_sanitizer.sanitize_error.return_value = "Internal error"
        with pytest.raises(HTTPException) as exc_info:
            raise_server_error(Exception("raw error"), "test operation")
        assert exc_info.value.status_code == 500

    @patch("app.core.dependencies.ErrorSanitizer")
    def test_raise_validation_error(self, mock_sanitizer):
        from app.core.dependencies import raise_validation_error
        mock_sanitizer.sanitize_error.return_value = "Bad input"
        with pytest.raises(HTTPException) as exc_info:
            raise_validation_error(ValueError("bad value"))
        assert exc_info.value.status_code == 400

    @patch("app.core.dependencies.AuditLogger")
    def test_raise_security_error(self, mock_audit):
        from app.core.dependencies import raise_security_error
        with pytest.raises(HTTPException) as exc_info:
            raise_security_error("sess-1", "SQL_VERIFICATION_FAILED", "Security check failed", "details")
        assert exc_info.value.status_code == 403
        mock_audit.log_security_event.assert_called_once_with("sess-1", "SQL_VERIFICATION_FAILED", "details")

    @patch("app.core.dependencies.ErrorSanitizer")
    def test_safe_log_error(self, mock_sanitizer):
        from app.core.dependencies import safe_log_error
        mock_sanitizer.safe_log_error.return_value = "safe message"
        result = safe_log_error(Exception("raw"))
        assert result == "safe message"


class TestCreateSessionValidator:
    @pytest.mark.asyncio
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_session_only_validator(self, mock_store, mock_csrf):
        from app.core.dependencies import create_session_validator
        mock_store.get.return_value = {"id": "sess-1"}
        validator_fn = create_session_validator(require_csrf=False, rate_limit_action=None)
        result = await validator_fn(session_id="sess-1", csrf_token=None)
        assert result.session_id == "sess-1"
        mock_csrf.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_validator_with_csrf(self, mock_store, mock_csrf):
        from app.core.dependencies import create_session_validator
        mock_store.get.return_value = {"id": "sess-1"}
        validator_fn = create_session_validator(require_csrf=True)
        await validator_fn(session_id="sess-1", csrf_token="token-123")
        mock_csrf.assert_called_once_with("sess-1", "token-123")

    @pytest.mark.asyncio
    @patch("app.core.dependencies.rate_limiter")
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_validator_with_rate_limit(self, mock_store, mock_csrf, mock_limiter):
        from app.core.dependencies import create_session_validator
        mock_store.get.return_value = {"id": "sess-1"}
        mock_limiter.check_rate_limit.return_value = (True, "OK")
        validator_fn = create_session_validator(require_csrf=True, rate_limit_action="generate")
        await validator_fn(session_id="sess-1", csrf_token="token")
        mock_limiter.check_rate_limit.assert_called_once_with("sess-1", "generate")

    @pytest.mark.asyncio
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_validator_schema_required_not_ready(self, mock_store, mock_csrf):
        from app.core.dependencies import create_session_validator
        mock_store.get.return_value = {"id": "sess-1", "schema_ready": False}
        validator_fn = create_session_validator(require_csrf=True, require_schema_ready=True)
        with pytest.raises(HTTPException) as exc_info:
            await validator_fn(session_id="sess-1", csrf_token="token")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_validator_schema_error(self, mock_store, mock_csrf):
        from app.core.dependencies import create_session_validator
        mock_store.get.return_value = {"id": "sess-1", "schema_error": "Timeout"}
        validator_fn = create_session_validator(require_csrf=True, require_schema_ready=True)
        with pytest.raises(HTTPException) as exc_info:
            await validator_fn(session_id="sess-1", csrf_token="token")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_validator_require_unlocked_locked(self, mock_store, mock_csrf):
        from app.core.dependencies import create_session_validator
        mock_store.get.return_value = {"id": "sess-1", "locked": True}
        validator_fn = create_session_validator(require_csrf=True, require_unlocked=True)
        with pytest.raises(HTTPException) as exc_info:
            await validator_fn(session_id="sess-1", csrf_token="token")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("app.core.dependencies.session_store")
    async def test_validator_session_not_found(self, mock_store):
        from app.core.dependencies import create_session_validator
        mock_store.get.return_value = None
        validator_fn = create_session_validator(require_csrf=False)
        with pytest.raises(HTTPException) as exc_info:
            await validator_fn(session_id="nonexistent", csrf_token=None)
        assert exc_info.value.status_code == 404


class TestRequestSessionValidator:
    @pytest.mark.asyncio
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_request_session_validator_success(self, mock_store, mock_csrf):
        from app.core.dependencies import RequestSessionValidator
        mock_store.get.return_value = {"id": "sess-1", "schema_ready": True}
        validator = RequestSessionValidator(require_csrf=True, require_schema_ready=True)
        request_obj = MagicMock()
        request_obj.session_id = "sess-1"
        result = await validator(request_obj, csrf_token="token")
        assert result.session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_request_session_validator_missing_session_id(self):
        from app.core.dependencies import RequestSessionValidator
        validator = RequestSessionValidator()
        request_obj = MagicMock(spec=[])
        with pytest.raises(HTTPException) as exc_info:
            await validator(request_obj, csrf_token="token")
        assert exc_info.value.status_code == 400
        assert "session_id is required" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("app.core.dependencies.session_store")
    async def test_request_session_validator_not_found(self, mock_store):
        from app.core.dependencies import RequestSessionValidator
        mock_store.get.return_value = None
        validator = RequestSessionValidator(require_csrf=False)
        request_obj = MagicMock()
        request_obj.session_id = "bad-id"
        with pytest.raises(HTTPException) as exc_info:
            await validator(request_obj, csrf_token=None)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("app.core.dependencies.rate_limiter")
    @patch("app.core.dependencies.verify_csrf_for_session")
    @patch("app.core.dependencies.session_store")
    async def test_request_session_validator_rate_limited(self, mock_store, mock_csrf, mock_limiter):
        from app.core.dependencies import RequestSessionValidator
        mock_store.get.return_value = {"id": "sess-1"}
        mock_limiter.check_rate_limit.return_value = (False, "Too fast")
        validator = RequestSessionValidator(require_csrf=True, rate_limit_action="generate")
        request_obj = MagicMock()
        request_obj.session_id = "sess-1"
        with pytest.raises(HTTPException) as exc_info:
            await validator(request_obj, csrf_token="token")
        assert exc_info.value.status_code == 429


class TestPreConfiguredValidators:
    def test_validate_for_generate_exists(self):
        from app.core.dependencies import validate_for_generate
        assert callable(validate_for_generate)

    def test_validate_for_execute_exists(self):
        from app.core.dependencies import validate_for_execute
        assert callable(validate_for_execute)

    def test_validate_for_export_exists(self):
        from app.core.dependencies import validate_for_export
        assert callable(validate_for_export)

    def test_validate_for_followup_exists(self):
        from app.core.dependencies import validate_for_followup
        assert callable(validate_for_followup)

    def test_validate_for_explain_exists(self):
        from app.core.dependencies import validate_for_explain
        assert callable(validate_for_explain)

    def test_validate_for_schema_exists(self):
        from app.core.dependencies import validate_for_schema
        assert callable(validate_for_schema)

    def test_validate_session_only_exists(self):
        from app.core.dependencies import validate_session_only
        assert callable(validate_session_only)


# ============================================================================
# 5. MAIN APP TESTS (app/main.py)
# ============================================================================


class TestAppCreation:
    def test_app_exists(self):
        from app.main import app
        assert app is not None
        assert app.title is not None

    def test_app_has_version(self):
        from app.main import app
        assert app.version is not None

    def test_app_has_openapi_tags(self):
        from app.main import app
        assert app.openapi_tags is not None
        tag_names = [t["name"] for t in app.openapi_tags]
        assert "Health" in tag_names
        assert "Sessions" in tag_names
        assert "Queries" in tag_names

    def test_tags_metadata_structure(self):
        from app.main import tags_metadata
        for tag in tags_metadata:
            assert "name" in tag
            assert "description" in tag


class TestMaxRequestBodySize:
    def test_max_body_size_is_10mb(self):
        from app.main import MAX_REQUEST_BODY_SIZE
        assert MAX_REQUEST_BODY_SIZE == 10 * 1024 * 1024


class TestCORSConfiguration:
    def test_allowed_origins_parsed(self):
        from app.main import allowed_origins
        assert isinstance(allowed_origins, list)
        assert len(allowed_origins) > 0

    @patch.dict("os.environ", {"ALLOWED_ORIGINS": "http://example.com,https://app.example.com"})
    def test_custom_cors_origins(self):
        import os
        raw = os.getenv("ALLOWED_ORIGINS", "")
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        assert "http://example.com" in origins

    @patch.dict("os.environ", {"ALLOWED_ORIGINS": ""})
    def test_empty_cors_origins(self):
        import os
        raw = os.getenv("ALLOWED_ORIGINS", "")
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        assert origins == []


class TestRequestBodySizeMiddleware:
    @pytest.mark.asyncio
    async def test_request_within_size_limit(self):
        from app.main import limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = {"content-length": "1024"}
        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_request_exceeds_size_limit(self):
        from app.main import limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = {"content-length": str(11 * 1024 * 1024)}
        mock_call_next = AsyncMock()
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response.status_code == 413
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_exactly_at_size_limit(self):
        from app.main import MAX_REQUEST_BODY_SIZE, limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = {"content-length": str(MAX_REQUEST_BODY_SIZE)}
        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_request_one_byte_over_limit(self):
        from app.main import MAX_REQUEST_BODY_SIZE, limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = {"content-length": str(MAX_REQUEST_BODY_SIZE + 1)}
        mock_call_next = AsyncMock()
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_request_no_content_length(self):
        from app.main import limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get.return_value = None
        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_request_invalid_content_length_value_error(self):
        """Test the try/except ValueError fix for non-numeric content-length."""
        from app.main import limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = {"content-length": "not-a-number"}
        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_request_empty_content_length(self):
        """Test empty string content-length is falsy and passes through."""
        from app.main import limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = {"content-length": ""}
        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_request_negative_content_length(self):
        """Negative content-length passes through since it is not > MAX."""
        from app.main import limit_request_body_size
        mock_request = MagicMock()
        mock_request.headers = {"content-length": "-1"}
        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await limit_request_body_size(mock_request, mock_call_next)
        assert response == mock_response


class TestCorrelationIdMiddleware:
    @pytest.mark.asyncio
    @patch("app.main.clear_context")
    @patch("app.main.bind_context")
    @patch("app.main.get_current_trace_id")
    async def test_correlation_id_from_trace(self, mock_trace, mock_bind, mock_clear):
        from app.main import add_correlation_id
        mock_trace.return_value = "trace-abc123"
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get.return_value = None
        mock_request.state = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await add_correlation_id(mock_request, mock_call_next)
        assert response.headers["X-Request-ID"] == "trace-abc123"
        assert response.headers["X-Trace-ID"] == "trace-abc123"

    @pytest.mark.asyncio
    @patch("app.main.clear_context")
    @patch("app.main.bind_context")
    @patch("app.main.get_current_trace_id")
    async def test_correlation_id_from_header(self, mock_trace, mock_bind, mock_clear):
        from app.main import add_correlation_id
        mock_trace.return_value = None
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get.return_value = "custom-req-id"
        mock_request.state = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await add_correlation_id(mock_request, mock_call_next)
        assert response.headers["X-Request-ID"] == "custom-req-id"
        assert "X-Trace-ID" not in response.headers

    @pytest.mark.asyncio
    @patch("app.main.clear_context")
    @patch("app.main.bind_context")
    @patch("app.main.get_current_trace_id")
    async def test_correlation_id_generated_uuid(self, mock_trace, mock_bind, mock_clear):
        from app.main import add_correlation_id
        mock_trace.return_value = None
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get.return_value = None
        mock_request.state = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await add_correlation_id(mock_request, mock_call_next)
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) == 8

    @pytest.mark.asyncio
    @patch("app.main.clear_context")
    @patch("app.main.bind_context")
    @patch("app.main.get_current_trace_id")
    async def test_correlation_id_clears_context_on_exception(self, mock_trace, mock_bind, mock_clear):
        from app.main import add_correlation_id
        mock_trace.return_value = None
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get.return_value = None
        mock_request.state = MagicMock()
        mock_call_next = AsyncMock(side_effect=RuntimeError("middleware error"))
        with pytest.raises(RuntimeError):
            await add_correlation_id(mock_request, mock_call_next)
        mock_clear.assert_called_once()


class TestSecurityHeadersMiddleware:
    @pytest.mark.asyncio
    async def test_security_headers_added(self):
        from app.main import add_security_headers
        mock_request = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await add_security_headers(mock_request, mock_call_next)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in response.headers


class TestLogRequestsMiddleware:
    @pytest.mark.asyncio
    @patch("app.main.record_http_request")
    async def test_log_requests_normal_path(self, mock_record):
        from app.main import log_requests
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/v1/sessions"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await log_requests(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_record.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.main.record_http_request")
    async def test_log_requests_skips_metrics_endpoint(self, mock_record):
        from app.main import log_requests
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/metrics"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_call_next = AsyncMock(return_value=mock_response)
        await log_requests(mock_request, mock_call_next)
        mock_record.assert_not_called()


class TestRootEndpoint:
    @pytest.mark.asyncio
    async def test_root_endpoint(self):
        from app.main import root
        result = await root()
        assert "app" in result
        assert "version" in result
        assert result["status"] == "running"


class TestInitializeEmbeddingModel:
    @patch("app.main.settings")
    def test_embedding_provider_none(self, mock_settings):
        from app.main import initialize_embedding_model
        mock_settings.EMBEDDING_PROVIDER = "none"
        result = initialize_embedding_model()
        assert result is True

    @patch("app.main.settings")
    def test_embedding_provider_openai_with_key(self, mock_settings):
        from app.main import initialize_embedding_model
        mock_settings.EMBEDDING_PROVIDER = "openai"
        mock_settings.OPENAI_API_KEY = "sk-test"
        result = initialize_embedding_model()
        assert result is True

    @patch("app.main.settings")
    def test_embedding_provider_openai_without_key(self, mock_settings):
        from app.main import initialize_embedding_model
        mock_settings.EMBEDDING_PROVIDER = "openai"
        mock_settings.OPENAI_API_KEY = None
        mock_settings.EMBEDDING_MODEL = "all-MiniLM-L6-v2"
        with patch("builtins.__import__", side_effect=ImportError("no chromadb")):
            result = initialize_embedding_model()
            assert result is False

    @patch("app.main.settings")
    def test_embedding_provider_not_configured(self, mock_settings):
        from app.main import initialize_embedding_model
        del mock_settings.EMBEDDING_PROVIDER
        mock_settings.EMBEDDING_MODEL = "all-MiniLM-L6-v2"
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            result = initialize_embedding_model()
            assert result is False


class TestLifespan:
    @pytest.mark.asyncio
    @patch("app.main.init_distributed_locking")
    @patch("app.main.init_checkpointer", new_callable=AsyncMock)
    @patch("app.main.init_telemetry")
    @patch("app.main.cleanup_service")
    @patch("app.main.initialize_cache", new_callable=AsyncMock)
    @patch("app.main.cache_service")
    @patch("app.main.pool_manager")
    @patch("app.main.init_database", new_callable=AsyncMock)
    @patch("app.main.session_store")
    @patch("app.main.vector_db")
    @patch("app.main.initialize_embedding_model")
    @patch("app.main.settings")
    async def test_lifespan_startup_and_shutdown(
        self, mock_settings, mock_init_embedding, mock_vector_db,
        mock_session_store, mock_init_db, mock_pool_mgr,
        mock_cache_svc, mock_init_cache, mock_cleanup,
        mock_init_telemetry, mock_init_checkpointer, mock_init_distributed,
    ):
        from app.main import lifespan
        mock_settings.validate_config.return_value = []
        mock_settings.CHROMA_PERSIST_DIR = "/tmp/test_chroma"
        mock_settings.REDIS_URL = "redis://localhost"
        mock_settings.CACHE_TYPE = "memory"
        mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        mock_init_embedding.return_value = True
        mock_session_store.redis_client = None
        mock_init_db.return_value = False
        mock_pool_mgr.start_cleanup_task = AsyncMock()
        mock_cache_svc.get_stats.return_value = {"backend": "memory"}
        mock_cleanup.start = AsyncMock()
        mock_cleanup.stop = AsyncMock()
        mock_init_telemetry.return_value = False
        mock_init_checkpointer.return_value = None
        mock_init_distributed.return_value = False
        mock_pool_mgr.close_all = AsyncMock()
        mock_app = MagicMock()
        with patch.dict("sys.modules", {"litellm": MagicMock()}):
            with patch("app.services.tools.register_all_tools"):
                with patch("app.services.tools.validate_tool_registration", return_value=(True, [])):
                    with patch("app.services.tools.ToolRegistry") as mock_registry:
                        mock_registry.get_tool_names.return_value = ["tool1"]
                        with patch("app.main.is_checkpointer_available", return_value=False):
                            with patch("app.main.close_database", new_callable=AsyncMock):
                                with patch("app.main.shutdown_telemetry"):
                                    async with lifespan(mock_app):
                                        mock_init_embedding.assert_called_once()
                                        mock_init_db.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.main.settings")
    async def test_lifespan_config_validation_error(self, mock_settings):
        from app.main import lifespan
        mock_settings.validate_config.side_effect = ValueError("Bad config")
        mock_settings.CHROMA_PERSIST_DIR = "/tmp/test"
        mock_app = MagicMock()
        with pytest.raises(ValueError, match="Bad config"):
            async with lifespan(mock_app):
                pass


class TestAppRouterRegistration:
    def test_routes_registered(self):
        from app.main import app
        # Some Starlette/FastAPI route containers (e.g., included routers)
        # may not expose a direct `.path` attribute.
        paths = [route.path for route in app.routes if hasattr(route, "path")]
        assert "/" in paths
        openapi_paths = list(app.openapi().get("paths", {}).keys())
        assert any(p.startswith("/api/v1") for p in openapi_paths)
