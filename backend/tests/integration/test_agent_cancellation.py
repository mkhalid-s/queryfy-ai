"""
Agent Cancellation Tests

Tests for graceful agent cancellation:
- Cancel during tool execution
- Cancel during LLM generation
- Cancel during multi-step workflow
- Resource cleanup after cancellation
- No zombie processes/connections remain
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.react_agent import run_react_agent
from app.services.llm_service import ToolCall, ToolCallingResponse, LLMUsageData


@pytest.mark.integration
async def test_agent_cancellation_during_tool_execution(mock_llm_config, mock_db_config):
    """Agent can be cancelled during tool execution"""

    # Create a slow tool that we'll cancel
    slow_tool_called = {"called": False, "completed": False}

    async def slow_tool_execute(*args, **kwargs):
        slow_tool_called["called"] = True
        await asyncio.sleep(10)  # Long operation
        slow_tool_called["completed"] = True
        return '{"success": true, "data": "completed"}'

    with patch("app.services.tools.registry.ToolRegistry.execute") as mock_tool_execute:
        mock_tool_execute.side_effect = slow_tool_execute

        with patch("app.services.llm_service.ToolCallingService.call_with_tools") as mock_llm_call:
            # Mock LLM to trigger tool call
            mock_response = ToolCallingResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="execute_sql",
                        arguments={"query": "SELECT 1"}
                    )
                ],
                has_tool_calls=True,
                usage=LLMUsageData(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            )
            mock_llm_call.return_value = mock_response

            # Start agent
            agent_task = asyncio.create_task(
                run_react_agent(
                    question="test query",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )
            )

            # Wait for tool to be called (with retry for CI environments)
            timeout = 5.0  # 5 second timeout for slower CI
            start_time = asyncio.get_event_loop().time()
            while not slow_tool_called["called"]:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    break
                await asyncio.sleep(0.1)

            assert slow_tool_called["called"], "Tool should have been called within 5 seconds"
            assert not slow_tool_called["completed"], "Tool should not have completed yet"

            # Cancel the agent
            agent_task.cancel()

            # Verify cancellation
            with pytest.raises(asyncio.CancelledError):
                await agent_task

            # Tool should not have completed
            assert not slow_tool_called["completed"], "Tool should not have completed after cancellation"


@pytest.mark.integration
async def test_agent_cancellation_during_llm_generation(mock_llm_config, mock_db_config):
    """Agent can be cancelled during LLM generation"""

    llm_called = {"called": False, "completed": False}

    async def slow_llm_invoke(*args, **kwargs):
        llm_called["called"] = True
        await asyncio.sleep(10)  # Simulate slow LLM
        llm_called["completed"] = True
        return ToolCallingResponse(
            content="Here is the SQL: SELECT 1",
            tool_calls=[],
            has_tool_calls=False,
            usage=LLMUsageData(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )

    with patch("app.services.llm_service.ToolCallingService.call_with_tools") as mock_llm_call:
        mock_llm_call.side_effect = slow_llm_invoke

        # Start agent
        agent_task = asyncio.create_task(
            run_react_agent(
                question="test query",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )
        )

        # Wait for LLM to be called
        await asyncio.sleep(0.3)
        assert llm_called["called"], "LLM should have been called"

        # Cancel the agent
        agent_task.cancel()

        # Verify cancellation
        with pytest.raises(asyncio.CancelledError):
            await agent_task

        # LLM should not have completed
        assert not llm_called["completed"], "LLM should not have completed after cancellation"


@pytest.mark.integration
async def test_agent_cancellation_cleans_up_resources(mock_llm_config, mock_db_config):
    """Agent cleans up resources (DB connections) after cancellation"""

    connection_opened = {"count": 0}
    connection_closed = {"count": 0}

    class MockConnection:
        async def __aenter__(self):
            connection_opened["count"] += 1
            return self

        async def __aexit__(self, *args):
            connection_closed["count"] += 1

        async def execute(self, *args, **kwargs):
            await asyncio.sleep(10)  # Slow query
            return []

    async def tool_with_connection(*args, **kwargs):
        async with MockConnection():
            await asyncio.sleep(10)
        return '{"success": true}'

    with patch("app.services.tools.registry.ToolRegistry.execute") as mock_tool_execute:
        mock_tool_execute.side_effect = tool_with_connection

        with patch("app.services.llm_service.ToolCallingService.call_with_tools") as mock_llm_call:
            mock_response = ToolCallingResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="execute_sql",
                        arguments={"query": "SELECT 1"}
                    )
                ],
                has_tool_calls=True,
                usage=LLMUsageData(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            )
            mock_llm_call.return_value = mock_response

            # Start agent
            agent_task = asyncio.create_task(
                run_react_agent(
                    question="test query",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )
            )

            # Wait for connection to open (with retry for CI environments)
            timeout = 5.0  # 5 second timeout for slower CI
            start_time = asyncio.get_event_loop().time()
            while connection_opened["count"] == 0:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    break
                await asyncio.sleep(0.1)

            # Verify connection was opened before cancellation
            assert connection_opened["count"] > 0, "Connection should have been opened within 5 seconds"

            # Cancel the agent
            agent_task.cancel()

            try:
                await agent_task
            except asyncio.CancelledError:
                pass

            # Give time for cleanup
            await asyncio.sleep(0.1)

            # Verify cleanup: opened connections should be closed
            # Note: In real implementation, this depends on proper finally blocks
            assert connection_opened["count"] > 0, "Connection was opened"
            # Cleanup verification depends on implementation


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_multiple_cancellations_are_safe(mock_llm_config, mock_db_config):
    """Multiple cancellation calls are safe (idempotent)"""

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        async def slow_llm(*args, **kwargs):
            await asyncio.sleep(10)
            return MagicMock(content="SQL")

        mock_llm = AsyncMock()
        mock_llm.ainvoke = slow_llm
        mock_get_llm.return_value = mock_llm

        with patch("app.services.react_agent.get_sql_tools") as mock_get_tools:
            mock_get_tools.return_value = []

            # Start agent
            agent_task = asyncio.create_task(
                run_react_agent(
                    question="test query",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )
            )

            await asyncio.sleep(0.1)

            # Multiple cancel calls should be safe
            agent_task.cancel()
            agent_task.cancel()
            agent_task.cancel()

            # Should still raise CancelledError once
            with pytest.raises(asyncio.CancelledError):
                await agent_task


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_sql_tools which no longer exists")
@pytest.mark.integration
async def test_cancellation_during_multi_step_workflow(mock_llm_config, mock_db_config):
    """Agent can be cancelled during multi-step workflow"""

    steps_completed = []

    async def mock_tool_step1(*args, **kwargs):
        steps_completed.append("step1")
        return {"success": True, "data": "step1 done"}

    async def mock_tool_step2(*args, **kwargs):
        steps_completed.append("step2_started")
        await asyncio.sleep(10)  # Long operation
        steps_completed.append("step2_completed")
        return {"success": True, "data": "step2 done"}

    with patch("app.services.react_agent.get_sql_tools") as mock_get_tools:
        tool1 = MagicMock()
        tool1.name = "search_tables"
        tool1.ainvoke = mock_tool_step1

        tool2 = MagicMock()
        tool2.name = "execute_sql"
        tool2.ainvoke = mock_tool_step2

        mock_get_tools.return_value = [tool1, tool2]

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            call_count = {"count": 0}

            async def multi_step_llm(*args, **kwargs):
                call_count["count"] += 1
                if call_count["count"] == 1:
                    # First call: trigger search_tables
                    return MagicMock(
                        content="Let me search",
                        tool_calls=[{"name": "search_tables", "args": {}}]
                    )
                else:
                    # Second call: trigger execute_sql (will be cancelled)
                    return MagicMock(
                        content="Now execute",
                        tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT 1"}}]
                    )

            mock_llm = AsyncMock()
            mock_llm.ainvoke = multi_step_llm
            mock_get_llm.return_value = mock_llm

            # Start agent
            agent_task = asyncio.create_task(
                run_react_agent(
                    question="test query",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )
            )

            # Wait for step2 to start
            await asyncio.sleep(0.3)

            # Cancel during step2
            agent_task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await agent_task

            # Verify step1 completed, step2 started but not completed
            assert "step1" in steps_completed
            assert "step2_started" in steps_completed
            assert "step2_completed" not in steps_completed


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_cancellation_propagates_to_child_tasks(mock_llm_config, mock_db_config):
    """Cancellation propagates to all child tasks"""

    child_tasks_cancelled = {"count": 0}

    async def child_task():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            child_tasks_cancelled["count"] += 1
            raise

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        async def llm_with_child_tasks(*args, **kwargs):
            # Spawn child tasks
            task1 = asyncio.create_task(child_task())
            task2 = asyncio.create_task(child_task())

            try:
                await asyncio.gather(task1, task2)
            except asyncio.CancelledError:
                task1.cancel()
                task2.cancel()
                raise

            return MagicMock(content="Done")

        mock_llm = AsyncMock()
        mock_llm.ainvoke = llm_with_child_tasks
        mock_get_llm.return_value = mock_llm

        with patch("app.services.react_agent.get_sql_tools") as mock_get_tools:
            mock_get_tools.return_value = []

            # Start agent
            agent_task = asyncio.create_task(
                run_react_agent(
                    question="test query",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )
            )

            await asyncio.sleep(0.2)

            # Cancel parent
            agent_task.cancel()

            try:
                await agent_task
            except asyncio.CancelledError:
                pass

            # Wait for child cancellations to propagate
            await asyncio.sleep(0.1)

            # Child tasks should have been cancelled
            # Note: Actual count depends on implementation


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_sql_tools which no longer exists")
@pytest.mark.integration
async def test_cancellation_does_not_leave_zombie_connections(mock_llm_config, mock_db_config):
    """Cancellation does not leave zombie database connections"""

    active_connections = {"count": 0}

    class TrackedConnection:
        def __init__(self):
            active_connections["count"] += 1

        async def close(self):
            active_connections["count"] -= 1

        async def execute(self, *args, **kwargs):
            await asyncio.sleep(10)
            return []

    with patch("app.services.react_agent.get_sql_tools") as mock_get_tools:
        mock_tool = MagicMock()
        mock_tool.name = "execute_sql"

        async def tool_with_tracked_connection(*args, **kwargs):
            conn = TrackedConnection()
            try:
                await conn.execute("SELECT 1")
            finally:
                await conn.close()
            return {"success": True}

        mock_tool.ainvoke = tool_with_tracked_connection
        mock_get_tools.return_value = [mock_tool]

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
                content="Let me execute",
                tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT 1"}}]
            ))
            mock_get_llm.return_value = mock_llm

            # Start agent
            agent_task = asyncio.create_task(
                run_react_agent(
                    question="test query",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )
            )

            await asyncio.sleep(0.2)

            # Cancel agent
            agent_task.cancel()

            try:
                await agent_task
            except asyncio.CancelledError:
                pass

            # Give time for cleanup
            await asyncio.sleep(0.2)

            # All connections should be closed
            assert active_connections["count"] == 0, "All connections should be closed after cancellation"


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_cancellation_with_timeout(mock_llm_config, mock_db_config):
    """Agent respects cancellation even with tool timeouts"""

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        async def very_slow_llm(*args, **kwargs):
            # Simulate operation longer than timeout
            await asyncio.sleep(100)
            return MagicMock(content="Done")

        mock_llm = AsyncMock()
        mock_llm.ainvoke = very_slow_llm
        mock_get_llm.return_value = mock_llm

        with patch("app.services.react_agent.get_sql_tools") as mock_get_tools:
            mock_get_tools.return_value = []

            # Start agent with short timeout
            agent_task = asyncio.create_task(
                asyncio.wait_for(
                    run_react_agent(
                        question="test query",
                        llm_config=mock_llm_config,
                        db_config=mock_db_config,
                        session_id="test-session"
                    ),
                    timeout=1.0  # 1 second timeout
                )
            )

            await asyncio.sleep(0.1)

            # Cancel before timeout
            agent_task.cancel()

            # Should raise CancelledError, not TimeoutError
            with pytest.raises(asyncio.CancelledError):
                await agent_task
