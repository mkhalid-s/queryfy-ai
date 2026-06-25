"""
Circuit Breaker Tests

Tests for agent circuit breaker functionality:
- Permanent error threshold (3 errors)
- Same error repeated (2x stops immediately)
- Transient error threshold (5 consecutive failures)
- Exploration loop threshold (7 iterations without SQL execution)
- State transitions and counter management
"""

from app.services.react_agent import should_continue, ReActState
from langchain_core.messages import AIMessage, HumanMessage


# =============================================================================
# Permanent Error Tests
# =============================================================================

def test_circuit_breaker_stops_after_3_permanent_errors():
    """Circuit breaker stops after 3 permanent errors"""
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 5,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "COLUMN_NOT_FOUND",
                    "failure_class": "permanent"
                }
            },
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "TABLE_NOT_FOUND",
                    "failure_class": "permanent"
                }
            },
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "SYNTAX_ERROR",
                    "failure_class": "permanent"
                }
            }
        ],
        "consecutive_failures": 3,
        "iterations_without_execution": 3
    }

    result = should_continue(state)
    assert result == "end", "Circuit breaker should stop after 3 permanent errors"


def test_circuit_breaker_allows_2_permanent_errors():
    """Circuit breaker allows 2 permanent errors (legitimate corrections)"""
    state: ReActState = {
        "messages": [AIMessage(content="Let me retry", tool_calls=[{"name": "execute_sql", "id": "call_1", "args": {}}])],
        "iteration": 3,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "COLUMN_NOT_FOUND",
                    "failure_class": "permanent"
                }
            },
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "TABLE_NOT_FOUND",
                    "failure_class": "permanent"
                }
            }
        ],
        "consecutive_failures": 2,
        "iterations_without_execution": 2
    }

    result = should_continue(state)
    assert result == "tools", "Circuit breaker should allow 2 permanent errors for corrections"


def test_circuit_breaker_stops_on_repeated_same_error():
    """Circuit breaker stops when same error repeated 3 times (true loop detection)"""
    # The circuit breaker requires permanent_count >= 3 before checking for repeated errors
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 4,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "COLUMN_NOT_FOUND",
                    "failure_class": "permanent"
                }
            },
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "COLUMN_NOT_FOUND",
                    "failure_class": "permanent"
                }
            },
            {
                "tool": "execute_sql",
                "error_info": {
                    "error_type": "COLUMN_NOT_FOUND",
                    "failure_class": "permanent"
                }
            }
        ],
        "consecutive_failures": 3,
        "iterations_without_execution": 3
    }

    result = should_continue(state)
    assert result == "end", "Circuit breaker should stop when same permanent error repeated 3 times"


def test_circuit_breaker_counts_recent_5_failures_only():
    """Circuit breaker only considers last 5 failures for permanent error threshold"""
    # 10 total failures, but only 2 permanent in last 5 (below the 3 threshold)
    # Note: consecutive_failures must be < 5 to avoid that circuit breaker
    # Note: iterations_without_execution must be < 7 to avoid exploration loop check
    state: ReActState = {
        "messages": [AIMessage(content="Let me retry", tool_calls=[{"name": "execute_sql", "id": "call_1", "args": {}}])],
        "iteration": 8,
        "max_iterations": 15,
        "status": "thinking",
        "failed_attempts": [
            # Old permanent errors (outside window - these 5 will be ignored)
            {"tool": "execute_sql", "error_info": {"error_type": "COLUMN_NOT_FOUND", "failure_class": "permanent"}},
            {"tool": "execute_sql", "error_info": {"error_type": "TABLE_NOT_FOUND", "failure_class": "permanent"}},
            {"tool": "execute_sql", "error_info": {"error_type": "SYNTAX_ERROR", "failure_class": "permanent"}},
            {"tool": "execute_sql", "error_info": {"error_type": "PERMISSION_ERROR", "failure_class": "permanent"}},
            {"tool": "execute_sql", "error_info": {"error_type": "COLUMN_NOT_FOUND", "failure_class": "permanent"}},
            # Recent failures (last 5) - only 2 permanent, 3 transient
            {"tool": "search_tables", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "COLUMN_NOT_FOUND", "failure_class": "permanent"}},
            {"tool": "search_tables", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "TABLE_NOT_FOUND", "failure_class": "permanent"}},
            {"tool": "search_tables", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
        ],
        "consecutive_failures": 3,  # Below 5 threshold
        "iterations_without_execution": 5  # Below 7 threshold
    }

    result = should_continue(state)
    # Should continue because only 2 permanent in recent window (below 3 threshold)
    assert result == "tools", "Circuit breaker should only count last 5 failures for permanent threshold"


