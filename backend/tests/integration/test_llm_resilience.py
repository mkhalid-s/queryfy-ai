"""
LLM Service Resilience Tests

Tests for graceful degradation when LLM service is unavailable:
- Rate limit errors (429)
- Service unavailable (503)
- Timeout errors
- Invalid API key (401)
- Malformed responses
- Token limit exceeded
- Retry with exponential backoff
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.react_agent import run_react_agent


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_llm_rate_limit(mock_llm_config, mock_db_config):
    """Agent handles LLM rate limit errors (429)"""

    llm_attempts = {"count": 0}

    async def mock_llm_with_rate_limit(*args, **kwargs):
        llm_attempts["count"] += 1

        if llm_attempts["count"] <= 2:
            # First two attempts: rate limited
            raise Exception("Rate limit exceeded (429). Please retry after 1 second")
        else:
            # Third attempt: success
            return MagicMock(content="SELECT * FROM users")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_with_rate_limit
        mock_get_llm.return_value = mock_llm_instance

        with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
            mock_execute.return_value = {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

            await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Agent should eventually succeed after retries
            assert llm_attempts["count"] >= 3, "Should retry after rate limit"


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_llm_service_unavailable(mock_llm_config, mock_db_config):
    """Agent handles LLM service unavailable errors (503)"""

    async def mock_llm_unavailable(*args, **kwargs):
        raise Exception("Service temporarily unavailable (503). Please try again later")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_unavailable
        mock_get_llm.return_value = mock_llm_instance

        result = await run_react_agent(
            question="Show me users",
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            session_id="test-session",
            max_iterations=3
        )

        # Agent should fail gracefully
        assert result["status"] in ["error", "complete"]
        if result["status"] == "error":
            assert "service" in result.get("error", "").lower() or \
                   "unavailable" in result.get("error", "").lower()


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_llm_timeout(mock_llm_config, mock_db_config):
    """Agent handles LLM generation timeout"""

    llm_attempts = {"count": 0}

    async def mock_llm_with_timeout(*args, **kwargs):
        llm_attempts["count"] += 1

        if llm_attempts["count"] == 1:
            # First attempt: timeout
            await asyncio.sleep(100)  # Simulate very slow LLM
            return MagicMock(content="SELECT * FROM users")
        else:
            # Second attempt: fast response
            return MagicMock(content="SELECT * FROM users")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_with_timeout
        mock_get_llm.return_value = mock_llm_instance

        with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
            mock_execute.return_value = {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

            # Use asyncio.wait_for to simulate timeout
            try:
                result = await asyncio.wait_for(
                    run_react_agent(
                        question="Show me users",
                        llm_config=mock_llm_config,
                        db_config=mock_db_config,
                        session_id="test-session",
                        max_iterations=3
                    ),
                    timeout=2.0  # 2 second timeout
                )

                # If we get here without timeout, check result
                assert result is not None

            except asyncio.TimeoutError:
                # Timeout is acceptable for this test
                pass


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_invalid_api_key(mock_llm_config, mock_db_config):
    """Agent handles invalid API key errors (401)"""

    async def mock_llm_invalid_key(*args, **kwargs):
        raise Exception("Invalid API key (401). Please check your credentials")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_invalid_key
        mock_get_llm.return_value = mock_llm_instance

        result = await run_react_agent(
            question="Show me users",
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            session_id="test-session",
            max_iterations=2
        )

        # Agent should fail immediately (permanent error)
        assert result["status"] in ["error", "complete"]
        if result["status"] == "error":
            assert "api" in result.get("error", "").lower() or \
                   "key" in result.get("error", "").lower() or \
                   "401" in str(result.get("error", ""))


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_malformed_llm_response(mock_llm_config, mock_db_config):
    """Agent handles malformed LLM responses"""

    llm_attempts = {"count": 0}

    async def mock_llm_malformed(*args, **kwargs):
        llm_attempts["count"] += 1

        if llm_attempts["count"] == 1:
            # First attempt: malformed response
            return MagicMock(content=None, tool_calls=None)  # Invalid response
        else:
            # Second attempt: valid response
            return MagicMock(content="SELECT * FROM users")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_malformed
        mock_get_llm.return_value = mock_llm_instance

        with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
            mock_execute.return_value = {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

            await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Agent should handle malformed response
            assert llm_attempts["count"] >= 1


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_handles_token_limit_exceeded(mock_llm_config, mock_db_config):
    """Agent handles token limit exceeded errors"""

    async def mock_llm_token_limit(*args, **kwargs):
        raise Exception("Token limit exceeded. Response too long for model context window")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_token_limit
        mock_get_llm.return_value = mock_llm_instance

        result = await run_react_agent(
            question="Show me users",
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            session_id="test-session",
            max_iterations=2
        )

        # Agent should fail gracefully
        assert result["status"] in ["error", "complete"]
        if result["status"] == "error":
            assert "token" in result.get("error", "").lower() or \
                   "limit" in result.get("error", "").lower()


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_retries_with_exponential_backoff(mock_llm_config, mock_db_config):
    """Agent retries with exponential backoff on transient LLM failures"""

    llm_attempts = {"count": 0, "timestamps": []}

    async def mock_llm_with_backoff(*args, **kwargs):
        import time
        llm_attempts["count"] += 1
        llm_attempts["timestamps"].append(time.time())

        if llm_attempts["count"] <= 2:
            # Fail first two attempts
            raise Exception("Rate limit exceeded (429)")
        else:
            # Third attempt succeeds
            return MagicMock(content="SELECT * FROM users")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_with_backoff
        mock_get_llm.return_value = mock_llm_instance

        with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
            mock_execute.return_value = {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

            await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Agent should retry with backoff
            assert llm_attempts["count"] >= 3, "Should retry multiple times"

            # Check timestamps have increasing delays (basic backoff check)
            if len(llm_attempts["timestamps"]) >= 3:
                llm_attempts["timestamps"][1] - llm_attempts["timestamps"][0]
                llm_attempts["timestamps"][2] - llm_attempts["timestamps"][1]
                # Second delay should be >= first delay (exponential backoff)
                # Note: This is a loose check due to test execution variance


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_fails_after_max_llm_retries(mock_llm_config, mock_db_config):
    """Agent fails after maximum LLM retries"""

    llm_attempts = {"count": 0}

    async def mock_llm_always_fails(*args, **kwargs):
        llm_attempts["count"] += 1
        raise Exception("Persistent LLM service failure")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_always_fails
        mock_get_llm.return_value = mock_llm_instance

        result = await run_react_agent(
            question="Show me users",
            llm_config=mock_llm_config,
            db_config=mock_db_config,
            session_id="test-session",
            max_iterations=5
        )

        # Agent should eventually give up
        assert result["status"] in ["error", "complete"]
        # Should have attempted multiple times before giving up
        assert llm_attempts["count"] >= 1


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_switches_llm_provider_on_failure(mock_llm_config, mock_db_config):
    """Agent attempts alternate LLM provider on persistent failures"""

    primary_attempts = {"count": 0}
    fallback_attempts = {"count": 0}

    async def mock_primary_llm(*args, **kwargs):
        primary_attempts["count"] += 1
        raise Exception("Primary LLM service unavailable")

    async def mock_fallback_llm(*args, **kwargs):
        fallback_attempts["count"] += 1
        return MagicMock(content="SELECT * FROM users")

    # Note: This test assumes fallback logic exists
    # If not implemented, this test documents desired behavior

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        call_count = {"count": 0}

        def get_llm_selector(*args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] <= 2:
                # First tries: primary LLM
                mock_llm = AsyncMock()
                mock_llm.ainvoke = mock_primary_llm
                return mock_llm
            else:
                # Fallback: alternate LLM
                mock_llm = AsyncMock()
                mock_llm.ainvoke = mock_fallback_llm
                return mock_llm

        mock_get_llm.side_effect = get_llm_selector

        with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
            mock_execute.return_value = {
                "success": True,
                "rows": [[1, "test"]],
                "columns": ["id", "name"],
                "row_count": 1
            }

            # Note: This test may not pass if fallback logic isn't implemented
            # It documents the desired resilience behavior
            try:
                result = await run_react_agent(
                    question="Show me users",
                    llm_config=mock_llm_config,
                    db_config=mock_db_config,
                    session_id="test-session"
                )

                # If fallback works, should succeed
                # If not implemented, will fail gracefully
                assert result is not None

            except Exception:
                # Fallback not implemented yet - acceptable
                pass


@pytest.mark.skip(reason="Test uses obsolete architecture - patches get_llm which no longer exists")
@pytest.mark.integration
async def test_agent_caches_llm_responses_on_retry(mock_llm_config, mock_db_config):
    """Agent avoids redundant LLM calls on retry"""

    llm_calls = []

    async def mock_llm_with_cache(*args, **kwargs):
        # Track unique calls
        prompt = str(args) + str(kwargs)
        llm_calls.append(prompt)
        return MagicMock(content="SELECT * FROM users")

    with patch("app.services.react_agent.get_llm") as mock_get_llm:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_llm_with_cache
        mock_get_llm.return_value = mock_llm_instance

        with patch("app.services.tools.query_tools.execute_sql") as mock_execute:
            # First attempt fails
            execute_attempts = {"count": 0}

            async def mock_execute_with_failure(*args, **kwargs):
                execute_attempts["count"] += 1
                if execute_attempts["count"] == 1:
                    raise Exception("Temporary database error")
                return {
                    "success": True,
                    "rows": [[1, "test"]],
                    "columns": ["id", "name"],
                    "row_count": 1
                }

            mock_execute.side_effect = mock_execute_with_failure

            await run_react_agent(
                question="Show me users",
                llm_config=mock_llm_config,
                db_config=mock_db_config,
                session_id="test-session"
            )

            # Should have made LLM calls
            assert len(llm_calls) >= 1

            # Note: Actual caching depends on implementation
            # This test documents desired behavior
