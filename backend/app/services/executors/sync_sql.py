"""
QueryfyAI - Sync SQL Query Executors

Synchronous SQL executors for databases that don't have async drivers.
Uses the shared ConnectionPoolManager for efficient connection reuse.
"""

import logging
from typing import Any, Dict, Optional

from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager
from app.services.security import SecurityService

from .base import SyncQueryExecutor

logger = logging.getLogger(__name__)


class SnowflakeExecutor(SyncQueryExecutor):
    """
    Snowflake query executor using snowflake-connector-python.

    Uses the shared ConnectionPoolManager for connection reuse.
    """

    DB_TYPE = "snowflake"

    async def execute(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using pooled Snowflake connection."""
        try:
            import asyncio

            # Sanitize and add limit
            query = SecurityService.sanitize_sql_for_execution(query)
            fetch_limit = limit + 1
            query_with_limit = self.add_limit_to_query(query, fetch_limit)

            config = DatabaseConfig(db_type="snowflake", connection_url=connection_url)

            async with pool_manager.get_connection(config) as conn:
                # Run sync query in thread pool
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, lambda: self._execute_with_conn(conn, query_with_limit, limit)
                )
                return result

        except Exception as e:
            logger.error(f"Snowflake executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def _execute_with_conn(self, conn, query: str, limit: int) -> Dict[str, Any]:
        """Execute query with existing connection (runs in thread)."""
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            columns = (
                [desc[0] for desc in cursor.description] if cursor.description else []
            )
            rows = cursor.fetchall()
            return self.format_results(columns, rows, limit)
        finally:
            cursor.close()

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fallback sync execution (not used when pool manager available)."""
        try:
            import snowflake.connector

            params = self._parse_snowflake_url(connection_url)
            fetch_limit = limit + 1
            query_with_limit = self.add_limit_to_query(query, fetch_limit)

            conn = snowflake.connector.connect(**params)
            try:
                return self._execute_with_conn(conn, query_with_limit, limit)
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Snowflake executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test Snowflake connection."""
        try:
            import snowflake.connector

            params = self._parse_snowflake_url(connection_url)
            conn = snowflake.connector.connect(**params)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT CURRENT_VERSION()")
                version = cursor.fetchone()[0]
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": f"Snowflake {version}",
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_snowflake_url(self, url: str) -> Dict[str, Any]:
        """Parse Snowflake connection URL."""
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        return {
            "account": parsed.hostname,
            "user": parsed.username,
            "password": parsed.password,
            "database": query_params.get("database", [None])[0],
            "warehouse": query_params.get("warehouse", [None])[0],
            "schema": query_params.get("schema", ["PUBLIC"])[0],
        }


class BigQueryExecutor(SyncQueryExecutor):
    """BigQuery query executor using google-cloud-bigquery."""

    DB_TYPE = "bigquery"

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using BigQuery client."""
        try:
            from google.cloud import bigquery

            # Parse project from URL
            project_id = self._parse_bigquery_project(connection_url)

            client = bigquery.Client(project=project_id)

            fetch_limit = limit + 1
            query_with_limit = self.add_limit_to_query(query, fetch_limit)

            job_config = bigquery.QueryJobConfig()
            if timeout:
                job_config.timeout_ms = timeout * 1000

            query_job = client.query(query_with_limit, job_config=job_config)
            results = query_job.result()

            columns = [field.name for field in results.schema]
            rows = [tuple(row.values()) for row in results]

            return self.format_results(columns, rows, limit)

        except Exception as e:
            logger.error(f"BigQuery executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test BigQuery connection."""
        try:
            from google.cloud import bigquery

            project_id = self._parse_bigquery_project(connection_url)
            client = bigquery.Client(project=project_id)

            # Simple query to test connection
            query = "SELECT 1"
            query_job = client.query(query)
            query_job.result()

            return {
                "success": True,
                "message": "Connection successful",
                "version": f"BigQuery (project: {project_id})",
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_bigquery_project(self, url: str) -> str:
        """Parse project ID from BigQuery URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.hostname or parsed.path.lstrip("/")


class SQLServerExecutor(SyncQueryExecutor):
    """SQL Server query executor using pyodbc."""

    DB_TYPE = "sqlserver"
    SUPPORTS_DML = True
    SUPPORTS_SANDBOX = True

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using pyodbc."""
        try:
            import pyodbc

            conn = pyodbc.connect(connection_url, timeout=timeout or 30)
            try:
                cursor = conn.cursor()

                # SQL Server uses TOP instead of LIMIT
                query_with_limit = self._add_top_to_query(query, limit + 1)

                cursor.execute(query_with_limit)

                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )
                rows = cursor.fetchall()

                return self.format_results(columns, [tuple(row) for row in rows], limit)
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"SQL Server executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test SQL Server connection."""
        try:
            import pyodbc

            conn = pyodbc.connect(connection_url, timeout=10)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT @@VERSION")
                version = cursor.fetchone()[0]
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": version.split("\n")[0],
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _add_top_to_query(self, query: str, limit: int) -> str:
        """Add TOP clause to SQL Server query."""
        query_upper = query.upper().strip()
        if "TOP" in query_upper or not query_upper.startswith("SELECT"):
            return query
        return query.replace("SELECT", f"SELECT TOP {limit}", 1)

    def add_limit_to_query(self, query: str, limit: int) -> str:
        """SQL Server uses TOP, not LIMIT."""
        return self._add_top_to_query(query, limit)

    def execute_dml_sync(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute DML (INSERT, UPDATE, DELETE) with transaction control.

        Args:
            connection_url: SQL Server connection URL
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict with rows_affected, execution_time, error
        """
        from datetime import datetime

        import pyodbc

        start_time = datetime.now()

        try:
            # Connect with autocommit disabled for transaction control
            conn = pyodbc.connect(connection_url, autocommit=False, timeout=timeout)

            try:
                cursor = conn.cursor()
                cursor.execute(sql)
                rows_affected = cursor.rowcount

                if rollback:
                    conn.rollback()
                    logger.info(
                        f"SQL Server DML sandbox: {rows_affected} rows (rolled back)"
                    )
                else:
                    conn.commit()
                    logger.info(f"SQL Server DML executed: {rows_affected} rows")

                execution_time = (datetime.now() - start_time).total_seconds()

                return {
                    "success": True,
                    "rows_affected": rows_affected,
                    "execution_time": execution_time,
                    "error": None,
                }

            except Exception:
                conn.rollback()
                raise

            finally:
                conn.close()

        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"SQL Server DML error ({error_type}): {e}")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML execution failed: {str(e)}",
            }


class OracleExecutor(SyncQueryExecutor):
    """Oracle query executor using cx_Oracle/oracledb."""

    DB_TYPE = "oracle"
    SUPPORTS_DML = True
    SUPPORTS_SANDBOX = True

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using oracledb."""
        try:
            import oracledb

            conn = oracledb.connect(connection_url)
            try:
                cursor = conn.cursor()
                if timeout:
                    cursor.callTimeout = timeout * 1000

                # Oracle uses FETCH FIRST for limiting
                query_with_limit = self._add_fetch_first(query, limit + 1)

                cursor.execute(query_with_limit)

                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )
                rows = cursor.fetchall()

                return self.format_results(columns, rows, limit)
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Oracle executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test Oracle connection."""
        try:
            import oracledb

            conn = oracledb.connect(connection_url)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM V$VERSION WHERE BANNER LIKE 'Oracle%'")
                row = cursor.fetchone()
                version = row[0] if row else "Oracle"
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": version,
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _add_fetch_first(self, query: str, limit: int) -> str:
        """Add FETCH FIRST clause to Oracle query (12c+)."""
        query_upper = query.upper().strip()
        if "FETCH" in query_upper or "ROWNUM" in query_upper:
            return query
        if not query_upper.startswith("SELECT"):
            return query
        return f"{query} FETCH FIRST {limit} ROWS ONLY"

    def add_limit_to_query(self, query: str, limit: int) -> str:
        """Oracle uses FETCH FIRST, not LIMIT."""
        return self._add_fetch_first(query, limit)

    def execute_dml_sync(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute DML (INSERT, UPDATE, DELETE) with transaction control.

        Args:
            connection_url: Oracle connection URL
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict with rows_affected, execution_time, error
        """
        from datetime import datetime

        import oracledb

        start_time = datetime.now()

        try:
            # Connect - Oracle has autocommit off by default
            conn = oracledb.connect(connection_url)

            try:
                cursor = conn.cursor()
                if timeout:
                    cursor.callTimeout = timeout * 1000  # milliseconds

                cursor.execute(sql)
                rows_affected = cursor.rowcount

                if rollback:
                    conn.rollback()
                    logger.info(
                        f"Oracle DML sandbox: {rows_affected} rows (rolled back)"
                    )
                else:
                    conn.commit()
                    logger.info(f"Oracle DML executed: {rows_affected} rows")

                execution_time = (datetime.now() - start_time).total_seconds()

                return {
                    "success": True,
                    "rows_affected": rows_affected,
                    "execution_time": execution_time,
                    "error": None,
                }

            except Exception:
                conn.rollback()
                raise

            finally:
                conn.close()

        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"Oracle DML error ({error_type}): {e}")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML execution failed: {str(e)}",
            }