# =============================================================================
# Transient Error / Consecutive Failure Tests
# =============================================================================

def test_circuit_breaker_stops_after_5_consecutive_failures():
    """Circuit breaker stops after 5 consecutive failures"""
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 6,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "CONNECTION_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "RATE_LIMIT", "failure_class": "transient"}},
        ],
        "consecutive_failures": 5,
        "iterations_without_execution": 5
    }

    result = should_continue(state)
    assert result == "end", "Circuit breaker should stop after 5 consecutive failures"


def test_circuit_breaker_allows_4_consecutive_failures():
    """Circuit breaker allows 4 consecutive failures"""
    state: ReActState = {
        "messages": [AIMessage(content="Let me retry", tool_calls=[{"name": "execute_sql", "id": "call_1", "args": {}}])],
        "iteration": 5,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "CONNECTION_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
        ],
        "consecutive_failures": 4,
        "iterations_without_execution": 4
    }

    result = should_continue(state)
    assert result == "tools", "Circuit breaker should allow 4 consecutive failures"


def test_consecutive_failures_resets_on_success():
    """Consecutive failures counter resets when operation succeeds"""
    # Simulate state after successful execution
    state: ReActState = {
        "messages": [AIMessage(content="Let me retry", tool_calls=[{"name": "execute_sql", "id": "call_1", "args": {}}])],
        "iteration": 6,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            {"tool": "execute_sql", "error_info": {"error_type": "TIMEOUT_ERROR", "failure_class": "transient"}},
            # Success happened, counter reset
        ],
        "consecutive_failures": 0,  # Reset to 0
        "iterations_without_execution": 0  # Reset to 0
    }

    result = should_continue(state)
    assert result == "tools", "Circuit breaker should allow retries after success resets counters"


# =============================================================================
# Exploration Loop Tests
# =============================================================================

def test_circuit_breaker_stops_after_10_iterations_without_execution():
    """Circuit breaker stops after 10 iterations without SQL execution (Phase 2 Day 1)"""
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 11,
        "max_iterations": 15,
        "status": "thinking",
        "failed_attempts": [],  # Empty - exploration iterations are successful, not failures
        "consecutive_failures": 0,
        "iterations_without_execution": 10  # This counter tracks exploration
    }

    result = should_continue(state)
    assert result == "end", "Circuit breaker should stop after 10 iterations without SQL execution"


def test_circuit_breaker_allows_9_exploration_iterations():
    """Circuit breaker allows 9 exploration iterations (complex multi-table JOIN discovery, Phase 2 Day 1)"""
    state: ReActState = {
        "messages": [AIMessage(content="Let me check one more table", tool_calls=[{"name": "search_tables", "id": "call_1", "args": {}}])],
        "iteration": 10,
        "max_iterations": 15,
        "status": "thinking",
        "failed_attempts": [],  # Empty - exploration iterations are successful, not failures
        "consecutive_failures": 0,
        "iterations_without_execution": 9  # Just below Phase 2 threshold of 10
    }

    result = should_continue(state)
    assert result == "tools", "Circuit breaker should allow 9 exploration iterations for complex JOINs"


def test_exploration_counter_resets_on_sql_execution():
    """Exploration counter resets when SQL is executed"""
    state: ReActState = {
        "messages": [AIMessage(content="Let me search", tool_calls=[{"name": "search_tables", "id": "call_1", "args": {}}])],
        "iteration": 8,
        "max_iterations": 15,
        "status": "thinking",
        "failed_attempts": [],  # Empty - SQL execution was successful
        "consecutive_failures": 0,
        "iterations_without_execution": 0  # Reset after SQL execution
    }

    result = should_continue(state)
    assert result == "tools", "Exploration counter should reset after SQL execution"


# =============================================================================
# Status-Based Termination Tests
# =============================================================================

def test_should_continue_stops_on_error_status():
    """should_continue returns 'end' when status is 'error'"""
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 2,
        "max_iterations": 10,
        "status": "error",  # Error status
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0
    }

    result = should_continue(state)
    assert result == "end", "should_continue should return 'end' when status is 'error'"


def test_should_continue_stops_on_complete_status():
    """should_continue returns 'end' when status is 'complete'"""
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 3,
        "max_iterations": 10,
        "status": "complete",  # Complete status
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0
    }

    result = should_continue(state)
    assert result == "end", "should_continue should return 'end' when status is 'complete'"


