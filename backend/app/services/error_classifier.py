"""
QueryfyAI - Error Classifier

Classifies database errors and determines appropriate retry strategies.
Used by the SQL agent to implement adaptive retry behavior.
"""

import re
from enum import Enum
from typing import Tuple


class ErrorType(Enum):
    """Classification of database error types."""

    SYNTAX = "syntax"  # SQL syntax errors
    SEMANTIC = "semantic"  # Wrong table/column names
    TIMEOUT = "timeout"  # Query took too long
    PERMISSION = "permission"  # Access denied
    CONNECTION = "connection"  # Connection issues
    CONSTRAINT = "constraint"  # Constraint violations
    TYPE_MISMATCH = "type"  # Data type errors
    UNKNOWN = "unknown"


class RetryStrategy(Enum):
    """Retry strategy based on error type."""

    REGENERATE = "regenerate"  # Ask LLM to regenerate completely
    FIX_SYNTAX = "fix_syntax"  # Ask LLM to fix specific syntax
    SIMPLIFY = "simplify"  # Simplify the query
    ADD_SCHEMA_CONTEXT = "add_context"  # Add more schema details
    NO_RETRY = "no_retry"  # Don't retry (permission, connection)


class ErrorClassifier:
    """
    Classifies database errors and determines retry strategies.

    Uses pattern matching on error messages to identify error types
    and map them to appropriate retry strategies.
    """

    # Error patterns for classification
    # Each pattern is a list of regex patterns that match that error type
    PATTERNS = {
        ErrorType.SYNTAX: [
            r"syntax error",
            r"unexpected token",
            r"parse error",
            r"invalid.*syntax",
            r"near \".*\"",
            r"mismatched input",
            r"extraneous input",
            r"expecting",
            r"unterminated",
            r"missing.*keyword",
        ],
        ErrorType.SEMANTIC: [
            r"(table|relation|column).*does not exist",
            r"(table|relation|column).*not found",
            r"unknown (table|column|field)",
            r"no such (table|column)",
            r"invalid.*identifier",
            r"undefined (table|column)",
            r"cannot find",
            r"ambiguous column",
        ],
        ErrorType.TIMEOUT: [
            r"timeout",
            r"exceeded.*time",
            r"query.*cancelled",
            r"statement timeout",
            r"execution time limit",
            r"taking too long",
        ],
        ErrorType.PERMISSION: [
            r"permission denied",
            r"access denied",
            r"insufficient privileges",
            r"not authorized",
            r"unauthorized",
            r"forbidden",
        ],
        ErrorType.CONNECTION: [
            r"connection (refused|reset|closed)",
            r"could not connect",
            r"network error",
            r"host.*not found",
            r"connection timed out",
            r"ssl.*error",
        ],
        ErrorType.CONSTRAINT: [
            r"constraint.*violated",
            r"duplicate key",
            r"unique.*violation",
            r"foreign key.*violation",
            r"check constraint",
            r"not null.*violation",
        ],
        ErrorType.TYPE_MISMATCH: [
            r"type mismatch",
            r"cannot cast",
            r"invalid.*type",
            r"incompatible types",
            r"cannot compare",
            r"operator does not exist",
            r"invalid input syntax for type",
        ],
    }

    # Retry strategies mapped to each error type
    STRATEGIES = {
        ErrorType.SYNTAX: RetryStrategy.FIX_SYNTAX,
        ErrorType.SEMANTIC: RetryStrategy.ADD_SCHEMA_CONTEXT,
        ErrorType.TIMEOUT: RetryStrategy.SIMPLIFY,
        ErrorType.PERMISSION: RetryStrategy.NO_RETRY,
        ErrorType.CONNECTION: RetryStrategy.NO_RETRY,
        ErrorType.CONSTRAINT: RetryStrategy.REGENERATE,
        ErrorType.TYPE_MISMATCH: RetryStrategy.FIX_SYNTAX,
        ErrorType.UNKNOWN: RetryStrategy.REGENERATE,
    }

    @classmethod
    def classify(cls, error_message: str) -> Tuple[ErrorType, RetryStrategy]:
        """
        Classify an error message and return appropriate retry strategy.

        Args:
            error_message: The error message from the database

        Returns:
            Tuple of (ErrorType, RetryStrategy)
        """
        error_lower = error_message.lower()

        for error_type, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_lower):
                    return error_type, cls.STRATEGIES[error_type]

        return ErrorType.UNKNOWN, RetryStrategy.REGENERATE

    @classmethod
    def get_retry_prompt_modifier(
        cls, strategy: RetryStrategy, error_message: str, failed_sql: str
    ) -> str:
        """
        Get prompt modifier based on retry strategy.

        Returns additional context to add to the LLM prompt when retrying
        to help it understand and fix the error.

        Args:
            strategy: The retry strategy to use
            error_message: The error message from the database
            failed_sql: The SQL that failed

        Returns:
            Additional prompt text to help the LLM fix the error
        """
        modifiers = {
            RetryStrategy.FIX_SYNTAX: f"""
PREVIOUS ATTEMPT FAILED - SYNTAX ERROR:
Error: {error_message}
Failed SQL: {failed_sql}

Fix the syntax issue while preserving the query intent.
Pay attention to:
- Proper SQL keyword usage
- Correct quoting for identifiers and strings
- Matching parentheses and brackets
- Proper clause ordering (SELECT, FROM, WHERE, GROUP BY, ORDER BY)
""",
            RetryStrategy.ADD_SCHEMA_CONTEXT: f"""
PREVIOUS ATTEMPT FAILED - SCHEMA ERROR:
Error: {error_message}
Failed SQL: {failed_sql}

The query referenced tables or columns that don't exist.
Use ONLY the tables and columns from the provided schema.
Double-check:
- Table names are spelled exactly as shown in the schema
- Column names exist in the tables you're querying
- Join conditions use valid foreign key relationships
""",
            RetryStrategy.SIMPLIFY: f"""
PREVIOUS ATTEMPT FAILED - TIMEOUT/COMPLEXITY:
Error: {error_message}

The previous query was too complex or timed out.
Generate a simpler, more efficient query:
- Use LIMIT to restrict result size
- Avoid unnecessary JOINs or subqueries
- Consider breaking into multiple simpler queries
- Use indexes (filter on primary keys when possible)
- Avoid SELECT * - select only needed columns
""",
            RetryStrategy.REGENERATE: f"""
PREVIOUS ATTEMPT FAILED:
Error: {error_message}
Failed SQL: {failed_sql}

Generate a completely new approach to answer the question.
Consider alternative ways to get the same information.
""",
        }
        return modifiers.get(strategy, "")

    @classmethod
    def should_retry(
        cls, error_type: ErrorType, retry_count: int, max_retries: int = 3
    ) -> bool:
        """
        Determine if we should retry based on error type and retry count.

        Args:
            error_type: The classified error type
            retry_count: Current retry attempt number
            max_retries: Maximum number of retries allowed

        Returns:
            True if should retry, False otherwise
        """
        # Never retry permission or connection errors
        if cls.STRATEGIES[error_type] == RetryStrategy.NO_RETRY:
            return False

        # Check retry count
        return retry_count < max_retries

    @classmethod
    def get_error_user_message(cls, error_type: ErrorType, error_message: str) -> str:
        """
        Get a user-friendly error message based on error type.

        Args:
            error_type: The classified error type
            error_message: The original error message

        Returns:
            A user-friendly error message
        """
        messages = {
            ErrorType.SYNTAX: "The generated SQL has a syntax error. Please try rephrasing your question.",
            ErrorType.SEMANTIC: "The query references tables or columns that don't exist. Please check your database schema.",
            ErrorType.TIMEOUT: "The query took too long to execute. Try asking for a smaller dataset or simpler question.",
            ErrorType.PERMISSION: "You don't have permission to access the requested data.",
            ErrorType.CONNECTION: "Unable to connect to the database. Please check the connection settings.",
            ErrorType.CONSTRAINT: "The operation violates database constraints.",
            ErrorType.TYPE_MISMATCH: "The query has incompatible data types.",
            ErrorType.UNKNOWN: f"Query failed: {error_message}",
        }
        return messages.get(error_type, f"Query failed: {error_message}")
