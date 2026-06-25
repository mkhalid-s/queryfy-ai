"""
Comprehensive tests for circuit breaker logic.
"""
from app.services.react_agent import should_continue


class TestPermanentErrorThreshold:
    """Test permanent error circuit breaker (3 errors or 2 identical)"""

    def test_three_different_permanent_errors_triggers(self):
        """3 different permanent errors should trigger circuit breaker"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
                {"error_info": {"failure_class": "permanent", "error_type": "TABLE_NOT_FOUND"}},
                {"error_info": {"failure_class": "permanent", "error_type": "SYNTAX_ERROR"}},
            ],
            "consecutive_failures": 3,
            "iterations_without_execution": 0,
            "iteration": 5,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "end"

    def test_three_identical_permanent_errors_triggers(self):
        """3 identical permanent errors should trigger circuit breaker (true loop)"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
            ],
            "consecutive_failures": 3,
            "iterations_without_execution": 0,
            "iteration": 4,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "end"

    def test_two_different_permanent_errors_continues(self):
        """2 different permanent errors should continue (allows multi-step correction)"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
                {"error_info": {"failure_class": "permanent", "error_type": "TABLE_NOT_FOUND"}},
            ],
            "consecutive_failures": 2,
            "iterations_without_execution": 0,
            "iteration": 3,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "agent"

    def test_permanent_and_transient_mixed(self):
        """Mixed errors should only count permanent ones"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
                {"error_info": {"failure_class": "transient", "error_type": "TIMEOUT_ERROR"}},
                {"error_info": {"failure_class": "permanent", "error_type": "TABLE_NOT_FOUND"}},
                {"error_info": {"failure_class": "transient", "error_type": "TIMEOUT_ERROR"}},
                {"error_info": {"failure_class": "permanent", "error_type": "SYNTAX_ERROR"}},
            ],
            "consecutive_failures": 5,
            "iterations_without_execution": 0,
            "iteration": 6,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        # Should trigger (3 permanent errors in last 5 attempts)
        assert should_continue(state) == "end"


class TestConsecutiveFailuresThreshold:
    """Test consecutive failures circuit breaker (5 failures)"""

    def test_five_consecutive_failures_triggers(self):
        """5 consecutive failures should trigger circuit breaker"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "transient", "error_type": "TIMEOUT_ERROR"}},
            ] * 5,
            "consecutive_failures": 5,
            "iterations_without_execution": 0,
            "iteration": 6,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "end"

    def test_four_consecutive_failures_continues(self):
        """4 consecutive failures should continue"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "transient", "error_type": "TIMEOUT_ERROR"}},
            ] * 4,
            "consecutive_failures": 4,
            "iterations_without_execution": 0,
            "iteration": 5,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "agent"


class TestExplorationLoopThreshold:
    """Test exploration loop circuit breaker (10 iterations, Phase 2 Day 1)"""

    def test_ten_iterations_without_execution_triggers(self):
        """10 iterations without SQL execution should trigger circuit breaker"""
        state = {
            "failed_attempts": [],
            "consecutive_failures": 0,
            "iterations_without_execution": 10,
            "iteration": 11,
            "max_iterations": 15,
            "status": "thinking",
            "messages": [],
            "question": "Test query",
            "tools_used": ["search_tables", "get_table_schema"]
        }

        assert should_continue(state) == "end"

    def test_nine_iterations_without_execution_continues(self):
        """9 iterations without execution should continue (allows complex JOINs)"""
        state = {
            "failed_attempts": [],
            "consecutive_failures": 0,
            "iterations_without_execution": 9,
            "iteration": 10,
            "max_iterations": 15,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "agent"


class TestCircuitBreakerPriority:
    """Test that multiple circuit breakers work correctly together"""

    def test_permanent_errors_checked_first(self):
        """Permanent errors should be checked before other conditions"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
            ],
            "consecutive_failures": 2,
            "iterations_without_execution": 10,  # Also triggers exploration loop (Phase 2 threshold)
            "iteration": 3,
            "max_iterations": 15,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        # Should trigger on permanent errors (checked first)
        assert should_continue(state) == "end"

    def test_max_iterations_checked_early(self):
        """Max iterations should be checked before circuit breakers"""
        state = {
            "failed_attempts": [],
            "consecutive_failures": 0,
            "iterations_without_execution": 0,
            "iteration": 10,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "end"


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_empty_failed_attempts(self):
        """Should handle empty failed attempts list"""
        state = {
            "failed_attempts": [],
            "consecutive_failures": 0,
            "iterations_without_execution": 0,
            "iteration": 1,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "agent"

    def test_missing_error_info(self):
        """Should handle failed attempts without error_info"""
        state = {
            "failed_attempts": [
                {"tool": "execute_sql", "error": "some error"},  # No error_info
            ] * 3,
            "consecutive_failures": 3,
            "iterations_without_execution": 0,
            "iteration": 4,
            "max_iterations": 10,
            "status": "thinking",
            "messages": [],
            "question": "Test query"
        }

        # Should not crash, should continue (no permanent errors counted)
        assert should_continue(state) == "agent"

    def test_status_complete_overrides_circuit_breaker(self):
        """Status complete should end even with failures"""
        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
            ] * 5,
            "consecutive_failures": 5,
            "iterations_without_execution": 0,
            "iteration": 6,
            "max_iterations": 10,
            "status": "complete",  # Overrides circuit breaker
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "end"

    def test_status_error_overrides_circuit_breaker(self):
        """Status error should end immediately"""
        state = {
            "failed_attempts": [],
            "consecutive_failures": 0,
            "iterations_without_execution": 0,
            "iteration": 1,
            "max_iterations": 10,
            "status": "error",
            "messages": [],
            "question": "Test query"
        }

        assert should_continue(state) == "end"