def test_should_continue_stops_at_max_iterations():
    """should_continue returns 'end' when max_iterations reached"""
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 10,  # Max reached
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0
    }

    result = should_continue(state)
    assert result == "end", "should_continue should return 'end' when max_iterations reached"


def test_should_continue_stops_with_sql_and_execution_result():
    """should_continue returns 'end' when SQL and execution_result exist"""
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 3,
        "max_iterations": 10,
        "status": "complete",
        "sql": "SELECT * FROM users",
        "execution_result": {"rows": [[1, "test"]], "columns": ["id", "name"]},
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0
    }

    result = should_continue(state)
    assert result == "end", "should_continue should return 'end' when both SQL and execution_result exist"


# =============================================================================
# Integration Scenarios
# =============================================================================

def test_multi_step_correction_succeeds():
    """Multi-step correction succeeds with 2 permanent errors (wrong column → wrong table → success)"""
    # Step 1: Wrong column error
    state: ReActState = {
        "messages": [AIMessage(content="Let me fix", tool_calls=[{"name": "execute_sql", "id": "call_1", "args": {}}])],
        "iteration": 3,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {"tool": "execute_sql", "error_info": {"error_type": "COLUMN_NOT_FOUND", "failure_class": "permanent"}},
        ],
        "consecutive_failures": 1,
        "iterations_without_execution": 1
    }

    result = should_continue(state)
    assert result == "tools", "Should allow first correction"

    # Step 2: Wrong table error
    state["failed_attempts"].append(
        {"tool": "execute_sql", "error_info": {"error_type": "TABLE_NOT_FOUND", "failure_class": "permanent"}}
    )
    state["consecutive_failures"] = 2
    state["iterations_without_execution"] = 2
    state["iteration"] = 4

    result = should_continue(state)
    assert result == "tools", "Should allow second correction"

    # Step 3: Success (would reset counters in actual execution)
    # Update message to one without tool_calls (agent finished, no more tools to call)
    state["messages"] = [AIMessage(content="Query executed successfully")]
    state["consecutive_failures"] = 0
    state["iterations_without_execution"] = 0
    state["sql"] = "SELECT * FROM correct_table"
    state["execution_result"] = {"rows": [[1]], "columns": ["id"]}
    state["iteration"] = 5

    result = should_continue(state)
    assert result == "end", "Should complete successfully after corrections"


def test_true_loop_detection():
    """True loop (same error repeated 3 times) triggers circuit breaker"""
    # Circuit breaker requires permanent_count >= 3 before checking for repeated errors
    state: ReActState = {
        "messages": [HumanMessage(content="test")],
        "iteration": 4,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [
            {"tool": "execute_sql", "error_info": {"error_type": "COLUMN_NOT_FOUND", "failure_class": "permanent"}},
            {"tool": "execute_sql", "error_info": {"error_type": "COLUMN_NOT_FOUND", "failure_class": "permanent"}},
            {"tool": "execute_sql", "error_info": {"error_type": "COLUMN_NOT_FOUND", "failure_class": "permanent"}},
        ],
        "consecutive_failures": 3,
        "iterations_without_execution": 3
    }

    result = should_continue(state)
    assert result == "end", "True loop should stop at 3 same permanent errors"


def test_complex_3_table_join_discovery():
    """Complex 3-table JOIN discovery succeeds with 6 exploration iterations"""
    # Simulates: search(customers) → schema(customers) → search(orders) → schema(orders) → search(products) → schema(products) → execute_sql
    state: ReActState = {
        "messages": [AIMessage(content="Now I'll execute", tool_calls=[{"name": "execute_and_analyze", "id": "call_1", "args": {}}])],
        "iteration": 7,
        "max_iterations": 15,
        "status": "thinking",
        "failed_attempts": [],  # Empty - all exploration tool calls were successful
        "consecutive_failures": 0,
        "iterations_without_execution": 6  # This counter tracks 6 successful exploration iterations
    }

    result = should_continue(state)
    assert result == "tools", "Should allow complex 3-table JOIN discovery at 6 iterations"

    # Simulate SQL execution success
    # Update message to one without tool_calls (agent finished)
    state["messages"] = [AIMessage(content="Query executed successfully")]
    state["iterations_without_execution"] = 0  # Reset after SQL execution
    state["consecutive_failures"] = 0
    state["sql"] = "SELECT * FROM customers c JOIN orders o ON c.id = o.customer_id JOIN products p ON o.product_id = p.id"
    state["execution_result"] = {"rows": [[1, "test", 100]], "columns": ["id", "name", "total"]}
    state["iteration"] = 8

    result = should_continue(state)
    assert result == "end", "Should complete successfully after JOIN discovery"


