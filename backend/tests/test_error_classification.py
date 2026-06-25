"""
Tests for error classification accuracy.
"""
from app.services.react_agent import classify_error


class TestErrorClassification:
    """Test all 12 error types are correctly classified"""

    def test_foreign_key_violation(self):
        """Foreign key violations should be permanent and not retryable"""
        errors = [
            "ERROR: insert or update on table violates foreign key constraint",
            "foreign key constraint violation",
            "referential integrity constraint violated",
        ]
        for error in errors:
            result = classify_error(error, "execute_sql")
            assert result["error_type"] == "FOREIGN_KEY_VIOLATION", f"Failed for: {error}"
            assert result["failure_class"] == "permanent", f"Failed for: {error}"
            assert not result["is_retryable"], f"Failed for: {error}"
            assert "referential integrity" in result["recovery_hint"].lower(), f"Failed for: {error}"

    def test_data_type_mismatch(self):
        """Type mismatches should be permanent and retryable"""
        errors = [
            "ERROR: operator does not exist: integer = character varying",
            "type mismatch in comparison",
            "cannot cast integer to timestamp",
            "invalid input syntax for type integer",
        ]
        for error in errors:
            result = classify_error(error, "execute_sql")
            assert result["error_type"] == "DATA_TYPE_MISMATCH", f"Failed for: {error}"
            assert result["failure_class"] == "permanent", f"Failed for: {error}"
            assert result["is_retryable"], f"Failed for: {error}"
            assert "cast" in result["recovery_hint"].lower() or "type" in result["recovery_hint"].lower(), f"Failed for: {error}"

    def test_duplicate_key(self):
        """Duplicate key violations should be permanent and not retryable"""
        errors = [
            "ERROR: duplicate key value violates unique constraint",
            "duplicate entry for key 'PRIMARY'",
            "uniqueness violation on column user_id",
            "record already exists",
        ]
        for error in errors:
            result = classify_error(error, "execute_sql")
            assert result["error_type"] == "DUPLICATE_KEY", f"Failed for: {error}"
            assert result["failure_class"] == "permanent", f"Failed for: {error}"
            assert not result["is_retryable"], f"Failed for: {error}"
            assert "already exists" in result["recovery_hint"].lower() or "unique" in result["recovery_hint"].lower(), f"Failed for: {error}"

    def test_infrastructure_error(self):
        """Infrastructure errors should be transient and not retryable"""
        errors = [
            "ERROR: could not write to file: No space left on device",
            "out of memory for query execution",
            "insufficient resources to complete operation",
            "disk full",
            "memory exhausted",
        ]
        for error in errors:
            result = classify_error(error, "execute_sql")
            assert result["error_type"] == "INFRASTRUCTURE_ERROR", f"Failed for: {error}"
            assert result["failure_class"] == "transient", f"Failed for: {error}"
            assert not result["is_retryable"], f"Failed for: {error}"
            assert "infrastructure" in result["recovery_hint"].lower(), f"Failed for: {error}"

    def test_existing_error_types_unchanged(self):
        """Ensure existing error types still work correctly"""
        test_cases = [
            ("column 'user_name' does not exist", "COLUMN_NOT_FOUND", "permanent", True),
            ("table 'users' does not exist", "TABLE_NOT_FOUND", "permanent", True),
            ("syntax error near 'FROM'", "SYNTAX_ERROR", "permanent", True),
            ("permission denied for table users", "PERMISSION_ERROR", "permanent", False),
            ("query timeout after 30s", "TIMEOUT_ERROR", "transient", True),
            ("connection refused", "TIMEOUT_ERROR", "transient", True),
            ("no data found", "NO_DATA", "transient", True),
            ("partition key required", "NOSQL_KEY_ERROR", "permanent", True),
        ]

        for error, expected_type, expected_class, expected_retryable in test_cases:
            result = classify_error(error, "execute_sql")
            assert result["error_type"] == expected_type, f"Failed for: {error}"
            assert result["failure_class"] == expected_class, f"Failed for: {error}"
            assert result["is_retryable"] == expected_retryable, f"Failed for: {error}"

    def test_error_type_priority(self):
        """Test that error detection has correct priority"""
        # Column error should be detected before table error
        result = classify_error("column 'id' does not exist in table 'users'", "execute_sql")
        assert result["error_type"] == "COLUMN_NOT_FOUND"

        # Permission error should be detected first
        result = classify_error("permission denied for table users", "execute_sql")
        assert result["error_type"] == "PERMISSION_ERROR"

        # Foreign key should be detected (not generic constraint)
        result = classify_error("foreign key constraint violation on table orders", "execute_sql")
        assert result["error_type"] == "FOREIGN_KEY_VIOLATION"


class TestCircuitBreakerWithNewErrors:
    """Test circuit breaker behavior with new error types"""

    def test_foreign_key_counts_as_permanent(self):
        """Foreign key violations should count toward permanent error limit"""
        from app.services.react_agent import should_continue

        state = {
            "failed_attempts": [
                {"error_info": {"failure_class": "permanent", "error_type": "COLUMN_NOT_FOUND"}},
                {"error_info": {"failure_class": "permanent", "error_type": "FOREIGN_KEY_VIOLATION"}},
                {"error_info": {"failure_class": "permanent", "error_type": "DUPLICATE_KEY"}},
            ],
            "consecutive_failures": 3,
            "iterations_without_execution": 0,
            "iteration": 5,
            "max_iterations": 10,
            "status": "thinking",
            "messages": []
        }

        # Should trigger circuit breaker (3 permanent errors)
        assert should_continue(state) == "end"

    def test_infrastructure_error_not_retried(self):
        """Infrastructure errors should not be retried (is_retryable=False)"""
        result = classify_error("disk full", "execute_sql")
        assert not result["is_retryable"]
        assert "infrastructure" in result["recovery_hint"].lower()

    def test_data_type_mismatch_allows_retry(self):
        """Data type mismatches should allow retry with correction"""
        result = classify_error("operator does not exist: integer = text", "execute_sql")
        assert result["is_retryable"]
        assert result["failure_class"] == "permanent"


class TestRecoveryHints:
    """Test that recovery hints are helpful and specific"""

    def test_foreign_key_hint_mentions_relationships(self):
        """Foreign key hints should mention table relationships"""
        result = classify_error("foreign key constraint violation", "execute_sql")
        hint = result["recovery_hint"].lower()
        assert "relationship" in hint or "referential" in hint
        assert "get_table_schema" in hint

    def test_data_type_hint_mentions_casting(self):
        """Data type mismatch hints should mention casting"""
        result = classify_error("operator does not exist: integer = varchar", "execute_sql")
        hint = result["recovery_hint"].lower()
        assert "cast" in hint or "type" in hint

    def test_duplicate_key_hint_explains_not_error(self):
        """Duplicate key hints should explain it's not a query error"""
        result = classify_error("duplicate key violates unique constraint", "execute_sql")
        hint = result["recovery_hint"]
        assert "NOT a query error" in hint or "already exists" in hint.lower()

    def test_infrastructure_hint_says_not_query_problem(self):
        """Infrastructure hints should clarify it's not the query"""
        result = classify_error("out of memory", "execute_sql")
        hint = result["recovery_hint"]
        assert "NOT a query problem" in hint or "not caused by their query" in hint.lower()
