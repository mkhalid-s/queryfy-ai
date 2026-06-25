"""
Database Resilience Tests

Tests for agent recovery from database failures:
- Connection loss during query execution
- Connection pool exhaustion
- Database timeout errors
- Schema change detection
- Read-only mode handling
- Transaction rollback on failure
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.react_agent import run_react_agent


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_recovers_from_connection_loss(mock_llm_config, mock_db_config):
    """Agent recovers from database connection loss"""

    execution_attempts = {"count": 0}

    async def mock_execute_with_connection_loss(*args, **kwargs):
        execution_attempts["count"] += 1

        if execution_attempts["count"] == 1:
            # First attempt: connection lost
            raise ConnectionError("Connection to database lost")
        else:
            # Second attempt: success
            return {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_with_connection_loss

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            call_count = {"count": 0}

            async def mock_llm(*args, **kwargs):
                call_count["count"] += 1
                if call_count["count"] == 1:
                    return MagicMock(
                        content="SELECT * FROM users",
                        tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM users"}}]
                    )
                else:
                    # Retry after connection error
                    return MagicMock(
                        content="Retrying connection",
                        tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM users"}}]
                    )

            mock_llm_instance = AsyncMock()
            mock_llm_instance.ainvoke = mock_llm
            mock_get_llm.return_value = mock_llm_instance

            result = await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Agent should recover and complete
            assert result["status"] == "complete"
            assert execution_attempts["count"] == 2, "Should retry after connection loss"


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_connection_pool_exhaustion(mock_llm_config, mock_db_config):
    """Agent handles connection pool exhaustion gracefully"""

    async def mock_execute_pool_exhausted(*args, **kwargs):
        raise Exception("Connection pool exhausted - too many connections")

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_pool_exhausted

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            mock_llm_instance = AsyncMock()
            mock_llm_instance.ainvoke = AsyncMock(return_value=MagicMock(
                content="SELECT * FROM users",
                tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM users"}}]
            ))
            mock_get_llm.return_value = mock_llm_instance

            result = await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=3
            )

            # Agent should fail gracefully (not crash)
            assert result["status"] in ["error", "complete"]
            # Should have error message about connection pool
            if result["status"] == "error":
                assert "connection" in result.get("error", "").lower() or \
                       "pool" in result.get("error", "").lower()


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_database_timeout(mock_llm_config, mock_db_config):
    """Agent handles database query timeout errors"""

    execution_attempts = {"count": 0}

    async def mock_execute_with_timeout(*args, **kwargs):
        execution_attempts["count"] += 1

        if execution_attempts["count"] == 1:
            # First attempt: timeout
            raise asyncio.TimeoutError("Query execution timeout after 30 seconds")
        else:
            # Second attempt: success with optimized query
            return {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_with_timeout

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            call_count = {"count": 0}

            async def mock_llm(*args, **kwargs):
                call_count["count"] += 1
                if call_count["count"] == 1:
                    # First: slow query
                    return MagicMock(
                        content="SELECT * FROM large_table",
                        tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM large_table"}}]
                    )
                else:
                    # Retry with WHERE clause
                    return MagicMock(
                        content="Adding WHERE clause",
                        tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM large_table WHERE id < 100"}}]
                    )

            mock_llm_instance = AsyncMock()
            mock_llm_instance.ainvoke = mock_llm
            mock_get_llm.return_value = mock_llm_instance

            await run_react_agent(
                question="Show me data",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Agent should recover with optimized query
            assert execution_attempts["count"] >= 2, "Should retry after timeout"


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_detects_schema_changes(mock_llm_config, mock_db_config):
    """Agent detects when database schema has changed"""

    execution_attempts = {"count": 0}

    async def mock_execute_with_schema_change(*args, **kwargs):
        execution_attempts["count"] += 1

        if execution_attempts["count"] == 1:
            # First attempt: column doesn't exist (schema changed)
            return {
                "success": False,
                "error": "Column 'old_column' does not exist",
                "error_type": "COLUMN_NOT_FOUND",
                "failure_class": "permanent",
                "recovery_hint": "Use get_table_schema to verify column names"
            }
        else:
            # After schema lookup, use correct column
            return {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "new_column"],
                "row_count": 1
            }

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_with_schema_change

        with patch("app.services.tools.schema_tools.get_table_schema") as mock_schema:
            mock_schema.return_value = {
                "success": True,
                "schema": {
                    "table_name": "users",
                    "columns": [
                        {"name": "id", "type": "INTEGER"},
                        {"name": "new_column", "type": "VARCHAR"}  # Column renamed
                    ]
                }
            }

            with patch("app.services.react_agent.get_llm") as mock_get_llm:
                call_count = {"count": 0}

                async def mock_llm(*args, **kwargs):
                    call_count["count"] += 1
                    if call_count["count"] == 1:
                        # First: use old column name
                        return MagicMock(
                            content="SELECT old_column FROM users",
                            tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT old_column FROM users"}}]
                        )
                    elif call_count["count"] == 2:
                        # Check schema
                        return MagicMock(
                            content="Let me check schema",
                            tool_calls=[{"name": "get_table_schema", "args": {"table_name": "users"}}]
                        )
                    else:
                        # Use correct column name
                        return MagicMock(
                            content="SELECT new_column FROM users",
                            tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT new_column FROM users"}}]
                        )

                mock_llm_instance = AsyncMock()
                mock_llm_instance.ainvoke = mock_llm
                mock_get_llm.return_value = mock_llm_instance

                result = await run_react_agent(
                    question="Show me user data",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )

                # Agent should adapt to schema change
                assert result["status"] == "complete"
                assert execution_attempts["count"] == 2, "Should retry with correct schema"


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_read_only_mode(mock_llm_config, mock_db_config):
    """Agent handles database in read-only mode"""

    async def mock_execute_read_only(*args, **kwargs):
        query = kwargs.get("query", "")

        if "INSERT" in query.upper() or "UPDATE" in query.upper() or "DELETE" in query.upper():
            # Write operation in read-only mode
            return {
                "success": False,
                "error": "Database is in read-only mode",
                "error_type": "PERMISSION_ERROR",
                "failure_class": "permanent",
                "recovery_hint": "Only SELECT queries are allowed"
            }
        else:
            # Read operation succeeds
            return {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_read_only

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            call_count = {"count": 0}

            async def mock_llm(*args, **kwargs):
                call_count["count"] += 1
                if call_count["count"] == 1:
                    # First: try INSERT (fails)
                    return MagicMock(
                        content="INSERT INTO users",
                        tool_calls=[{"name": "execute_sql", "args": {"query": "INSERT INTO users VALUES (1, 'test')"}}]
                    )
                else:
                    # Switch to SELECT
                    return MagicMock(
                        content="SELECT * FROM users",
                        tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM users"}}]
                    )

            mock_llm_instance = AsyncMock()
            mock_llm_instance.ainvoke = mock_llm
            mock_get_llm.return_value = mock_llm_instance

            result = await run_react_agent(
                question="Add a user",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Agent should handle read-only mode gracefully
            assert result["status"] in ["complete", "error"]


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_transaction_rollback(mock_llm_config, mock_db_config):
    """Agent handles transaction rollback on failure"""

    operations = []

    async def mock_execute_with_rollback(*args, **kwargs):
        query = kwargs.get("query", "")
        operations.append({"query": query, "status": "attempted"})

        if "COMMIT" in query.upper():
            # Simulate commit failure
            operations.append({"query": "ROLLBACK", "status": "executed"})
            raise Exception("Transaction commit failed - rolling back")
        else:
            return {
                "success": True,
                "message": "Query executed in transaction"
            }

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_with_rollback

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            mock_llm_instance = AsyncMock()
            mock_llm_instance.ainvoke = AsyncMock(return_value=MagicMock(
                content="UPDATE users SET active=1; COMMIT;",
                tool_calls=[{"name": "execute_sql", "args": {"query": "UPDATE users SET active=1"}}]
            ))
            mock_get_llm.return_value = mock_llm_instance

            await run_react_agent(
                question="Update users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=3
            )

            # Agent should handle rollback
            assert len(operations) > 0, "Should have attempted operations"


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_recovers_from_intermittent_connection_issues(mock_llm_config, mock_db_config):
    """Agent recovers from intermittent connection issues"""

    execution_attempts = {"count": 0}

    async def mock_execute_intermittent(*args, **kwargs):
        execution_attempts["count"] += 1

        # Fail on attempts 1, 3, 5 (intermittent failures)
        if execution_attempts["count"] % 2 == 1 and execution_attempts["count"] < 6:
            raise ConnectionError("Intermittent connection issue")
        else:
            return {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_intermittent

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            call_count = {"count": 0}

            async def mock_llm(*args, **kwargs):
                call_count["count"] += 1
                return MagicMock(
                    content="SELECT * FROM users",
                    tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM users"}}]
                )

            mock_llm_instance = AsyncMock()
            mock_llm_instance.ainvoke = mock_llm
            mock_get_llm.return_value = mock_llm_instance

            await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=8
            )

            # Agent should eventually succeed after retries
            assert execution_attempts["count"] >= 2, "Should retry on intermittent failures"


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_database_maintenance_mode(mock_llm_config, mock_db_config):
    """Agent handles database in maintenance mode"""

    async def mock_execute_maintenance(*args, **kwargs):
        raise Exception("Database is undergoing maintenance. Please try again later.")

    with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
        mock_execute.side_effect = mock_execute_maintenance

        with patch("app.services.react_agent.get_llm") as mock_get_llm:
            mock_llm_instance = AsyncMock()
            mock_llm_instance.ainvoke = AsyncMock(return_value=MagicMock(
                content="SELECT * FROM users",
                tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT * FROM users"}}]
            ))
            mock_get_llm.return_value = mock_llm_instance

            result = await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session",
                max_iterations=3
            )

            # Agent should fail gracefully with clear error
            assert result["status"] in ["error", "complete"]
            if result["status"] == "error":
                assert "maintenance" in result.get("error", "").lower() or \
                       "try again" in result.get("error", "").lower()
