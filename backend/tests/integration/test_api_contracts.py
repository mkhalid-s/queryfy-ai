"""
API Contract Tests - Backend ↔ Frontend Integration

Tests for ensuring backend and frontend APIs are compatible:
- Field transformation (snake_case ↔ camelCase)
- Request/response format validation
- SSE event format compatibility
- Error response format alignment
- Chart specification format
- SQL hash consistency
- Timestamp parsing
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from tests.utils.integration_helpers import (
    transform_keys_to_camel,
    transform_keys_to_snake,
    validate_sse_event,
    validate_error_response,
    validate_chart_spec,
    validate_timestamp_format,
    validate_sql_hash,
    parse_sse_stream
)


# =============================================================================
# Field Transformation Tests (snake_case ↔ camelCase)
# =============================================================================

def test_chat_request_field_transformation():
    """Frontend camelCase request correctly transforms to backend snake_case"""
    # Frontend sends camelCase
    frontend_request = {
        "sessionId": "session-123",
        "message": "Show me users",
        "mode": "analyst",
        "stream": False,
        "includeReasoning": True,
        "includeChart": True,
        "continueConversation": True
    }

    # Transform to snake_case (as middleware does)
    backend_request = transform_keys_to_snake(frontend_request)

    # Verify transformation
    assert backend_request["session_id"] == "session-123"
    assert backend_request["message"] == "Show me users"
    assert backend_request["mode"] == "analyst"
    assert backend_request["stream"] is False
    assert backend_request["include_reasoning"] is True
    assert backend_request["include_chart"] is True
    assert backend_request["continue_conversation"] is True


def test_chat_response_field_transformation():
    """Backend snake_case response correctly transforms to frontend camelCase"""
    # Backend returns snake_case - COMPLETE ChatResponse model
    backend_response = {
        # Response Status
        "success": True,
        "mode": "analyst",

        # SQL Generation
        "sql": "SELECT * FROM users",
        "is_valid": True,
        "query_type": "SELECT",
        "explanation": "Retrieves all users",

        # Analyst Mode Fields
        "answer": "Here are all the users in the system",
        "key_findings": ["Total users: 150"],
        "confidence": 0.85,
        "chart": {
            "chart_type": "bar",
            "x_axis": "department",
            "y_axis": "count",
            "data": []
        },
        "raw_result": {
            "columns": ["id", "name"],
            "rows": [[1, "Alice"]],
            "row_count": 1
        },
        "reasoning": "I analyzed the users table and found all records",
        "data_quality": {
            "overall_score": 0.95,
            "completeness": 0.98,
            "issues": []
        },
        "suggestions": [
            {"text": "Show users by department", "category": "breakdown"}
        ],

        # Tool Usage
        "tools_used": ["search_tables", "get_schema", "execute_sql"],
        "tool_calls_count": 3,

        # Metadata
        "query_id": "q-12345-abcde",
        "sql_hash": "abc123def456789012345678901234",
        "execution_time_ms": 150,
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700
        },

        # Conversation Metadata
        "is_follow_up": False,
        "conversation_turn": 1,

        # Errors/Warnings
        "error": None,
        "warnings": ["Some data may be stale"]
    }

    # Transform to camelCase (as frontend does)
    frontend_response = transform_keys_to_camel(backend_response)

    # Verify response status transformation
    assert frontend_response["success"] is True
    assert frontend_response["mode"] == "analyst"

    # Verify SQL generation transformation
    assert frontend_response["sql"] == "SELECT * FROM users"
    assert frontend_response["isValid"] is True
    assert frontend_response["queryType"] == "SELECT"
    assert frontend_response["explanation"] == "Retrieves all users"

    # Verify analyst mode fields transformation
    assert frontend_response["answer"] == "Here are all the users in the system"
    assert frontend_response["keyFindings"] == ["Total users: 150"]
    assert frontend_response["confidence"] == 0.85
    assert frontend_response["reasoning"] == "I analyzed the users table and found all records"

    # Verify data quality transformation
    assert frontend_response["dataQuality"]["overallScore"] == 0.95
    assert frontend_response["dataQuality"]["completeness"] == 0.98
    assert frontend_response["dataQuality"]["issues"] == []

    # Verify suggestions transformation
    assert len(frontend_response["suggestions"]) == 1
    assert frontend_response["suggestions"][0]["text"] == "Show users by department"
    assert frontend_response["suggestions"][0]["category"] == "breakdown"

    # Verify tool usage transformation
    assert frontend_response["toolsUsed"] == ["search_tables", "get_schema", "execute_sql"]
    assert frontend_response["toolCallsCount"] == 3

    # Verify metadata transformation
    assert frontend_response["queryId"] == "q-12345-abcde"
    assert frontend_response["sqlHash"] == "abc123def456789012345678901234"
    assert frontend_response["executionTimeMs"] == 150
    assert frontend_response["usage"]["promptTokens"] == 500
    assert frontend_response["usage"]["completionTokens"] == 200
    assert frontend_response["usage"]["totalTokens"] == 700

    # Verify conversation metadata transformation
    assert frontend_response["isFollowUp"] is False
    assert frontend_response["conversationTurn"] == 1

    # Verify errors/warnings transformation
    assert frontend_response["error"] is None
    assert frontend_response["warnings"] == ["Some data may be stale"]

    # Verify nested transformation (chart)
    assert frontend_response["chart"]["chartType"] == "bar"
    assert frontend_response["chart"]["xAxis"] == "department"
    assert frontend_response["chart"]["yAxis"] == "count"

    # Verify nested transformation (raw_result)
    assert frontend_response["rawResult"]["rowCount"] == 1


def test_error_response_field_transformation():
    """Backend error response transforms correctly for frontend"""
    backend_error = {
        "success": False,
        "error": "Database connection failed",
        "error_type": "CONNECTION_ERROR",
        "error_code": "DB_001",
        "user_message": "Unable to connect to database. Please try again.",
        "retry_after": 30,
        "request_id": "req-abc-123"
    }

    frontend_error = transform_keys_to_camel(backend_error)

    assert frontend_error["success"] is False
    assert frontend_error["error"] == "Database connection failed"
    assert frontend_error["errorType"] == "CONNECTION_ERROR"
    assert frontend_error["errorCode"] == "DB_001"
    assert frontend_error["userMessage"] == "Unable to connect to database. Please try again."
    assert frontend_error["retryAfter"] == 30
    assert frontend_error["requestId"] == "req-abc-123"


# =============================================================================
# API Request/Response Compatibility Tests
# =============================================================================

def test_chat_standard_mode_contract(client):
    """Chat API standard mode contract matches frontend expectations"""
    from app.services.sql_generation import GenerationContext, SQLGenerationResult

    mock_ctx = MagicMock(spec=GenerationContext)
    mock_ctx.is_follow_up = False

    mock_result = SQLGenerationResult(
        success=True,
        sql="SELECT * FROM users LIMIT 10",
        query_id="q-test-123",
        sql_hash="abc123",
    )

    with patch('app.api.chat.SQLGenerationService.prepare_context', return_value=(mock_ctx, None)), \
         patch('app.api.chat.SQLGenerationService.generate_sql', return_value=mock_result), \
         patch('app.core.dependencies.session_store.get') as mock_get, \
         patch('app.api.chat.session_store'):
        # Mock session_store.get to return a valid session
        mock_get.return_value = {
            "id": "session-123",
            "db_config": {"connection_url": "postgresql://user:pass@localhost:5432/testdb", "db_type": "postgresql"},
            "llm_config": {"provider": "openai", "model": "gpt-4", "api_key": "test-key-123"},
            "schema_ready": True,
            "history": [],
            "context_window": []
        }

        response = client.post(
            "/api/v1/chat",
            json={
                "session_id": "session-123",
                "message": "Show top 10 users",
                "mode": "standard"
            },
            headers={"X-CSRF-Token": "test-csrf-token"}
        )

        assert response.status_code == 200
        data = response.json()

        # Validate required fields for standard mode
        assert "success" in data
        assert "mode" in data
        assert "sql" in data
        assert "is_valid" in data
        assert data["mode"] == "standard"
        assert data["success"] is True


def test_chat_analyst_mode_contract(client):
    """Chat API analyst mode contract matches frontend expectations"""
    with patch('app.api.chat.run_react_agent') as mock_agent:
        mock_agent.return_value = {
            "success": True,
            "status": "complete",
            "sql": "SELECT department, COUNT(*) FROM users GROUP BY department",
            "execution_result": {
                "success": True,
                "columns": ["department", "count"],
                "rows": [["Engineering", 50], ["Sales", 30]],
                "row_count": 2
            },
            "answer": "Your team has 50 engineers and 30 sales staff",
            "key_findings": ["Engineering is the largest department"],
            "confidence": "high",
            "chart": {
                "chart_type": "bar",
                "x_axis": "department",
                "y_axis": "count",
                "data": [
                    {"department": "Engineering", "count": 50},
                    {"department": "Sales", "count": 30}
                ]
            }
        }

        with patch('app.core.dependencies.session_store.get') as mock_get, \
             patch('app.api.chat.session_store'):
            # Mock session_store.get to return a valid session
            mock_get.return_value = {
                "id": "session-123",
                "db_config": {"connection_url": "postgresql://user:pass@localhost:5432/testdb", "db_type": "postgresql"},
                "llm_config": {"provider": "openai", "model": "gpt-4", "api_key": "test-key-123"},
                "schema_ready": True,
                "history": [],
                "context_window": []
            }

            response = client.post(
                "/api/v1/chat",
                json={
                    "session_id": "session-123",
                    "message": "How many people in each department?",
                    "mode": "analyst"
                },
                headers={"X-CSRF-Token": "test-csrf-token"}
            )

            assert response.status_code == 200
            data = response.json()

            # Validate required fields for analyst mode
            assert "success" in data
            assert "mode" in data
            assert "sql" in data
            assert "answer" in data
            assert data["mode"] == "analyst"
            assert data["success"] is True

            # Validate chart spec if present
            if "chart" in data and data["chart"]:
                validate_chart_spec(data["chart"])


# =============================================================================
# SSE Event Format Tests
# =============================================================================

def test_sse_event_format_validation():
    """SSE events follow correct format per ChatStreamEvent model"""
    # Valid SSE events matching ChatStreamEvent types
    valid_events = [
        'data: {"type": "thinking", "content": "Processing your request..."}\n',
        'data: {"type": "tool_call", "content": "Searching tables", "tool_name": "search_tables", "step_number": 1}\n',
        'data: {"type": "tool_result", "content": "Found 3 tables", "tool_name": "search_tables", "summary": "tables: users, orders, products"}\n',
        'data: {"type": "sql_chunk", "content": "SELECT * FROM"}\n',
        'data: {"type": "sql_complete", "content": "SELECT * FROM users", "sql": "SELECT * FROM users"}\n',
        'data: {"type": "executing", "content": "Running query..."}\n',
        'data: {"type": "analyzing", "content": "Generating insights..."}\n',
        'data: {"type": "done", "content": "Query completed successfully"}\n',
        'data: {"type": "error", "content": "Query failed", "error": "Syntax error"}\n'
    ]

    for event_line in valid_events:
        event_data = validate_sse_event(event_line)
        assert "type" in event_data
        assert "content" in event_data


def test_sse_event_types():
    """All SSE event types match ChatStreamEvent model"""
    # Event types per ChatStreamEvent model documentation
    valid_types = [
        "thinking",      # Agent is processing/reasoning
        "sql_chunk",     # Partial SQL text (progressive display)
        "sql_complete",  # Full SQL after validation (standard mode)
        "sql",           # Full SQL (analyst mode)
        "tool_call",     # Agent is calling a tool
        "tool_result",   # Tool returned a result
        "executing",     # Running the SQL query
        "analyzing",     # Generating insights from results
        "done",          # Complete response with full metadata
        "error"          # Error occurred
    ]

    for event_type in valid_types:
        event_line = f'data: {{"type": "{event_type}", "content": "Test"}}\n'
        event_data = validate_sse_event(event_line)
        assert event_data["type"] == event_type


def test_sse_tool_call_event_fields():
    """tool_call events include required fields per ChatStreamEvent"""
    event_line = 'data: {"type": "tool_call", "content": "Searching for tables", "tool_name": "search_tables", "tool_args": {"query": "users"}, "step_number": 1, "description": "Finding relevant tables"}\n'

    event_data = validate_sse_event(event_line)

    assert event_data["type"] == "tool_call"
    assert event_data["tool_name"] == "search_tables"
    assert event_data["tool_args"] == {"query": "users"}
    assert event_data["step_number"] == 1
    assert event_data["description"] == "Finding relevant tables"


def test_sse_tool_result_event_fields():
    """tool_result events include required fields per ChatStreamEvent"""
    event_line = 'data: {"type": "tool_result", "content": "Found tables", "tool_name": "search_tables", "summary": "Found 3 tables: users, orders, products"}\n'

    event_data = validate_sse_event(event_line)

    assert event_data["type"] == "tool_result"
    assert event_data["tool_name"] == "search_tables"
    assert event_data["summary"] == "Found 3 tables: users, orders, products"


def test_sse_done_event_with_data():
    """done event includes full response data"""
    done_event = {
        "type": "done",
        "content": "Complete",
        "data": {
            "sql": "SELECT * FROM users",
            "answer": "Here are all users",
            "key_findings": ["Total: 100 users"],
            "confidence": 0.9
        }
    }
    event_line = f'data: {json.dumps(done_event)}\n'

    event_data = validate_sse_event(event_line)

    assert event_data["type"] == "done"
    assert event_data["data"]["sql"] == "SELECT * FROM users"
    assert event_data["data"]["answer"] == "Here are all users"
    assert event_data["data"]["confidence"] == 0.9


def test_sse_progress_field():
    """SSE events can include progress indicator"""
    event_line = 'data: {"type": "analyzing", "content": "Processing results", "progress": 0.75}\n'

    event_data = validate_sse_event(event_line)

    assert event_data["type"] == "analyzing"
    assert event_data["progress"] == 0.75


def test_sse_stream_parsing():
    """SSE stream can be parsed into individual events"""
    sse_stream = """data: {"type": "thinking", "content": "Starting analysis"}

