"""
Resilience Test Utilities

Provides helper functions and mocks for testing agent resilience features:
- Circuit breaker state transitions
- Error simulation (permanent, transient)
- Timeout mocking
- Database/LLM failure injection
"""

import asyncio
from typing import Callable, Any, Dict, List


class CircuitBreakerState:
    """Track circuit breaker state for testing"""

    def __init__(self):
        self.permanent_errors = []
        self.transient_errors = []
        self.consecutive_failures = 0
        self.iterations_without_execution = 0
        self.sql_executions = 0

    def add_permanent_error(self, error_type: str):
        """Add a permanent error"""
        self.permanent_errors.append(error_type)
        self.consecutive_failures += 1

    def add_transient_error(self, error_type: str):
        """Add a transient error"""
        self.transient_errors.append(error_type)
        self.consecutive_failures += 1

    def add_exploration_iteration(self):
        """Add an iteration without SQL execution"""
        self.iterations_without_execution += 1

    def add_sql_execution(self):
        """Record SQL execution (resets exploration counter)"""
        self.sql_executions += 1
        self.iterations_without_execution = 0
        self.consecutive_failures = 0

    def should_stop(self) -> bool:
        """Determine if circuit breaker should stop execution"""
        # Check permanent errors (threshold: 3)
        if len(self.permanent_errors) >= 3:
            return True

        # Check consecutive failures (threshold: 5)
        if self.consecutive_failures >= 5:
            return True

        # Check exploration loop (threshold: 7)
        if self.iterations_without_execution >= 7:
            return True

        return False


class ErrorSimulator:
    """Simulate various error conditions for resilience testing"""

    @staticmethod
    def permanent_error(error_type: str = "COLUMN_NOT_FOUND") -> Dict[str, Any]:
        """Create a permanent error response"""
        error_messages = {
            "COLUMN_NOT_FOUND": "Column 'invalid_col' does not exist in table",
            "TABLE_NOT_FOUND": "Table 'invalid_table' does not exist",
            "SYNTAX_ERROR": "Syntax error near 'SELCT'",
            "PERMISSION_ERROR": "Permission denied for table users",
            "NOSQL_KEY_ERROR": "Missing partition key in query"
        }

        return {
            "success": False,
            "error": error_messages.get(error_type, "Unknown error"),
            "error_type": error_type,
            "failure_class": "permanent",
            "is_retryable": True,
            "recovery_hint": f"Fix {error_type} and retry"
        }

    @staticmethod
    def transient_error(error_type: str = "TIMEOUT_ERROR") -> Dict[str, Any]:
        """Create a transient error response"""
        error_messages = {
            "TIMEOUT_ERROR": "Query timeout after 30 seconds",
            "CONNECTION_ERROR": "Connection refused to database",
            "RATE_LIMIT": "Rate limit exceeded, try again later",
            "NO_DATA": "Query executed successfully but returned no results"
        }

        return {
            "success": False,
            "error": error_messages.get(error_type, "Unknown error"),
            "error_type": error_type,
            "failure_class": "transient",
            "is_retryable": True,
            "recovery_hint": f"Retry {error_type}"
        }

    @staticmethod
    def memory_error(size_mb: float = 127.5) -> Dict[str, Any]:
        """Create a memory guard error"""
        return {
            "success": False,
            "error": "Result set too large for in-depth analysis",
            "size_mb": size_mb,
            "recommendation": "Add WHERE clause to filter data"
        }

    @staticmethod
    def success_with_sampling(rows: int = 5000, sampled: int = 1000) -> Dict[str, Any]:
        """Create a success response with sampling disclaimer"""
        return {
            "success": True,
            "rows": [[i, f"data_{i}"] for i in range(rows)],
            "sampled_rows": sampled,
            "total_rows": rows,
            "insights": {
                "sampling_applied": True,
                "disclaimer": f"Analysis based on random sample of {sampled} rows (out of {rows} total)"
            }
        }


