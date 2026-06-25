"""
QueryfyAI - PostgreSQL Query Executor

Async PostgreSQL executor using asyncpg with connection pooling.
Uses the shared ConnectionPoolManager for efficient connection reuse.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager
from app.services.security import SecurityService

from .base import QueryExecutor

logger = logging.getLogger(__name__)


class PostgreSQLExecutor(QueryExecutor):
    """
    PostgreSQL query executor using asyncpg.

    Uses the shared ConnectionPoolManager for connection pooling,
    ensuring efficient connection reuse across sessions and tenants.
    """

    DB_TYPE = "postgresql"
    SUPPORTS_ASYNC = True
    SUPPORTS_DML = True
    SUPPORTS_SANDBOX = True

    async def execute(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute query using asyncpg with pooled connections.

        Uses ConnectionPoolManager for efficient connection reuse
        across multiple sessions and tenants.
        """
        try:
            # Sanitize and add limit
            query = SecurityService.sanitize_sql_for_execution(query)
            fetch_limit = limit + 1  # Fetch one extra to detect has_more
            query_with_limit = self.add_limit_to_query(query, fetch_limit)

            # Create DatabaseConfig for pool manager
            config = DatabaseConfig(db_type="postgresql", connection_url=connection_url)

            # Use shared connection pool manager
            async with pool_manager.get_connection(config) as conn:
                # Execute query with timeout
                if timeout:
                    rows = await asyncio.wait_for(
                        conn.fetch(query_with_limit), timeout=timeout
                    )
                else:
                    rows = await conn.fetch(query_with_limit)

                if not rows:
                    return {
                        "success": True,
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "has_more": False,
                        "error": None,
                    }

                # Get column names from first row
                columns = list(rows[0].keys())

                # Convert to list of tuples for format_results
                row_tuples = [tuple(row.values()) for row in rows]

                return self.format_results(columns, row_tuples, limit)

        except asyncio.TimeoutError:
            logger.warning(f"PostgreSQL query timeout after {timeout}s")
            return self.error_result(f"Query exceeded timeout of {timeout} seconds")
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"PostgreSQL query error ({error_type}): {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    async def test_connection(self, connection_url: str) -> Dict[str, Any]:
        """Test PostgreSQL connection using pool manager."""
        try:
            config = DatabaseConfig(db_type="postgresql", connection_url=connection_url)

            async with pool_manager.get_connection(config) as conn:
                version = await conn.fetchval("SELECT version()")
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": version,
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    async def execute_dml(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute DML (INSERT, UPDATE, DELETE) with transaction control.

        Args:
            connection_url: PostgreSQL connection URL
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict with rows_affected, execution_time, error
        """
        from datetime import datetime

        import asyncpg

        start_time = datetime.now()

        try:
            # Direct connection for transaction control
            conn = await asyncpg.connect(connection_url)

            try:
                # Start transaction
                tr = conn.transaction()
                await tr.start()

                try:
                    # Execute DML with timeout
                    if timeout:
                        result = await asyncio.wait_for(
                            conn.execute(sql), timeout=timeout
                        )
                    else:
                        result = await conn.execute(sql)

                    # Parse rows affected from result (e.g., "DELETE 5", "UPDATE 3", "INSERT 0 1")
                    rows_affected = 0
                    if result:
                        parts = result.split()
                        if parts:
                            # Last number is usually rows affected
                            for part in reversed(parts):
                                if part.isdigit():
                                    rows_affected = int(part)
                                    break

                    if rollback:
                        await tr.rollback()
                        logger.info(f"DML sandbox: {result} (rolled back)")
                    else:
                        await tr.commit()
                        logger.info(f"DML executed: {result}")

                    execution_time = (datetime.now() - start_time).total_seconds()

                    return {
                        "success": True,
                        "rows_affected": rows_affected,
                        "execution_time": execution_time,
                        "error": None,
                    }

                except Exception:
                    await tr.rollback()
                    raise

            finally:
                await conn.close()

        except asyncio.TimeoutError:
            logger.warning(f"DML timeout after {timeout}s")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML exceeded timeout of {timeout} seconds",
            }
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"DML error ({error_type}): {e}")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML execution failed: {str(e)}",
            }