# =============================================================================
# consecutive_no_tools router safety net
# =============================================================================


def test_router_ends_on_two_consecutive_no_tool_responses():
    """Router fails fast when consecutive_no_tools >= 2."""
    state: ReActState = {
        "messages": [AIMessage(content="I don't know what to do next")],
        "iteration": 4,
        "max_iterations": 10,
        "status": "thinking",  # NOT "complete" — status hasn't propagated
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0,
        "consecutive_no_tools": 2,
    }
    assert should_continue(state) == "end"


def test_router_continues_on_one_no_tool_response():
    """consecutive_no_tools < 2 doesn't trip the safety net."""
    state: ReActState = {
        "messages": [AIMessage(content="Let me think about this")],
        "iteration": 3,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0,
        "consecutive_no_tools": 1,
    }
    # No tool_calls on the message + no sql/execution_result → fallthrough
    # to "agent" — the router lets the next iteration happen.
    assert should_continue(state) == "agent"


# =============================================================================
# _CRITICAL_STATE_FIELDS drift guard
# =============================================================================


def test_critical_state_fields_all_exist_on_state_schema():
    """
    The _CRITICAL_STATE_FIELDS tuple is manually maintained. If a
    future change renames a state field without updating the tuple,
    _build_complete_state_update() will silently carry stale values
    across early-return paths and confuse the router. This test
    locks the invariant so drift fails fast in CI.
    """
    from app.services.react_agent import ReActAgentNodes, ReActState

    state_fields = set(ReActState.__annotations__.keys())
    tuple_fields = set(ReActAgentNodes._CRITICAL_STATE_FIELDS)

    missing = tuple_fields - state_fields
    assert not missing, (
        f"_CRITICAL_STATE_FIELDS lists fields that no longer exist on "
        f"ReActState: {sorted(missing)}. Either rename the field on "
        f"ReActState or drop it from _CRITICAL_STATE_FIELDS."
    )


# =============================================================================
# Wall-clock soft budget on agent runs
# =============================================================================


def test_router_ends_when_wall_clock_budget_exceeded():
    """Slow runs hit the budget and stop; agent doesn't loop for ~50 min."""
    import time

    from app.services.react_agent import ReActState

    # Simulate a run that started 700 s ago against a 600 s budget.
    state: ReActState = {
        "messages": [HumanMessage(content="slow query")],
        "iteration": 4,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0,
        "consecutive_no_tools": 0,
        "wall_clock_start": time.monotonic() - 700.0,
        "wall_clock_budget_seconds": 600.0,
    }
    assert should_continue(state) == "end"


def test_router_continues_when_within_wall_clock_budget():
    """Fast runs are unaffected by the budget."""
    import time

    from app.services.react_agent import ReActState

    state: ReActState = {
        "messages": [AIMessage(content="thinking")],
        "iteration": 2,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0,
        "consecutive_no_tools": 0,
        # Started 30 s ago, generous budget
        "wall_clock_start": time.monotonic() - 30.0,
        "wall_clock_budget_seconds": 600.0,
    }
    # Falls through to "agent" — neither tool_calls nor sql+result yet
    assert should_continue(state) == "agent"


def test_router_skips_check_when_budget_zero():
    """Setting budget=0 disables the check (operator escape hatch)."""
    import time

    from app.services.react_agent import ReActState

    state: ReActState = {
        "messages": [AIMessage(content="thinking")],
        "iteration": 2,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0,
        "consecutive_no_tools": 0,
        # Pretend we've been running 1 hour, budget disabled
        "wall_clock_start": time.monotonic() - 3600.0,
        "wall_clock_budget_seconds": 0.0,
    }
    # Wall-clock check is skipped; falls through to "agent"
    assert should_continue(state) == "agent"


def test_router_skips_check_when_state_missing_wall_clock_fields():
    """
    Backward-compat: pre-Wave-2A states (e.g., resumed checkpoints
    from before this commit) won't have wall_clock_start /
    wall_clock_budget_seconds in the state dict. Router must handle
    that without raising — the check just silently no-ops.
    """
    state: ReActState = {  # type: ignore[typeddict-item]
        "messages": [AIMessage(content="thinking")],
        "iteration": 2,
        "max_iterations": 10,
        "status": "thinking",
        "failed_attempts": [],
        "consecutive_failures": 0,
        "iterations_without_execution": 0,
        "consecutive_no_tools": 0,
        # No wall_clock_start, no wall_clock_budget_seconds
    }
    # Must not raise.
    assert should_continue(state) == "agent"