class ClickHouseExecutor(SyncQueryExecutor):
    """ClickHouse query executor using clickhouse-driver."""

    DB_TYPE = "clickhouse"

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using clickhouse-driver."""
        try:
            from clickhouse_driver import Client

            params = self._parse_clickhouse_url(connection_url)
            client = Client(**params)

            fetch_limit = limit + 1
            query_with_limit = self.add_limit_to_query(query, fetch_limit)

            result = client.execute(query_with_limit, with_column_types=True)
            rows, columns_info = result

            columns = [col[0] for col in columns_info]

            return self.format_results(columns, rows, limit)

        except Exception as e:
            logger.error(f"ClickHouse executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test ClickHouse connection."""
        try:
            from clickhouse_driver import Client

            params = self._parse_clickhouse_url(connection_url)
            client = Client(**params)

            result = client.execute("SELECT version()")
            version = result[0][0] if result else "Unknown"

            return {
                "success": True,
                "message": "Connection successful",
                "version": f"ClickHouse {version}",
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_clickhouse_url(self, url: str) -> Dict[str, Any]:
        """Parse ClickHouse connection URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 9000,
            "user": parsed.username or "default",
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/") or "default",
        }


class TrinoExecutor(SyncQueryExecutor):
    """Trino/Presto/Athena query executor using trino-python-client."""

    DB_TYPE = "trino"

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using Trino client."""
        try:
            import trino

            params = self._parse_trino_url(connection_url)

            conn = trino.dbapi.connect(**params)
            try:
                cursor = conn.cursor()

                fetch_limit = limit + 1
                query_with_limit = self.add_limit_to_query(query, fetch_limit)

                cursor.execute(query_with_limit)
                rows = cursor.fetchall()

                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )

                return self.format_results(columns, rows, limit)
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Trino executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test Trino connection."""
        try:
            import trino

            params = self._parse_trino_url(connection_url)
            conn = trino.dbapi.connect(**params)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": "Trino",
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_trino_url(self, url: str) -> Dict[str, Any]:
        """Parse Trino connection URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path_parts = parsed.path.lstrip("/").split("/")

        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 8080,
            "user": parsed.username or "trino",
            "catalog": path_parts[0] if path_parts else "hive",
            "schema": path_parts[1] if len(path_parts) > 1 else "default",
        }


