"""
QueryfyAI - Cassandra Query Executor

Cassandra executor using cassandra-driver for CQL query execution.
Wraps synchronous driver in async executor pattern.
"""

import asyncio
import base64
import logging
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from .base import QueryExecutor

logger = logging.getLogger(__name__)


class CassandraExecutor(QueryExecutor):
    """
    Cassandra query executor using cassandra-driver.

    Features:
    - CQL SELECT query execution
    - Type serialization for JSON-incompatible types
    - LIMIT enforcement for safety
    - Connection pooling via Cluster
    """

    DB_TYPE = "cassandra"
    SUPPORTS_ASYNC = False  # Uses sync driver with executor

    def _parse_connection_url(self, url: str) -> Dict[str, Any]:
        """Parse Cassandra connection URL."""
        from urllib.parse import unquote, urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 9042,
            "username": unquote(parsed.username) if parsed.username else None,
            "password": unquote(parsed.password) if parsed.password else None,
            "keyspace": parsed.path.lstrip("/") if parsed.path else None,
        }

    def _create_session(self, connection_url: str):
        """Create Cassandra session (sync)."""
        from cassandra.auth import PlainTextAuthProvider
        from cassandra.cluster import Cluster

        params = self._parse_connection_url(connection_url)

        auth_provider = None
        if params["username"] and params["password"]:
            auth_provider = PlainTextAuthProvider(
                username=params["username"], password=params["password"]
            )

        cluster = Cluster(
            contact_points=[params["host"]],
            port=params["port"],
            auth_provider=auth_provider,
            protocol_version=4,
        )

        session = cluster.connect()
        session._cluster_ref = cluster

        if params["keyspace"]:
            session.set_keyspace(params["keyspace"])

        return session

    def _close_session(self, session):
        """Close Cassandra session."""
        try:
            if hasattr(session, "_cluster_ref"):
                session._cluster_ref.shutdown()
        except Exception as e:
            logger.warning(f"Error closing Cassandra session: {e}")

    def _sanitize_query(self, query: str) -> str:
        """
        Sanitize CQL query for safe execution.

        Only allows SELECT statements.
        """
        query = query.strip()

        # Remove trailing semicolons
        query = query.rstrip(";")

        # Ensure it's a SELECT query
        if not query.upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

        # Block dangerous keywords
        dangerous_patterns = [
            r"\bDROP\b",
            r"\bTRUNCATE\b",
            r"\bDELETE\b",
            r"\bINSERT\b",
            r"\bUPDATE\b",
            r"\bCREATE\b",
            r"\bALTER\b",
            r"\bGRANT\b",
            r"\bREVOKE\b",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                raise ValueError("Query contains forbidden operation")

        return query

    def _add_limit_to_cql(self, query: str, limit: int) -> str:
        """Add LIMIT clause to CQL query if not present."""
        query_upper = query.upper().strip()

        # Check if LIMIT already present
        if "LIMIT" in query_upper:
            return query

        # Add LIMIT before any trailing clauses
        return f"{query} LIMIT {limit}"

    def _serialize_value(self, value: Any) -> Any:
        """
        Serialize Cassandra types to JSON-compatible values.

        Handles:
        - UUID/timeuuid -> str
        - datetime/date/time -> ISO format
        - Decimal -> float
        - bytes/blob -> base64
        - set -> list
        - frozen types -> recursive
        """
        if value is None:
            return None

        # UUID types
        if isinstance(value, UUID):
            return str(value)

        # Date/time types
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, time):
            return value.isoformat()

        # Numeric types
        if isinstance(value, Decimal):
            return float(value)

        # Binary types
        if isinstance(value, (bytes, bytearray)):
            return base64.b64encode(value).decode("utf-8")

        # Collection types
        if isinstance(value, set):
            return [self._serialize_value(v) for v in value]
        if isinstance(value, frozenset):
            return [self._serialize_value(v) for v in value]
        if isinstance(value, list):
            return [self._serialize_value(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self._serialize_value(v) for k, v in value.items()}
        if isinstance(value, tuple):
            return [self._serialize_value(v) for v in value]

        # Standard types
        if isinstance(value, (str, int, float, bool)):
            return value

        # Fallback: convert to string
        return str(value)

    def _serialize_row(self, row, columns: List[str]) -> Dict[str, Any]:
        """Serialize a result row to a JSON-compatible dict."""
        result = {}
        for i, col in enumerate(columns):
            value = row[i] if hasattr(row, "__getitem__") else getattr(row, col, None)
            result[col] = self._serialize_value(value)
        return result

    def _execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Synchronous query execution."""
        session = None
        try:
            # Sanitize query
            query = self._sanitize_query(query)

            # Add limit (fetch one extra to detect has_more)
            fetch_limit = limit + 1
            query_with_limit = self._add_limit_to_cql(query, fetch_limit)

            # Create session
            session = self._create_session(connection_url)

            # Execute query
            if timeout:
                session.default_timeout = timeout

            result = session.execute(query_with_limit)

            # Get column names
            columns = (
                [col.name for col in result.column_names]
                if hasattr(result, "column_names")
                else []
            )
            if not columns and result.column_names:
                columns = list(result.column_names)

            # Fetch all rows
            rows = list(result)

            if not rows:
                return {
                    "success": True,
                    "columns": columns,
                    "rows": [],
                    "row_count": 0,
                    "has_more": False,
                    "error": None,
                }

            # Determine has_more
            has_more = len(rows) > limit
            result_rows = rows[:limit] if has_more else rows

            # Get columns from first row if not available
            if not columns and result_rows:
                columns = (
                    list(result_rows[0]._fields)
                    if hasattr(result_rows[0], "_fields")
                    else []
                )

            # Serialize rows
            serialized_rows = [self._serialize_row(row, columns) for row in result_rows]

            return {
                "success": True,
                "columns": columns,
                "rows": serialized_rows,
                "row_count": len(serialized_rows),
                "has_more": has_more,
                "error": None,
            }

        except ValueError as e:
            # Query validation errors
            return self.error_result(str(e))
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"Cassandra query error ({error_type}): {e}")
            return self.error_result(f"Query execution failed: {str(e)}")
        finally:
            if session:
                self._close_session(session)

    async def execute(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute CQL query asynchronously.

        Wraps synchronous cassandra-driver in executor.
        """
        loop = asyncio.get_event_loop()

        try:
            if timeout:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._execute_sync(
                            connection_url, query, limit, timeout
                        ),
                    ),
                    timeout=timeout,
                )
            else:
                result = await loop.run_in_executor(
                    None,
                    lambda: self._execute_sync(connection_url, query, limit, timeout),
                )

            return result

        except asyncio.TimeoutError:
            logger.warning(f"Cassandra query timeout after {timeout}s")
            return self.error_result(f"Query exceeded timeout of {timeout} seconds")

    def _test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Synchronous connection test."""
        session = None
        try:
            session = self._create_session(connection_url)

            # Test with simple query
            result = session.execute("SELECT release_version FROM system.local")
            row = result.one()
            version = row.release_version if row else "unknown"

            return {
                "success": True,
                "message": "Connection successful",
                "version": f"Cassandra {version}",
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }
        finally:
            if session:
                self._close_session(session)

    async def test_connection(self, connection_url: str) -> Dict[str, Any]:
        """Test Cassandra connection."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._test_connection_sync(connection_url)
        )
