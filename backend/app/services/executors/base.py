"""
QueryfyAI - Base Query Executor

Strategy Pattern interface for database query execution.
Each database type implements its own executor strategy.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class QueryExecutor(ABC):
    """
    Abstract base class for database query executors.

    Implements the Strategy pattern - each database type provides
    its own implementation of query execution.
    """

    # Override in subclasses
    DB_TYPE: str = ""
    SUPPORTS_ASYNC: bool = False
    SUPPORTS_DML: bool = False  # Whether executor supports DML operations
    SUPPORTS_SANDBOX: bool = False  # Whether executor supports sandbox mode (rollback)

    @abstractmethod
    async def execute(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a query against the database.

        Args:
            connection_url: Database connection string
            query: The query to execute (SQL or MongoDB syntax)
            limit: Maximum number of rows to return
            timeout: Query timeout in seconds

        Returns:
            Dict containing:
                - success: bool
                - columns: List[str] - column names
                - rows: List[Dict] - result rows as dicts
                - row_count: int - number of rows returned
                - has_more: bool - whether more rows exist
                - error: Optional[str] - error message if failed
        """
        pass

    @abstractmethod
    async def test_connection(self, connection_url: str) -> Dict[str, Any]:
        """
        Test database connection.

        Args:
            connection_url: Database connection string

        Returns:
            Dict containing:
                - success: bool
                - message: str - success or error message
                - version: Optional[str] - database version if available
        """
        pass

    async def execute_dml(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute a DML (INSERT, UPDATE, DELETE) statement.

        Default implementation raises NotImplementedError.
        Override in subclasses that support DML operations.

        Args:
            connection_url: Database connection string
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict containing:
                - success: bool
                - rows_affected: int
                - execution_time: float
                - error: Optional[str]
        """
        raise NotImplementedError(f"DML operations not supported for {self.DB_TYPE}")

    def format_results(
        self, columns: List[str], rows: List[tuple], limit: int
    ) -> Dict[str, Any]:
        """
        Format query results into standard response structure.

        Args:
            columns: List of column names
            rows: List of row tuples
            limit: The limit used in the query

        Returns:
            Standardized result dictionary
        """
        has_more = len(rows) > limit
        result_rows = rows[:limit] if has_more else rows

        return {
            "success": True,
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in result_rows],
            "row_count": len(result_rows),
            "has_more": has_more,
            "error": None,
        }

    def format_dict_results(
        self, rows: List[Dict[str, Any]], limit: int
    ) -> Dict[str, Any]:
        """
        Format results that are already in dict format.

        Args:
            rows: List of row dictionaries
            limit: The limit used in the query

        Returns:
            Standardized result dictionary
        """
        has_more = len(rows) > limit
        result_rows = rows[:limit] if has_more else rows

        # Extract columns from first row if available
        columns = list(result_rows[0].keys()) if result_rows else []

        return {
            "success": True,
            "columns": columns,
            "rows": result_rows,
            "row_count": len(result_rows),
            "has_more": has_more,
            "error": None,
        }

    def error_result(self, error: str) -> Dict[str, Any]:
        """
        Create an error result.

        Args:
            error: Error message

        Returns:
            Error result dictionary
        """
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "has_more": False,
            "error": error,
        }

    def add_limit_to_query(self, query: str, limit: int) -> str:
        """
        Add LIMIT clause to query if not present.
        Override in subclasses for non-standard syntax.

        Args:
            query: Original query
            limit: Limit to add

        Returns:
            Query with LIMIT clause
        """
        import re

        query_upper = query.upper().strip()

        # Don't add limit if already present (use word boundary to avoid false positives)
        # This prevents bypasses like SELECT 'LIMIT' as col FROM users
        if re.search(r"\bLIMIT\s+\d+", query_upper):
            return query

        # Don't add limit if it's not a SELECT query
        if not query_upper.startswith("SELECT"):
            return query

        return f"{query} LIMIT {limit}"


class SyncQueryExecutor(QueryExecutor):
    """
    Base class for synchronous database drivers.

    Wraps synchronous execution in an async method using
    run_in_executor for compatibility with async API.
    """

    SUPPORTS_ASYNC: bool = False

    @abstractmethod
    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous query execution.
        Implement this instead of execute() for sync drivers.
        """
        pass

    @abstractmethod
    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """
        Synchronous connection test.
        Implement this instead of test_connection() for sync drivers.
        """
        pass

    async def execute(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Wrap sync execution in async context."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.execute_sync(connection_url, query, limit, timeout)
        )

    async def test_connection(self, connection_url: str) -> Dict[str, Any]:
        """Wrap sync connection test in async context."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.test_connection_sync(connection_url)
        )

    def execute_dml_sync(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Synchronous DML execution.
        Override in subclasses that support DML operations.

        Args:
            connection_url: Database connection string
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict containing:
                - success: bool
                - rows_affected: int
                - execution_time: float
                - error: Optional[str]
        """
        raise NotImplementedError(f"DML operations not supported for {self.DB_TYPE}")

    async def execute_dml(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """Wrap sync DML execution in async context."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.execute_dml_sync(connection_url, sql, rollback, timeout)
        )