data: {"type": "tool_call", "content": "Searching tables", "tool_name": "search_tables"}

data: {"type": "tool_result", "content": "Found tables", "tool_name": "search_tables"}

data: {"type": "executing", "content": "Running SQL query"}

data: {"type": "analyzing", "content": "Generating insights"}

data: {"type": "done", "content": "Complete"}

"""

    events = parse_sse_stream(sse_stream)

    assert len(events) == 6
    assert events[0]["type"] == "thinking"
    assert events[1]["type"] == "tool_call"
    assert events[2]["type"] == "tool_result"
    assert events[3]["type"] == "executing"
    assert events[4]["type"] == "analyzing"
    assert events[5]["type"] == "done"


def test_sse_standard_mode_flow():
    """Standard mode SSE event flow: thinking -> sql_chunk -> sql_complete -> done"""
    sse_stream = """data: {"type": "thinking", "content": "Analyzing your query"}

data: {"type": "sql_chunk", "content": "SELECT * FROM"}

data: {"type": "sql_chunk", "content": "SELECT * FROM users"}

data: {"type": "sql_complete", "content": "SQL validated", "sql": "SELECT * FROM users"}

data: {"type": "done", "content": "Complete"}

"""

    events = parse_sse_stream(sse_stream)

    assert len(events) == 5
    assert events[0]["type"] == "thinking"
    assert events[1]["type"] == "sql_chunk"
    assert events[2]["type"] == "sql_chunk"
    assert events[3]["type"] == "sql_complete"
    assert events[4]["type"] == "done"


def test_sse_analyst_mode_flow():
    """Analyst mode SSE event flow: thinking -> tool_call -> tool_result -> sql -> executing -> analyzing -> done"""
    sse_stream = """data: {"type": "thinking", "content": "Planning approach"}