class HiveExecutor(SyncQueryExecutor):
    """Hive/Spark query executor using PyHive."""

    DB_TYPE = "hive"

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using PyHive."""
        try:
            from pyhive import hive

            params = self._parse_hive_url(connection_url)

            conn = hive.connect(**params)
            try:
                cursor = conn.cursor()

                fetch_limit = limit + 1
                query_with_limit = self.add_limit_to_query(query, fetch_limit)

                cursor.execute(query_with_limit)
                rows = cursor.fetchall()

                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )

                return self.format_results(columns, rows, limit)
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Hive executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test Hive connection."""
        try:
            from pyhive import hive

            params = self._parse_hive_url(connection_url)
            conn = hive.connect(**params)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": "Hive",
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_hive_url(self, url: str) -> Dict[str, Any]:
        """Parse Hive connection URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 10000,
            "username": parsed.username,
            "database": parsed.path.lstrip("/") or "default",
        }


# Aliases for Presto and Athena (use Trino executor)
PrestoExecutor = TrinoExecutor
AthenaExecutor = TrinoExecutor

# Alias for Spark (use Hive executor)
SparkExecutor = HiveExecutor


# Alias for Redshift (use PostgreSQL-compatible executor)
class RedshiftExecutor(SyncQueryExecutor):
    """Redshift query executor using psycopg2."""

    DB_TYPE = "redshift"

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using psycopg2."""
        try:
            import psycopg2

            conn = psycopg2.connect(connection_url)
            try:
                cursor = conn.cursor()
                if timeout:
                    cursor.execute(f"SET statement_timeout = {timeout * 1000}")

                fetch_limit = limit + 1
                query_with_limit = self.add_limit_to_query(query, fetch_limit)

                cursor.execute(query_with_limit)

                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )
                rows = cursor.fetchall()

                return self.format_results(columns, rows, limit)
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Redshift executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test Redshift connection."""
        try:
            import psycopg2

            conn = psycopg2.connect(connection_url)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0]
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": version.split(",")[0] if version else "Redshift",
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }


class DatabricksExecutor(SyncQueryExecutor):
    """Databricks query executor using databricks-sql-connector."""

    DB_TYPE = "databricks"

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using Databricks SQL connector."""
        try:
            from databricks import sql

            params = self._parse_databricks_url(connection_url)

            conn = sql.connect(**params)
            try:
                cursor = conn.cursor()

                fetch_limit = limit + 1
                query_with_limit = self.add_limit_to_query(query, fetch_limit)

                cursor.execute(query_with_limit)
                rows = cursor.fetchall()

                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )

                return self.format_results(columns, rows, limit)
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Databricks executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test Databricks connection."""
        try:
            from databricks import sql

            params = self._parse_databricks_url(connection_url)
            conn = sql.connect(**params)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": "Databricks",
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_databricks_url(self, url: str) -> Dict[str, Any]:
        """Parse Databricks connection URL."""
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        return {
            "server_hostname": parsed.hostname,
            "http_path": query_params.get("http_path", ["/sql/1.0/warehouses/"])[0],
            "access_token": parsed.password or query_params.get("token", [None])[0],
        }
