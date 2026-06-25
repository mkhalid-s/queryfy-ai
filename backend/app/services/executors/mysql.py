"""
QueryfyAI - MySQL Query Executor

Async MySQL executor using aiomysql with connection pooling.
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


class MySQLExecutor(QueryExecutor):
    """
    MySQL query executor using aiomysql.

    Uses the shared ConnectionPoolManager for connection pooling,
    ensuring efficient connection reuse across sessions and tenants.
    """

    DB_TYPE = "mysql"
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
        Execute query using aiomysql with pooled connections.

        Uses ConnectionPoolManager for efficient connection reuse
        across multiple sessions and tenants.
        """
        try:
            # Sanitize and add limit
            query = SecurityService.sanitize_sql_for_execution(query)
            fetch_limit = limit + 1
            query_with_limit = self.add_limit_to_query(query, fetch_limit)

            # Create DatabaseConfig for pool manager
            config = DatabaseConfig(db_type="mysql", connection_url=connection_url)

            # Use shared connection pool manager
            async with pool_manager.get_connection(config) as conn:
                async with conn.cursor() as cursor:
                    # Execute with timeout
                    if timeout:
                        await asyncio.wait_for(
                            cursor.execute(query_with_limit), timeout=timeout
                        )
                    else:
                        await cursor.execute(query_with_limit)

                    rows = await cursor.fetchall()

                    if not rows:
                        return {
                            "success": True,
                            "columns": [],
                            "rows": [],
                            "row_count": 0,
                            "has_more": False,
                            "error": None,
                        }

                    # Get column names from cursor description
                    columns = (
                        [col[0] for col in cursor.description]
                        if cursor.description
                        else []
                    )

                    return self.format_results(columns, list(rows), limit)

        except asyncio.TimeoutError:
            logger.warning(f"MySQL query timeout after {timeout}s")
            return self.error_result(f"Query exceeded timeout of {timeout} seconds")
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"MySQL query error ({error_type}): {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    async def test_connection(self, connection_url: str) -> Dict[str, Any]:
        """Test MySQL connection using pool manager."""
        try:
            config = DatabaseConfig(db_type="mysql", connection_url=connection_url)

            async with pool_manager.get_connection(config) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT VERSION()")
                    result = await cursor.fetchone()
                    version = result[0] if result else "Unknown"

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
            connection_url: MySQL connection URL
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict with rows_affected, execution_time, error
        """
        from datetime import datetime
        from urllib.parse import parse_qs, urlparse

        import aiomysql

        start_time = datetime.now()

        try:
            # Parse connection URL for direct connection (not pooled)
            parsed = urlparse(connection_url)
            parse_qs(parsed.query) if parsed.query else {}

            # Extract connection parameters
            host = parsed.hostname or "localhost"
            port = parsed.port or 3306
            user = parsed.username or "root"
            password = parsed.password or ""
            db_path = parsed.path.strip("/")
            database = db_path.split("/")[0] if db_path else None

            # Direct connection with autocommit disabled for transaction control
            conn = await aiomysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                db=database,
                autocommit=False,  # Manual transaction control
            )

            try:
                async with conn.cursor() as cursor:
                    # Start transaction explicitly
                    await cursor.execute("START TRANSACTION")

                    try:
                        # Execute DML with timeout
                        if timeout:
                            await asyncio.wait_for(cursor.execute(sql), timeout=timeout)
                        else:
                            await cursor.execute(sql)

                        rows_affected = cursor.rowcount

                        if rollback:
                            await cursor.execute("ROLLBACK")
                            logger.info(
                                f"MySQL DML sandbox: {rows_affected} rows (rolled back)"
                            )
                        else:
                            await cursor.execute("COMMIT")
                            logger.info(f"MySQL DML executed: {rows_affected} rows")

                        execution_time = (datetime.now() - start_time).total_seconds()

                        return {
                            "success": True,
                            "rows_affected": rows_affected,
                            "execution_time": execution_time,
                            "error": None,
                        }

                    except Exception:
                        await cursor.execute("ROLLBACK")
                        raise

            finally:
                conn.close()
                await conn.wait_closed()

        except asyncio.TimeoutError:
            logger.warning(f"MySQL DML timeout after {timeout}s")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML exceeded timeout of {timeout} seconds",
            }
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"MySQL DML error ({error_type}): {e}")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML execution failed: {str(e)}",
            }