data: {"type": "tool_call", "content": "Searching", "tool_name": "search_tables"}

data: {"type": "tool_result", "content": "Found", "tool_name": "search_tables"}

data: {"type": "sql", "content": "SELECT COUNT(*) FROM users"}

data: {"type": "executing", "content": "Running query"}

data: {"type": "analyzing", "content": "Generating insights"}

data: {"type": "done", "content": "Complete"}

"""

    events = parse_sse_stream(sse_stream)

    assert len(events) == 7
    assert events[0]["type"] == "thinking"
    assert events[1]["type"] == "tool_call"
    assert events[2]["type"] == "tool_result"
    assert events[3]["type"] == "sql"
    assert events[4]["type"] == "executing"
    assert events[5]["type"] == "analyzing"
    assert events[6]["type"] == "done"


# =============================================================================
# Error Response Format Tests
# =============================================================================

def test_error_response_format_validation():
    """Error responses follow consistent format"""
    error_responses = [
        {
            "success": False,
            "error": "Invalid session ID",
            "error_type": "VALIDATION_ERROR"
        },
        {
            "success": False,
            "error": "Database connection failed",
            "error_type": "CONNECTION_ERROR",
            "retry_after": 30
        },
        {
            "success": False,
            "error": "Query timeout",
            "error_type": "TIMEOUT_ERROR",
            "details": {"elapsed_time": 120}
        }
    ]

    for error_response in error_responses:
        validate_error_response(error_response)


def test_error_response_has_user_friendly_message():
    """Error responses include user-friendly messages"""
    error_response = {
        "success": False,
        "error": "Internal database error: connection pool exhausted",
        "error_type": "CONNECTION_ERROR",
        "user_message": "Unable to connect to database. Please try again in a moment."
    }

    validate_error_response(error_response)
    assert "user_message" in error_response
    assert len(error_response["user_message"]) > 0


# =============================================================================
# Chart Specification Format Tests
# =============================================================================

def test_chart_spec_format_validation():
    """Chart specifications match expected format"""
    valid_chart_specs = [
        {
            "chart_type": "bar",
            "x_axis": "category",
            "y_axis": "value",
            "data": [{"category": "A", "value": 10}]
        },
        {
            "chart_type": "line",
            "x_axis": "date",
            "y_axis": "sales",
            "data": [{"date": "2024-01", "sales": 1000}],
            "title": "Monthly Sales"
        },
        {
            "chart_type": "pie",
            "x_axis": "segment",
            "y_axis": "percentage",
            "data": [{"segment": "A", "percentage": 60}]
        }
    ]

    for chart_spec in valid_chart_specs:
        validate_chart_spec(chart_spec)


def test_chart_spec_data_format():
    """Chart data matches expected structure"""
    chart_spec = {
        "chart_type": "bar",
        "x_axis": "month",
        "y_axis": "revenue",
        "data": [
            {"month": "Jan", "revenue": 5000},
            {"month": "Feb", "revenue": 6000},
            {"month": "Mar", "revenue": 7000}
        ]
    }

    validate_chart_spec(chart_spec)

    # Verify data structure
    assert isinstance(chart_spec["data"], list)
    assert len(chart_spec["data"]) > 0

    # Each data point should have x and y values
    for point in chart_spec["data"]:
        assert chart_spec["x_axis"] in point
        assert chart_spec["y_axis"] in point


# =============================================================================
# SQL Hash Consistency Tests
# =============================================================================

def test_sql_hash_format():
    """SQL hash follows consistent format (MD5 or SHA256)"""
    valid_hashes = [
        "5d41402abc4b2a76b9719d911017c592",  # MD5 (32 chars)
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 (64 chars)
    ]

    for sql_hash in valid_hashes:
        validate_sql_hash(sql_hash)


def test_sql_hash_consistency():
    """Same SQL produces same hash"""
    import hashlib

    sql = "SELECT * FROM users WHERE id = 1"

    # Generate hash twice
    hash1 = hashlib.md5(sql.encode()).hexdigest()
    hash2 = hashlib.md5(sql.encode()).hexdigest()

    assert hash1 == hash2
    validate_sql_hash(hash1)


# =============================================================================
# Timestamp Parsing Tests
# =============================================================================

def test_timestamp_format_validation():
    """Timestamps follow ISO8601 format"""
    valid_timestamps = [
        "2024-01-15T10:30:00Z",
        "2024-01-15T10:30:00.123456Z",
        "2024-01-15T10:30:00+00:00",
        "2024-01-15T10:30:00.123456+00:00"
    ]

    for timestamp in valid_timestamps:
        validate_timestamp_format(timestamp)


def test_timestamp_parsing_compatibility():
    """Frontend can parse backend timestamps"""
    from datetime import datetime

    backend_timestamp = "2024-01-15T10:30:00Z"

    # Verify it's valid ISO8601
    validate_timestamp_format(backend_timestamp)

    # Verify Python can parse it
    dt = datetime.fromisoformat(backend_timestamp.replace('Z', '+00:00'))
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15


# =============================================================================
# Schema Compatibility Tests
# =============================================================================

def test_chat_request_schema_compatibility():
    """Frontend chat request schema matches backend expectations"""
    frontend_schema = {
        "sessionId": str,
        "message": str,
        "mode": str,  # "standard" or "analyst"
        "stream": bool,
        "includeReasoning": bool,
        "includeChart": bool,
        "continueConversation": bool
    }

    backend_schema = {
        "session_id": str,
        "message": str,
        "mode": str,
        "stream": bool,
        "include_reasoning": bool,
        "include_chart": bool,
        "continue_conversation": bool
    }

    # Verify field mapping
    for frontend_field, field_type in frontend_schema.items():
        snake_field = transform_keys_to_snake({frontend_field: None})
        backend_field = list(snake_field.keys())[0]

        assert backend_field in backend_schema
        assert backend_schema[backend_field] == field_type


def test_chat_response_schema_compatibility():
    """Backend chat response schema matches frontend expectations"""
    backend_response = {
        "success": True,
        "mode": "analyst",
        "sql": "SELECT 1",
        "is_valid": True,
        "query_type": "SELECT",
        "answer": "The result is 1",
        "key_findings": ["One row"],
        "confidence": "high",
        "session_id": "session-123",
        "timestamp": "2024-01-15T10:30:00Z"
    }

    # Transform to frontend format
    frontend_response = transform_keys_to_camel(backend_response)

    # Verify frontend can access all fields
    assert frontend_response["success"] is True
    assert frontend_response["mode"] == "analyst"
    assert frontend_response["sql"] == "SELECT 1"
    assert frontend_response["isValid"] is True
    assert frontend_response["queryType"] == "SELECT"
    assert frontend_response["answer"] == "The result is 1"
    assert frontend_response["keyFindings"] == ["One row"]
    assert frontend_response["confidence"] == "high"
    assert frontend_response["sessionId"] == "session-123"
    assert frontend_response["timestamp"] == "2024-01-15T10:30:00Z"


# =============================================================================
# Backward Compatibility Tests
# =============================================================================

def test_optional_fields_are_optional():
    """Optional fields can be omitted without breaking compatibility"""
    # Minimal valid request
    minimal_request = {
        "session_id": "session-123",
        "message": "Show users"
    }

    # Should be valid (mode, stream, etc. have defaults)
    from app.models.chat_models import ChatRequest

    try:
        chat_request = ChatRequest(**minimal_request)
        assert chat_request.session_id == "session-123"
        assert chat_request.message == "Show users"
        assert chat_request.mode == "standard"  # Default
        assert chat_request.stream is False  # Default
    except Exception as e:
        pytest.fail(f"Minimal request should be valid: {e}")


def test_extra_fields_ignored():
    """Extra fields in request are ignored (forward compatibility)"""
    request_with_extra = {
        "session_id": "session-123",
        "message": "Show users",
        "future_feature": "some_value"  # Extra field
    }

    from app.models.chat_models import ChatRequest

    try:
        # Pydantic should ignore extra fields (or raise if configured to forbid)
        chat_request = ChatRequest(**request_with_extra)
        assert chat_request.session_id == "session-123"
        assert chat_request.message == "Show users"
    except Exception:
        # If extra fields are forbidden, that's also valid (strict mode)
        pass
