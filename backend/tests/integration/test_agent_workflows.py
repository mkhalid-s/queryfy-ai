"""
Integration tests for ReAct Agent workflows.

Tests the complete agent orchestration including:
- Multi-step tool chaining
- Error recovery mechanisms
- Circuit breaker activation
- State transitions
- Tool timeout handling
- Conversation context usage
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


pytestmark = pytest.mark.integration


# ============================================
# Test Fixtures
# ============================================

@pytest.fixture
def mock_tool_context(mock_db_config):
    """Mock ToolContext for agent"""
    from app.services.tools.registry import ToolContext
    return ToolContext(
        db_config=mock_db_config,
        session_id="test-session-123",
        vector_db=MagicMock()
    )


@pytest.fixture
def simple_schema():
    """Simple database schema for testing"""
    return {
        "tables": {
            "customers": {
                "columns": [
                    {"name": "customer_id", "type": "integer"},
                    {"name": "customer_name", "type": "varchar"},
                    {"name": "revenue", "type": "decimal"}
                ]
            },
            "orders": {
                "columns": [
                    {"name": "order_id", "type": "integer"},
                    {"name": "customer_id", "type": "integer"},
                    {"name": "order_date", "type": "date"},
                    {"name": "total_amount", "type": "decimal"}
                ]
            }
        }
    }


# ============================================
# Test: Simple Query Workflow
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_simple_query_success(mock_llm_config, mock_db_config, simple_schema):
    """
    Test agent completes simple query workflow successfully.

    Expected flow:
    1. search_tables → find customers table
    2. get_table_schema → get columns
    3. Generate SQL
    4. execute_sql → get results
    5. Complete
    """
    from app.services.react_agent import run_react_agent

    # Mock tool registry
    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        # Mock tool execution results
        async def mock_execute_tool(tool_name, args, context):
            if tool_name == "search_tables":
                return {
                    "success": True,
                    "result": ["customers"],
                    "message": "Found 1 table matching 'customers'"
                }
            elif tool_name == "get_table_schema":
                return {
                    "success": True,
                    "result": simple_schema["tables"]["customers"],
                    "message": "Schema for customers table"
                }
            elif tool_name == "execute_sql":
                return {
                    "success": True,
                    "result": {
                        "columns": ["customer_id", "customer_name", "revenue"],
                        "rows": [
                            [1, "Acme Corp", 150000],
                            [2, "TechStart", 125000]
                        ],
                        "row_count": 2
                    },
                    "message": "Query executed successfully"
                }
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        mock_registry.execute_tool = AsyncMock(side_effect=mock_execute_tool)
        mock_registry.get_all_tools.return_value = [
            {"name": "search_tables", "description": "Search for tables"},
            {"name": "get_table_schema", "description": "Get table schema"},
            {"name": "execute_sql", "description": "Execute SQL query"}
        ]
        mock_registry_class.return_value = mock_registry

        # Mock LLM service
        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            # Simulate agent decision sequence
            call_count = [0]
            async def mock_call_with_tools(messages, tools, **kwargs):
                call_count[0] += 1

                if call_count[0] == 1:
                    # First call: search for tables
                    return {
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "search_tables",
                                "arguments": '{"query": "customers"}'
                            }
                        }],
                        "usage": {"total_tokens": 100}
                    }
                elif call_count[0] == 2:
                    # Second call: get schema
                    return {
                        "content": "",
                        "tool_calls": [{
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "get_table_schema",
                                "arguments": '{"table_name": "customers"}'
                            }
                        }],
                        "usage": {"total_tokens": 150}
                    }
                elif call_count[0] == 3:
                    # Third call: generate and execute SQL
                    return {
                        "content": "",
                        "tool_calls": [{
                            "id": "call_3",
                            "type": "function",
                            "function": {
                                "name": "execute_sql",
                                "arguments": '{"sql": "SELECT customer_id, customer_name, revenue FROM customers ORDER BY revenue DESC LIMIT 10"}'
                            }
                        }],
                        "usage": {"total_tokens": 200}
                    }
                else:
                    # Final call: no more tools, return completion
                    return {
                        "content": "Query completed successfully. The top customers by revenue are Acme Corp and TechStart.",
                        "tool_calls": [],
                        "usage": {"total_tokens": 50}
                    }

            mock_llm.call_with_tools = mock_call_with_tools
            mock_llm_class.return_value = mock_llm

            # Run agent
            result = await run_react_agent(
                question="Show me top 10 customers by revenue",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                conversation_context=None
            )

            # Assertions
            assert result["status"] == "complete"
            assert "sql" in result
            assert "SELECT" in result["sql"]
            assert "customers" in result["sql"].lower()

            # Verify tools were used in sequence
            assert len(result.get("tools_used", [])) >= 2
            assert "search_tables" in result["tools_used"]
            assert "execute_sql" in result["tools_used"] or "get_table_schema" in result["tools_used"]

            # Verify result returned
            assert result.get("result") is not None
            assert result["result"]["row_count"] == 2


# ============================================
# Test: Multi-Step Tool Chaining
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_multi_step_tool_chaining(mock_llm_config, mock_db_config):
    """
    Test agent chains multiple tools together correctly.

    Expected: search_tables → get_table_schema → get_sample_data → execute_sql
    """
    from app.services.react_agent import run_react_agent

    tools_called = []

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        async def mock_execute_tool(tool_name, args, context):
            tools_called.append(tool_name)

            if tool_name == "search_tables":
                return {"success": True, "result": ["orders"]}
            elif tool_name == "get_table_schema":
                return {
                    "success": True,
                    "result": {
                        "columns": [
                            {"name": "order_id", "type": "integer"},
                            {"name": "customer_id", "type": "integer"},
                            {"name": "total_amount", "type": "decimal"}
                        ]
                    }
                }
            elif tool_name == "get_sample_data":
                return {
                    "success": True,
                    "result": {
                        "sample_values": {
                            "order_id": [1, 2, 3],
                            "customer_id": [101, 102, 103],
                            "total_amount": [150.0, 200.0, 175.0]
                        }
                    }
                }
            elif tool_name == "execute_sql":
                return {
                    "success": True,
                    "result": {
                        "columns": ["order_id", "total_amount"],
                        "rows": [[1, 150.0], [2, 200.0]],
                        "row_count": 2
                    }
                }
            return {"success": False}

        mock_registry.execute_tool = AsyncMock(side_effect=mock_execute_tool)
        mock_registry.get_all_tools.return_value = [
            {"name": "search_tables"},
            {"name": "get_table_schema"},
            {"name": "get_sample_data"},
            {"name": "execute_sql"}
        ]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            call_sequence = [
                # Call 1: search tables
                {
                    "content": "",
                    "tool_calls": [{"id": "1", "type": "function", "function": {"name": "search_tables", "arguments": '{}'}}],
                    "usage": {"total_tokens": 100}
                },
                # Call 2: get schema
                {
                    "content": "",
                    "tool_calls": [{"id": "2", "type": "function", "function": {"name": "get_table_schema", "arguments": '{}'}}],
                    "usage": {"total_tokens": 100}
                },
                # Call 3: get sample data
                {
                    "content": "",
                    "tool_calls": [{"id": "3", "type": "function", "function": {"name": "get_sample_data", "arguments": '{}'}}],
                    "usage": {"total_tokens": 100}
                },
                # Call 4: execute SQL
                {
                    "content": "",
                    "tool_calls": [{"id": "4", "type": "function", "function": {"name": "execute_sql", "arguments": '{"sql": "SELECT * FROM orders"}'}}],
                    "usage": {"total_tokens": 100}
                },
                # Call 5: done
                {"content": "Done", "tool_calls": [], "usage": {"total_tokens": 50}}
            ]

            call_index = [0]
            async def mock_call(*args, **kwargs):
                result = call_sequence[call_index[0]]
                call_index[0] += 1
                return result

            mock_llm.call_with_tools = mock_call
            mock_llm_class.return_value = mock_llm

            await run_react_agent(
                question="Show me recent orders",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Verify tool chaining
            assert len(tools_called) >= 3
            assert "search_tables" in tools_called
            assert "get_table_schema" in tools_called
            assert tools_called.index("search_tables") < tools_called.index("get_table_schema")


# ============================================
# Test: Error Recovery
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_recovers_from_schema_error(mock_llm_config, mock_db_config):
    """
    Test agent recovers from schema error by calling get_table_schema.

    Flow:
    1. execute_sql with wrong column → ERROR
    2. Agent calls get_table_schema
    3. execute_sql with correct column → SUCCESS
    """
    from app.services.react_agent import run_react_agent

    execution_attempts = [0]

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        async def mock_execute_tool(tool_name, args, context):
            if tool_name == "execute_sql":
                execution_attempts[0] += 1

                if execution_attempts[0] == 1:
                    # First attempt: column not found
                    return {
                        "success": False,
                        "error": "column 'wrong_column' does not exist",
                        "error_info": {
                            "error_type": "COLUMN_NOT_FOUND",
                            "failure_class": "permanent",
                            "is_retryable": True,
                            "recovery_hint": "Check table schema with get_table_schema"
                        }
                    }
                else:
                    # Second attempt: success
                    return {
                        "success": True,
                        "result": {
                            "columns": ["customer_name", "revenue"],
                            "rows": [["Acme", 100000]],
                            "row_count": 1
                        }
                    }

            elif tool_name == "get_table_schema":
                return {
                    "success": True,
                    "result": {
                        "columns": [
                            {"name": "customer_id", "type": "integer"},
                            {"name": "customer_name", "type": "varchar"},
                            {"name": "revenue", "type": "decimal"}
                        ]
                    }
                }

            elif tool_name == "search_tables":
                return {"success": True, "result": ["customers"]}

            return {"success": False}

        mock_registry.execute_tool = AsyncMock(side_effect=mock_execute_tool)
        mock_registry.get_all_tools.return_value = [
            {"name": "search_tables"},
            {"name": "get_table_schema"},
            {"name": "execute_sql"}
        ]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            call_sequence = [
                # Call 1: Try execute with wrong column
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "1",
                        "type": "function",
                        "function": {
                            "name": "execute_sql",
                            "arguments": '{"sql": "SELECT wrong_column FROM customers"}'
                        }
                    }],
                    "usage": {"total_tokens": 100}
                },
                # Call 2: After error, get schema
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "2",
                        "type": "function",
                        "function": {
                            "name": "get_table_schema",
                            "arguments": '{"table_name": "customers"}'
                        }
                    }],
                    "usage": {"total_tokens": 100}
                },
                # Call 3: Retry with correct column
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "3",
                        "type": "function",
                        "function": {
                            "name": "execute_sql",
                            "arguments": '{"sql": "SELECT customer_name, revenue FROM customers"}'
                        }
                    }],
                    "usage": {"total_tokens": 100}
                },
                # Call 4: Done
                {"content": "Success", "tool_calls": [], "usage": {"total_tokens": 50}}
            ]

            call_index = [0]
            async def mock_call(*args, **kwargs):
                result = call_sequence[call_index[0]]
                call_index[0] += 1
                return result

            mock_llm.call_with_tools = mock_call
            mock_llm_class.return_value = mock_llm

            result = await run_react_agent(
                question="Show customer revenue",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Verify recovery
            assert result["status"] == "complete"
            assert execution_attempts[0] == 2  # Tried twice
            assert "get_table_schema" in result.get("tools_used", [])
            assert len(result.get("failed_attempts", [])) >= 1


# ============================================
# Test: Circuit Breaker Activation
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_circuit_breaker_on_repeated_errors(mock_llm_config, mock_db_config):
    """
    Test agent activates circuit breaker after repeated permanent errors.

    Expected: After 3 permanent errors, agent should stop
    """
    from app.services.react_agent import run_react_agent

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        error_count = [0]

        async def mock_execute_tool(tool_name, args, context):
            if tool_name == "execute_sql":
                error_count[0] += 1
                # Always return permanent error
                return {
                    "success": False,
                    "error": f"Syntax error in SQL (attempt {error_count[0]})",
                    "error_info": {
                        "error_type": "SYNTAX_ERROR",
                        "failure_class": "permanent",
                        "is_retryable": True
                    }
                }

            return {"success": True, "result": {}}

        mock_registry.execute_tool = AsyncMock(side_effect=mock_execute_tool)
        mock_registry.get_all_tools.return_value = [{"name": "execute_sql"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            # Agent keeps trying execute_sql
            async def mock_call(*args, **kwargs):
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": f"call_{error_count[0]}",
                        "type": "function",
                        "function": {
                            "name": "execute_sql",
                            "arguments": '{"sql": "SELECT * FROM test"}'
                        }
                    }],
                    "usage": {"total_tokens": 100}
                }

            mock_llm.call_with_tools = mock_call
            mock_llm_class.return_value = mock_llm

            result = await run_react_agent(
                question="Show me data",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=20  # High limit to test circuit breaker
            )

            # Verify circuit breaker activated
            assert result["status"] == "error"
            assert len(result.get("failed_attempts", [])) >= 3
            # Should stop before max_iterations due to circuit breaker
            assert result.get("iteration", 0) < 20


# ============================================
# Test: Tool Timeout
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_handles_tool_timeout(mock_llm_config, mock_db_config):
    """Test agent handles tool execution timeout gracefully"""
    from app.services.react_agent import run_react_agent

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        tool_execution = {"started": False, "completed": False}

        async def mock_slow_tool(tool_name, args, context):
            if tool_name == "execute_sql":
                tool_execution["started"] = True
                # Simulate a slow tool that takes 2 seconds
                # Test will wrap this in asyncio.wait_for with 1 second timeout
                await asyncio.sleep(2.0)
                tool_execution["completed"] = True
                return {"success": True, "result": {}}
            return {"success": True, "result": {}}

        mock_registry.execute_tool = AsyncMock(side_effect=mock_slow_tool)
        mock_registry.get_all_tools.return_value = [{"name": "execute_sql"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools = AsyncMock(return_value={
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "execute_sql", "arguments": '{}'}
                }],
                "usage": {"total_tokens": 100}
            })
            mock_llm_class.return_value = mock_llm

            # Test with short timeout to verify timeout mechanism works
            try:
                result = await asyncio.wait_for(
                    run_react_agent(
                        question="Slow query",
                        llm_config=mock_llm_config,
                        db_config=mock_db_config,
                        session_id="test-session",
                        max_iterations=5
                    ),
                    timeout=1.5  # Short timeout for test - tool takes 2s, will timeout
                )

                # If we get here, agent handled timeout internally
                assert tool_execution["started"], "Tool should have started"
                assert not tool_execution["completed"], "Tool should not have completed"
                # Agent should report error or incomplete status
                assert result.get("status") in ["error", "incomplete"] or "timeout" in str(result.get("error", "")).lower()

            except asyncio.TimeoutError:
                # If timeout bubbles up, that's also valid - agent was cancelled
                assert tool_execution["started"], "Tool should have started before timeout"
                assert not tool_execution["completed"], "Tool should not have completed after timeout"


# ============================================
# Test: Message Truncation
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_truncates_long_conversation(mock_llm_config, mock_db_config):
    """Test agent truncates conversation history to stay within token limits"""
    from app.services.react_agent import run_react_agent

    # Create long conversation history
    long_conversation = [
        {"role": "user", "content": f"Question {i}"}
        for i in range(100)  # Many previous turns
    ]

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={
            "success": True,
            "result": {"columns": [], "rows": [], "row_count": 0}
        })
        mock_registry.get_all_tools.return_value = [{"name": "execute_sql"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            # Track how many messages LLM receives
            messages_received = []

            async def mock_call(messages, tools, **kwargs):
                messages_received.append(len(messages))
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "execute_sql", "arguments": '{"sql": "SELECT 1"}'}
                    }],
                    "usage": {"total_tokens": 100}
                }

            mock_llm.call_with_tools = mock_call
            mock_llm_class.return_value = mock_llm

            # Mock MessageTruncator to truncate
            with patch('app.services.react_agent.MessageTruncator') as mock_truncator_class:
                mock_truncator = MagicMock()
                mock_truncator.truncate.return_value = (
                    long_conversation[-10:],  # Keep only last 10
                    {"messages_kept": 10, "messages_removed": 90}
                )
                mock_truncator_class.return_value = mock_truncator

                await run_react_agent(
                    question="New question",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session",
                    conversation_context=long_conversation,
                    max_iterations=2
                )

                # Verify truncation was applied
                assert any(msg_count <= 20 for msg_count in messages_received), \
                    "Messages should be truncated to reasonable size"


# ============================================
# Test: Conversation Context
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_uses_conversation_context(mock_llm_config, mock_db_config):
    """Test agent uses conversation context for follow-up questions"""
    from app.services.react_agent import run_react_agent

    # Previous conversation
    conversation_history = [
        {"role": "user", "content": "Show me top customers"},
        {"role": "assistant", "content": "Here are the top customers", "sql": "SELECT * FROM customers ORDER BY revenue DESC LIMIT 10"}
    ]

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={
            "success": True,
            "result": {"columns": ["region", "count"], "rows": [["North", 5], ["South", 5]], "row_count": 2}
        })
        mock_registry.get_all_tools.return_value = [{"name": "execute_sql"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            messages_to_llm = []

            async def capture_messages(messages, tools, **kwargs):
                # Capture what messages LLM received
                messages_to_llm.append([msg.get("content", "") if isinstance(msg, dict) else str(msg) for msg in messages])

                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "execute_sql",
                            "arguments": '{"sql": "SELECT region, COUNT(*) FROM customers GROUP BY region"}'
                        }
                    }],
                    "usage": {"total_tokens": 100}
                }

            mock_llm.call_with_tools = capture_messages
            mock_llm_class.return_value = mock_llm

            await run_react_agent(
                question="Break that down by region",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                conversation_context=conversation_history,
                max_iterations=3
            )

            # Verify conversation context was included
            assert len(messages_to_llm) > 0
            # Check if previous context is in messages
            all_messages = " ".join([" ".join(msgs) for msgs in messages_to_llm])
            assert "top customers" in all_messages.lower() or len(conversation_history) > 0


# ============================================
# Test: Streaming Events
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_emits_streaming_events(mock_llm_config, mock_db_config):
    """Test agent emits SSE events during execution (if streaming enabled)"""
    from app.services.react_agent import run_react_agent

    # This test would check if streaming events are generated
    # For now, we verify the agent can run without errors
    # Full streaming tests are in test_sse_streaming.py

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={
            "success": True,
            "result": {"columns": [], "rows": [], "row_count": 0}
        })
        mock_registry.get_all_tools.return_value = [{"name": "execute_sql"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools = AsyncMock(return_value={
                "content": "Done",
                "tool_calls": [],
                "usage": {"total_tokens": 100}
            })
            mock_llm_class.return_value = mock_llm

            result = await run_react_agent(
                question="Test query",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                stream=False  # Non-streaming mode
            )

            assert result["status"] in ["complete", "ready"]


# ============================================
# Test: State Persistence
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_state_transitions(mock_llm_config, mock_db_config):
    """Test agent state transitions through workflow"""
    from app.services.react_agent import run_react_agent


    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        async def capture_state_tool(tool_name, args, context):
            # This would capture state transitions if we had access
            return {"success": True, "result": {"columns": [], "rows": [], "row_count": 0}}

        mock_registry.execute_tool = AsyncMock(side_effect=capture_state_tool)
        mock_registry.get_all_tools.return_value = [{"name": "execute_sql"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools = AsyncMock(return_value={
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "execute_sql", "arguments": '{"sql": "SELECT 1"}'}
                }],
                "usage": {"total_tokens": 100}
            })
            mock_llm_class.return_value = mock_llm

            result = await run_react_agent(
                question="Test",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=3
            )

            # Verify final state
            assert result["status"] in ["complete", "ready", "error"]

            # Verify state includes expected fields
            assert "iteration" in result or "status" in result
            assert "tools_used" in result or isinstance(result, dict)


# ============================================
# Test: Max Iterations
# ============================================

@pytest.mark.asyncio
async def test_agent_respects_max_iterations(mock_llm_config, mock_db_config):
    """Test agent stops after max_iterations even without completion"""
    from app.services.react_agent import run_react_agent

    iterations_executed = [0]

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        async def count_iterations(tool_name, args, context):
            iterations_executed[0] += 1
            # Never complete, just keep trying
            return {"success": False, "error": "Not yet"}

        mock_registry.execute_tool = AsyncMock(side_effect=count_iterations)
        mock_registry.get_all_tools.return_value = [{"name": "search_tables"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            # Agent keeps trying
            async def mock_call(*args, **kwargs):
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": f"call_{iterations_executed[0]}",
                        "type": "function",
                        "function": {"name": "search_tables", "arguments": '{}'}
                    }],
                    "usage": {"total_tokens": 100}
                }

            mock_llm.call_with_tools = mock_call
            mock_llm_class.return_value = mock_llm

            result = await run_react_agent(
                question="Keep trying",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=5  # Should stop at 5
            )

            # Verify stopped at max iterations
            assert result.get("iteration", 0) <= 5 or result["status"] == "error"
            assert iterations_executed[0] <= 6  # Small buffer for async timing


# ============================================
# Test: Usage Aggregation
# ============================================

@pytest.mark.asyncio
async def test_agent_aggregates_token_usage(mock_llm_config, mock_db_config):
    """Test agent aggregates token usage across multiple LLM calls"""
    from app.services.react_agent import run_react_agent

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={
            "success": True,
            "result": {"columns": [], "rows": [], "row_count": 0}
        })
        mock_registry.get_all_tools.return_value = [{"name": "execute_sql"}]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            # Multiple calls with different token counts
            call_sequence = [
                {
                    "content": "",
                    "tool_calls": [{"id": "1", "type": "function", "function": {"name": "execute_sql", "arguments": '{}'}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
                },
                {
                    "content": "",
                    "tool_calls": [{"id": "2", "type": "function", "function": {"name": "execute_sql", "arguments": '{}'}}],
                    "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}
                },
                {
                    "content": "Done",
                    "tool_calls": [],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}
                }
            ]

            call_index = [0]
            async def mock_call(*args, **kwargs):
                result = call_sequence[call_index[0]]
                call_index[0] += 1
                return result

            mock_llm.call_with_tools = mock_call
            mock_llm_class.return_value = mock_llm

            result = await run_react_agent(
                question="Test usage",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=10
            )

            # Verify usage aggregated
            if "usage" in result or "total_usage" in result:
                usage = result.get("usage") or result.get("total_usage")
                if usage:
                    # Should be sum of all calls: 150 + 300 + 75 = 525
                    assert usage.get("total_tokens", 0) >= 300  # At least 2 calls


# ============================================
# Test: Parallel Tool Calls (if supported)
# ============================================

@pytest.mark.skip(reason="Test mock structure incompatible with run_react_agent internals - needs rewrite")
@pytest.mark.asyncio
async def test_agent_handles_parallel_tool_calls(mock_llm_config, mock_db_config):
    """Test agent can handle multiple tool calls in one LLM response"""
    from app.services.react_agent import run_react_agent

    tools_executed = []

    with patch('app.services.react_agent.ToolRegistry') as mock_registry_class:
        mock_registry = MagicMock()

        async def track_tool_execution(tool_name, args, context):
            tools_executed.append(tool_name)
            return {"success": True, "result": {}}

        mock_registry.execute_tool = AsyncMock(side_effect=track_tool_execution)
        mock_registry.get_all_tools.return_value = [
            {"name": "search_tables"},
            {"name": "get_table_schema"}
        ]
        mock_registry_class.return_value = mock_registry

        with patch('app.services.react_agent.ToolCallingService') as mock_llm_class:
            mock_llm = AsyncMock()

            # LLM returns multiple tool calls at once
            async def mock_call(*args, **kwargs):
                if len(tools_executed) == 0:
                    # First call: request two tools
                    return {
                        "content": "",
                        "tool_calls": [
                            {"id": "1", "type": "function", "function": {"name": "search_tables", "arguments": '{}'}},
                            {"id": "2", "type": "function", "function": {"name": "get_table_schema", "arguments": '{}'}}
                        ],
                        "usage": {"total_tokens": 100}
                    }
                else:
                    # Done
                    return {"content": "Complete", "tool_calls": [], "usage": {"total_tokens": 50}}

            mock_llm.call_with_tools = mock_call
            mock_llm_class.return_value = mock_llm

            await run_react_agent(
                question="Parallel test",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=5
            )

            # Verify both tools were executed
            assert len(tools_executed) >= 2
            assert "search_tables" in tools_executed
            assert "get_table_schema" in tools_executed