class DatabaseFailureSimulator:
    """Simulate database connection failures"""

    def __init__(self, fail_count: int = 3):
        self.fail_count = fail_count
        self.attempts = 0

    async def execute_with_failures(self, success_result: Any) -> Any:
        """Execute with failures, then success"""
        self.attempts += 1

        if self.attempts <= self.fail_count:
            raise ConnectionError("Database connection lost")

        return success_result

    def reset(self):
        """Reset failure counter"""
        self.attempts = 0


class LLMFailureSimulator:
    """Simulate LLM service failures"""

    def __init__(self, failure_type: str = "rate_limit"):
        self.failure_type = failure_type
        self.attempts = 0

    async def invoke_with_failure(self, *args, **kwargs):
        """Invoke LLM with simulated failures"""
        self.attempts += 1

        if self.failure_type == "rate_limit":
            raise Exception("Rate limit exceeded (429)")
        elif self.failure_type == "service_unavailable":
            raise Exception("Service unavailable (503)")
        elif self.failure_type == "timeout":
            await asyncio.sleep(100)  # Simulate timeout
        elif self.failure_type == "invalid_api_key":
            raise Exception("Invalid API key (401)")
        else:
            raise Exception("Unknown LLM error")


class TimeoutSimulator:
    """Simulate timeout conditions"""

    @staticmethod
    async def slow_operation(delay_seconds: float = 35.0):
        """Simulate a slow operation that should timeout"""
        await asyncio.sleep(delay_seconds)
        return {"success": True, "data": "Completed after timeout"}

    @staticmethod
    async def with_timeout(coro, timeout_seconds: float = 30.0):
        """Execute coroutine with timeout"""
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return ErrorSimulator.transient_error("TIMEOUT_ERROR")


def create_mock_tool_context(
    llm_config: Any,
    db_config: Any,
    fail_on_call: int = None,
    error_type: str = "COLUMN_NOT_FOUND"
) -> Dict[str, Any]:
    """
    Create a mock tool context for testing

    Args:
        llm_config: Mock LLM configuration
        db_config: Mock database configuration
        fail_on_call: If specified, fail on this call number (1-indexed)
        error_type: Type of error to simulate

    Returns:
        Mock tool context dictionary
    """
    call_count = {"count": 0}

    async def mock_execute(*args, **kwargs):
        call_count["count"] += 1

        if fail_on_call and call_count["count"] == fail_on_call:
            if error_type in ["COLUMN_NOT_FOUND", "TABLE_NOT_FOUND", "SYNTAX_ERROR"]:
                return ErrorSimulator.permanent_error(error_type)
            else:
                return ErrorSimulator.transient_error(error_type)

        return {
            "success": True,
            "rows": [[1, "test_data"]],
            "columns": ["id", "name"],
            "row_count": 1
        }

    return {
        "llm_config": llm_config,
        "db_config": db_config,
        "execute": mock_execute,
        "call_count": call_count
    }


def create_exploration_sequence(iterations: int) -> List[Dict[str, Any]]:
    """
    Create a sequence of exploration results (no SQL execution)

    Used to test exploration loop detection threshold (7 iterations)

    Args:
        iterations: Number of exploration iterations to create

    Returns:
        List of mock tool results
    """
    sequence = []

    for i in range(iterations):
        if i % 2 == 0:
            # search_tables call
            sequence.append({
                "tool": "search_tables",
                "success": True,
                "tables": [f"table_{i}"]
            })
        else:
            # get_table_schema call
            sequence.append({
                "tool": "get_table_schema",
                "success": True,
                "schema": {
                    "columns": [{"name": f"col_{i}", "type": "VARCHAR"}]
                }
            })

    return sequence


async def assert_eventually(
    condition: Callable[[], bool],
    timeout: float = 5.0,
    interval: float = 0.1,
    message: str = "Condition not met"
):
    """
    Assert that a condition becomes true within a timeout

    Useful for testing async operations with retries

    Args:
        condition: Function that returns True when condition is met
        timeout: Maximum time to wait (seconds)
        interval: Time between checks (seconds)
        message: Error message if condition not met
    """
    start = asyncio.get_event_loop().time()

    while (asyncio.get_event_loop().time() - start) < timeout:
        if condition():
            return
        await asyncio.sleep(interval)

    raise AssertionError(message)
