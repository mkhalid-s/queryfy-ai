"""
Integration Tests for SSE Streaming

Tests Server-Sent Events streaming functionality in chat endpoint.
Covers event formatting, stream lifecycle, error handling, and timeout scenarios.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.chat import _format_sse, _stream_chat
from app.models.chat_models import ChatMode, ChatStreamEvent


# ============================================
# HELPER FUNCTIONS
# ============================================


async def collect_stream_events(stream_generator):
    """
    Collect all SSE events from a stream generator.

    Returns:
        list: List of dicts, one per event. Each dict has 'event' and 'data' keys.
    """
    events = []
    async for sse_line in stream_generator:
        # SSE format: "data: {json}\n\n"
        if sse_line.startswith("data: "):
            json_str = sse_line[6:].strip()  # Remove "data: " prefix
            event_data = json.loads(json_str)
            events.append(event_data)
    return events


def parse_sse_line(sse_line: str) -> dict:
    """Parse a single SSE line into event dict."""
    if sse_line.startswith("data: "):
        json_str = sse_line[6:].strip()
        return json.loads(json_str)
    return {}


# ============================================
# EVENT FORMATTING TESTS
# ============================================


def test_format_sse_basic():
    """Test _format_sse produces correct SSE format"""
    event = ChatStreamEvent(event="thinking", content="Processing...", progress=0.1)

    result = _format_sse(event)

    # Should start with "data: "
    assert result.startswith("data: ")
    # Should end with double newline
    assert result.endswith("\n\n")
    # Should be valid JSON after "data: " prefix
    json_str = result[6:-2]  # Remove "data: " and "\n\n"
    parsed = json.loads(json_str)
    assert parsed["event"] == "thinking"
    assert parsed["content"] == "Processing..."
    assert parsed["progress"] == 0.1


def test_format_sse_with_tool_data():
    """Test _format_sse with tool_call event including tool_name and tool_args"""
    event = ChatStreamEvent(
        event="tool_call",
        tool_name="search_tables",
        tool_args={"keywords": ["customer", "order"]},
        progress=0.3,
        step_number=1,
        description="Searching for relevant tables"
    )

    result = _format_sse(event)
    parsed = parse_sse_line(result)

    assert parsed["event"] == "tool_call"
    assert parsed["tool_name"] == "search_tables"
    assert parsed["tool_args"] == {"keywords": ["customer", "order"]}
    assert parsed["step_number"] == 1
    assert parsed["description"] == "Searching for relevant tables"


def test_format_sse_done_event_with_data():
    """Test _format_sse with done event including complex data payload"""
    event = ChatStreamEvent(
        event="done",
        content="Query complete",
        progress=1.0,
        data={
            "query_id": "test123",
            "sql": "SELECT * FROM customers",
            "mode": "analyst",
            "key_findings": ["Finding 1", "Finding 2"],
            "confidence": 0.95,
            "chart": {
                "chart_type": "bar",
                "title": "Customer Distribution",
                "x_axis": "region",
                "y_axis": "count"
            }
        }
    )

    result = _format_sse(event)
    parsed = parse_sse_line(result)

    assert parsed["event"] == "done"
    assert parsed["data"]["query_id"] == "test123"
    assert parsed["data"]["sql"] == "SELECT * FROM customers"
    assert parsed["data"]["key_findings"] == ["Finding 1", "Finding 2"]
    assert parsed["data"]["confidence"] == 0.95
    assert parsed["data"]["chart"]["chart_type"] == "bar"


# ============================================
# STREAM LIFECYCLE TESTS
# ============================================


@pytest.mark.asyncio
async def test_stream_lifecycle_standard_mode(mock_db_config, mock_llm_config):
    """Test complete stream lifecycle for standard mode: thinking -> sql_chunk* -> sql_complete -> done"""

    # Mock session and dependencies
    session = {
        "id": "test-session",
        "llm_config": mock_llm_config.model_dump(),
        "db_config": mock_db_config.model_dump(),
        "context_window": [],
        "last_query_context": None,
    }

    # Mock SQL generation streaming
    async def mock_sql_generator():
        yield "SELECT "
        yield "* "
        yield "FROM "
        yield "customers "
        yield "LIMIT 10"

    with patch("app.api.chat.SQLGenerationService.prepare_context") as mock_prepare, \
         patch("app.api.chat.LLMService.generate_sql") as mock_llm, \
         patch("app.api.chat.vector_db.find_similar_queries", return_value=[]), \
         patch("app.api.chat.SecurityService.validate_generated_sql", return_value=(True, None)), \
         patch("app.api.chat.sql_integrity.register_sql", return_value="hash123"), \
         patch("app.api.chat.query_history_service.save_query", new_callable=AsyncMock), \
         patch("app.api.chat.session_store.reset_conversation"), \
         patch("app.api.chat.session_store.update"), \
         patch("app.api.chat.session_store.add_history", return_value="entry1"), \
         patch("app.api.chat.session_store.update_history_entry"):

        # Mock context preparation
        mock_ctx = MagicMock()
        mock_ctx.sanitized_query = "show customers"
        mock_ctx.relevant_schema = "customers table"
        mock_ctx.conversation_history = []
        mock_ctx.natural_language = "show customers"
        mock_ctx.is_follow_up = False
        mock_ctx.db_config = mock_db_config
        mock_ctx.llm_config = mock_llm_config
        mock_prepare.return_value = (mock_ctx, None)

        # Mock LLM service
        mock_llm.return_value = (mock_sql_generator(), {})

        # Run stream
        stream = _stream_chat(
            session_id="test-session",
            session=session,
            message="show customers",
            mode=ChatMode.STANDARD,
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            include_reasoning=False,
            include_chart=False,
            continue_conversation=False,
        )

        events = await collect_stream_events(stream)

        # Verify lifecycle
        assert len(events) >= 3, "Should have at least thinking, sql_chunk, sql_complete, done events"

        # First event should be "thinking" with some processing message
        assert events[0]["event"] == "thinking"
        # Accept various thinking messages
        assert any(word in events[0]["content"] for word in ["SQL", "Processing", "Analyzing", "Generating"])

        # Should have sql_chunk events
        sql_chunks = [e for e in events if e["event"] == "sql_chunk"]
        assert len(sql_chunks) >= 5, "Should have multiple sql_chunk events"

        # Should have sql_complete event
        sql_complete_events = [e for e in events if e["event"] == "sql_complete"]
        assert len(sql_complete_events) == 1
        assert "SELECT * FROM customers LIMIT 10" in sql_complete_events[0]["content"]

        # Last event should be "done"
        assert events[-1]["event"] == "done"
        assert events[-1]["data"]["mode"] == "standard"
        assert "SELECT" in events[-1]["data"]["sql"]


@pytest.mark.asyncio
async def test_stream_lifecycle_analyst_mode(mock_db_config, mock_llm_config):
    """Test complete stream lifecycle for analyst mode: thinking -> tool_call -> tool_result -> sql -> executing -> result -> done"""

    session = {
        "id": "test-session",
        "llm_config": mock_llm_config.model_dump(),
        "db_config": mock_db_config.model_dump(),
        "context_window": [],
        "last_query_context": None,
    }

    # Mock agent streaming events (accept kwargs to match run_streaming signature)
    async def mock_agent_stream(**kwargs):
        yield {"event": "thinking", "content": "Analyzing question...", "progress": 0.1}
        yield {
            "event": "tool_call",
            "tool_name": "search_tables",
            "tool_args": {"keywords": ["customer"]},
            "progress": 0.2,
            "step_number": 1
        }
        yield {
            "event": "tool_result",
            "tool_name": "search_tables",
            "content": "Found 2 tables",
            "progress": 0.3,
            "summary": "customers, customer_orders"
        }
        yield {
            "event": "sql_generated",
            "sql": "SELECT * FROM customers LIMIT 100",
            "progress": 0.6
        }
        yield {
            "event": "executing",
            "content": "Running query...",
            "progress": 0.7
        }
        yield {
            "event": "complete",
            "result": {
                "success": True,
                "sql": "SELECT * FROM customers LIMIT 100",
                "execution_result": {
                    "success": True,
                    "columns": ["id", "name"],
                    "rows": [[1, "Alice"], [2, "Bob"]],
                    "row_count": 2,
                    "has_analysis": True,
                    "insights": [
                        {"severity": "info", "description": "Dataset has 2 customers"}
                    ],
                    "chart": {
                        "recommended_chart": "bar",
                        "title": "Customers",
                        "config": {"x_axis": "name", "y_axis": "id"}
                    },
                    "quality": {"overall_score": 95, "completeness": 100, "issues": []}
                },
                "tools_used": ["search_tables", "execute_and_analyze"],
                "total_steps": 2,
                "suggestions": [{"question": "What regions?"}]
            }
        }

    with patch("app.api.chat.ReActAgent") as mock_agent_class, \
         patch("app.api.chat.sql_integrity.register_sql", return_value="hash456"), \
         patch("app.api.chat.query_history_service.save_query", new_callable=AsyncMock), \
         patch("app.api.chat.generate_data_summary", return_value="Found 2 customers"), \
         patch("app.api.chat.session_store.reset_conversation"), \
         patch("app.api.chat.session_store.update"), \
         patch("app.api.chat.session_store.add_history", return_value="entry1"), \
         patch("app.api.chat.session_store.cache_query_result"), \
         patch("app.api.chat.session_store.get_conversation_context", return_value=[]):

        # Mock agent instance
        mock_agent = MagicMock()
        mock_agent.run_streaming = mock_agent_stream
        mock_agent_class.return_value = mock_agent

        # Run stream
        stream = _stream_chat(
            session_id="test-session",
            session=session,
            message="show customers",
            mode=ChatMode.ANALYST,
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            include_reasoning=False,
            include_chart=True,
            continue_conversation=False,
        )

        events = await collect_stream_events(stream)

        # Verify analyst mode lifecycle
        assert len(events) >= 6, "Should have thinking, tool_call, tool_result, sql, result, done"

        # Find each event type
        thinking_events = [e for e in events if e["event"] == "thinking"]
        tool_call_events = [e for e in events if e["event"] == "tool_call"]
        tool_result_events = [e for e in events if e["event"] == "tool_result"]
        sql_events = [e for e in events if e["event"] == "sql"]
        result_events = [e for e in events if e["event"] == "result"]
        done_events = [e for e in events if e["event"] == "done"]

        assert len(thinking_events) >= 1, "Should have thinking events"
        assert len(tool_call_events) >= 1, "Should have tool_call events"
        assert len(tool_result_events) >= 1, "Should have tool_result events"
        assert len(sql_events) >= 1, "Should have sql event"
        assert len(result_events) >= 1, "Should have result event"
        assert len(done_events) == 1, "Should have exactly one done event"

        # Verify done event data
        done_event = done_events[0]
        assert done_event["data"]["mode"] == "analyst"
        assert "sql" in done_event["data"]
        assert "key_findings" in done_event["data"]
        assert "chart" in done_event["data"]
        assert done_event["data"]["tools_used"] == ["search_tables", "execute_and_analyze"]


# ============================================
# EVENT ORDERING TESTS
# ============================================


@pytest.mark.asyncio
async def test_event_stream_ordering(mock_db_config, mock_llm_config):
    """Test that events are emitted in correct order with monotonically increasing progress"""

    session = {"id": "test-session", "context_window": [], "last_query_context": None}

    async def mock_agent_stream(**kwargs):
        yield {"event": "thinking", "progress": 0.1}
        yield {"event": "tool_call", "tool_name": "search_tables", "progress": 0.2}
        yield {"event": "tool_result", "tool_name": "search_tables", "progress": 0.3}
        yield {"event": "sql_generated", "sql": "SELECT 1", "progress": 0.6}
        yield {
            "event": "complete",
            "result": {
                "success": True,
                "sql": "SELECT 1",
                "execution_result": {
                    "success": True,
                    "columns": ["?column?"],
                    "rows": [[1]],
                    "row_count": 1,
                    "has_analysis": False
                },
                "tools_used": ["search_tables"],
                "total_steps": 1
            }
        }

    with patch("app.api.chat.ReActAgent") as mock_agent_class, \
         patch("app.api.chat.sql_integrity.register_sql", return_value="hash"), \
         patch("app.api.chat.query_history_service.save_query", new_callable=AsyncMock), \
         patch("app.api.chat.generate_data_summary", return_value="Result: 1"), \
         patch("app.api.chat.session_store.reset_conversation"), \
         patch("app.api.chat.session_store.update"), \
         patch("app.api.chat.session_store.add_history", return_value="entry1"), \
         patch("app.api.chat.session_store.cache_query_result"), \
         patch("app.api.chat.session_store.get_conversation_context", return_value=[]):

        mock_agent = MagicMock()
        mock_agent.run_streaming = mock_agent_stream
        mock_agent_class.return_value = mock_agent

        stream = _stream_chat(
            session_id="test-session",
            session=session,
            message="test",
            mode=ChatMode.ANALYST,
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            include_reasoning=False,
            include_chart=False,
            continue_conversation=False,
        )

        events = await collect_stream_events(stream)

        # Extract progress values (skip None)
        progress_values = [e.get("progress") for e in events if e.get("progress") is not None]

        # Verify progress is monotonically increasing (or equal)
        for i in range(1, len(progress_values)):
            assert progress_values[i] >= progress_values[i-1], \
                f"Progress should be monotonically increasing: {progress_values}"

        # Verify first progress is near 0 and last is 1.0
        assert progress_values[0] <= 0.2, "First progress should be low"
        assert progress_values[-1] == 1.0, "Last progress should be 1.0"


# ============================================
# ERROR HANDLING TESTS
# ============================================


@pytest.mark.asyncio
async def test_stream_error_propagation(mock_db_config, mock_llm_config):
    """Test that errors are propagated as error events in stream"""

    session = {"id": "test-session", "context_window": [], "last_query_context": None}

    async def mock_agent_stream(**kwargs):
        yield {"event": "thinking", "progress": 0.1}
        yield {"event": "error", "error": "LLM timeout"}

    with patch("app.api.chat.ReActAgent") as mock_agent_class, \
         patch("app.api.chat.session_store.reset_conversation"), \
         patch("app.api.chat.session_store.get_conversation_context", return_value=[]):
        mock_agent = MagicMock()
        mock_agent.run_streaming = mock_agent_stream
        mock_agent_class.return_value = mock_agent

        stream = _stream_chat(
            session_id="test-session",
            session=session,
            message="test",
            mode=ChatMode.ANALYST,
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            include_reasoning=False,
            include_chart=False,
            continue_conversation=False,
        )

        events = await collect_stream_events(stream)

        # Should have thinking and error events
        assert len(events) >= 2
        assert events[0]["event"] == "thinking"

        # Should have error event with timeout message
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) >= 1
        assert "timeout" in error_events[0]["content"].lower()


@pytest.mark.asyncio
async def test_stream_exception_handling(mock_db_config, mock_llm_config):
    """Test that exceptions during streaming are caught and emitted as error events"""

    session = {"id": "test-session", "context_window": [], "last_query_context": None}

    async def mock_agent_stream(**kwargs):
        yield {"event": "thinking", "progress": 0.1}
        raise RuntimeError("Unexpected agent failure")

    with patch("app.api.chat.ReActAgent") as mock_agent_class, \
         patch("app.api.chat.session_store.reset_conversation"), \
         patch("app.api.chat.session_store.get_conversation_context", return_value=[]):
        mock_agent = MagicMock()
        mock_agent.run_streaming = mock_agent_stream
        mock_agent_class.return_value = mock_agent

        stream = _stream_chat(
            session_id="test-session",
            session=session,
            message="test",
            mode=ChatMode.ANALYST,
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            include_reasoning=False,
            include_chart=False,
            continue_conversation=False,
        )

        events = await collect_stream_events(stream)

        # Should emit error event
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) >= 1


# ============================================
# TIMEOUT TESTS
# ============================================


@pytest.mark.asyncio
async def test_stream_timeout_standard_mode(mock_db_config, mock_llm_config):
    """Test that streaming times out for standard mode after configured timeout"""

    session = {"id": "test-session", "context_window": []}

    # Mock slow SQL generator that never completes
    async def slow_sql_generator():
        for i in range(100):
            await asyncio.sleep(1)  # Intentionally slow
            yield f"SELECT_{i} "

    with patch("app.api.chat.SQLGenerationService.prepare_context") as mock_prepare, \
         patch("app.api.chat.LLMService.generate_sql") as mock_llm, \
         patch("app.api.chat.vector_db.find_similar_queries", return_value=[]), \
         patch("app.api.chat.settings.AGENT_TIMEOUT_SECONDS", 0.1):  # Very short timeout

        mock_ctx = MagicMock()
        mock_ctx.sanitized_query = "test"
        mock_ctx.relevant_schema = "test"
        mock_ctx.conversation_history = []
        mock_ctx.natural_language = "test"
        mock_ctx.is_follow_up = False
        mock_ctx.db_config = mock_db_config
        mock_ctx.llm_config = mock_llm_config
        mock_prepare.return_value = (mock_ctx, None)

        mock_llm.return_value = (slow_sql_generator(), {})

        stream = _stream_chat(
            session_id="test-session",
            session=session,
            message="test",
            mode=ChatMode.STANDARD,
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            include_reasoning=False,
            include_chart=False,
            continue_conversation=False,
        )

        events = await collect_stream_events(stream)

        # Should eventually emit timeout error
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) >= 1
        # Check that timeout or timed out is in the error message
        error_msg = error_events[0]["content"].lower()
        assert "timeout" in error_msg or "timed out" in error_msg


# ============================================
# DATA SERIALIZATION TESTS
# ============================================


@pytest.mark.asyncio
async def test_stream_data_serialization_complex_types(mock_db_config, mock_llm_config):
    """Test that complex data types are properly serialized in stream events"""

    session = {"id": "test-session", "context_window": [], "last_query_context": None}

    # Include complex data types in result
    async def mock_agent_stream(**kwargs):
        yield {"event": "thinking", "progress": 0.1}
        yield {
            "event": "complete",
            "result": {
                "success": True,
                "sql": "SELECT * FROM orders WHERE created_at > '2024-01-01'",
                "execution_result": {
                    "success": True,
                    "columns": ["id", "total", "created_at"],
                    "rows": [
                        [1, 99.99, "2024-01-15T10:30:00"],
                        [2, 150.50, "2024-01-20T14:45:00"]
                    ],
                    "row_count": 2,
                    "has_analysis": True,
                    "insights": [{"severity": "info", "description": "2 orders"}],
                    "chart": {
                        "recommended_chart": "line",
                        "title": "Orders Over Time",
                        "config": {"x_axis": "created_at", "y_axis": "total"}
                    },
                    "quality": {"overall_score": 90, "completeness": 100, "issues": []}
                },
                "tools_used": ["execute_and_analyze"],
                "total_steps": 1
            }
        }

    with patch("app.api.chat.ReActAgent") as mock_agent_class, \
         patch("app.api.chat.sql_integrity.register_sql", return_value="hash"), \
         patch("app.api.chat.query_history_service.save_query", new_callable=AsyncMock), \
         patch("app.api.chat.generate_data_summary", return_value="Found 2 orders"), \
         patch("app.api.chat.session_store.reset_conversation"), \
         patch("app.api.chat.session_store.update"), \
         patch("app.api.chat.session_store.add_history", return_value="entry1"), \
         patch("app.api.chat.session_store.cache_query_result"), \
         patch("app.api.chat.session_store.get_conversation_context", return_value=[]):

        mock_agent = MagicMock()
        mock_agent.run_streaming = mock_agent_stream
        mock_agent_class.return_value = mock_agent

        stream = _stream_chat(
            session_id="test-session",
            session=session,
            message="recent orders",
            mode=ChatMode.ANALYST,
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            include_reasoning=False,
            include_chart=True,
            continue_conversation=False,
        )

        events = await collect_stream_events(stream)

        # Find done event
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1

        done_data = done_events[0]["data"]

        # Verify all complex data serialized correctly
        assert isinstance(done_data["sql"], str)
        assert isinstance(done_data["key_findings"], list)
        assert isinstance(done_data["chart"], dict)
        assert done_data["chart"]["chart_type"] == "line"
        assert isinstance(done_data["raw_result"], dict)
        assert done_data["raw_result"]["row_count"] == 2
        assert isinstance(done_data["tools_used"], list)
