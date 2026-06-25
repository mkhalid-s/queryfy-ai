"""
QueryfyAI - DuckDB Query Executor

Synchronous SQL executor for DuckDB - an embeddable OLAP database.
Excellent for analytics, in-memory processing, and direct Parquet/CSV queries.
Uses standard SQL LIMIT syntax.

IMPORTANT - Deployment Considerations:
========================================
DuckDB is an embedded database. The database files must be accessible to the
backend server process. This works well for:

  - Local development and testing
  - Self-hosted single-user deployments
  - Analytics workloads querying local Parquet/CSV files
  - CI/CD pipelines with test data

For multi-user production deployments:
  - Database files must be on shared storage (NFS, EFS, etc.)
  - Docker/K8s: Mount volumes with database files
  - Consider using MotherDuck (cloud DuckDB) for remote access:
    duckdb:///md:my_database
  - DuckDB can query remote files directly:
    duckdb:///s3://bucket/data.parquet (requires httpfs extension)

NOT recommended for:
  - Multi-tenant SaaS where users expect to query their local files
  - Scenarios where the server cannot access the database file path
"""

import logging
from typing import Any, Dict, Optional

from .base import SyncQueryExecutor

logger = logging.getLogger(__name__)


class DuckDBExecutor(SyncQueryExecutor):
    """
    DuckDB query executor using duckdb Python package.

    Features:
    - In-memory or file-based databases
    - Direct Parquet/CSV file queries
    - Standard SQL with LIMIT support
    - Fast analytical queries

    Connection URL formats:
    - duckdb:///path/to/database.duckdb
    - duckdb://:memory:
    - duckdb:///path/to/data.parquet (direct file query)
    """

    DB_TYPE = "duckdb"
    SUPPORTS_DML = True
    SUPPORTS_SANDBOX = True

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using DuckDB."""
        try:
            import duckdb

            db_path = self._parse_duckdb_url(connection_url)

            # Connect to database (in-memory or file)
            conn = (
                duckdb.connect(db_path, read_only=True)
                if db_path != ":memory:"
                else duckdb.connect()
            )

            try:
                fetch_limit = limit + 1
                query_with_limit = self.add_limit_to_query(query, fetch_limit)

                result = conn.execute(query_with_limit)

                columns = (
                    [desc[0] for desc in result.description]
                    if result.description
                    else []
                )
                rows = result.fetchall()

                return self.format_results(columns, rows, limit)
            finally:
                conn.close()

        except ImportError:
            logger.error("DuckDB not installed. Install with: pip install duckdb")
            return self.error_result("DuckDB driver not installed")
        except Exception as e:
            logger.error(f"DuckDB executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test DuckDB connection."""
        try:
            import duckdb

            db_path = self._parse_duckdb_url(connection_url)

            # Connect and get version
            conn = (
                duckdb.connect(db_path) if db_path != ":memory:" else duckdb.connect()
            )
            try:
                result = conn.execute("SELECT version()").fetchone()
                version = result[0] if result else "Unknown"

                # Also check if it's a file or in-memory
                mode = "in-memory" if db_path == ":memory:" else f"file: {db_path}"

                return {
                    "success": True,
                    "message": f"Connection successful ({mode})",
                    "version": f"DuckDB {version}",
                }
            finally:
                conn.close()

        except ImportError:
            return {
                "success": False,
                "message": "DuckDB driver not installed. Install with: pip install duckdb",
                "version": None,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_duckdb_url(self, url: str) -> str:
        """
        Parse DuckDB connection URL.

        Formats:
        - duckdb:///path/to/database.duckdb
        - duckdb://:memory:
        - duckdb://./relative/path.duckdb
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)

        # Handle :memory: special case
        if parsed.netloc == ":memory:" or url.endswith(":memory:"):
            return ":memory:"

        # Handle file path
        path = parsed.path
        if not path or path == "/":
            return ":memory:"

        # Remove leading slash for relative paths on Windows
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]

        return path

    def execute_dml_sync(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute DML (INSERT, UPDATE, DELETE) with transaction control.

        Args:
            connection_url: DuckDB connection URL
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds (not directly supported by DuckDB)

        Returns:
            Dict with rows_affected, execution_time, error
        """
        from datetime import datetime

        import duckdb

        start_time = datetime.now()

        try:
            db_path = self._parse_duckdb_url(connection_url)

            # Connect in read-write mode for DML
            conn = duckdb.connect(db_path)

            try:
                # Begin transaction explicitly
                conn.execute("BEGIN TRANSACTION")

                try:
                    conn.execute(sql)

                    # DuckDB DML doesn't return rows - use changes() to get affected count
                    changes_result = conn.execute("SELECT changes()").fetchone()
                    rows_affected = changes_result[0] if changes_result else 0

                    if rollback:
                        conn.execute("ROLLBACK")
                        logger.info(
                            f"DuckDB DML sandbox: {rows_affected} rows (rolled back)"
                        )
                    else:
                        conn.execute("COMMIT")
                        logger.info(f"DuckDB DML executed: {rows_affected} rows")

                    execution_time = (datetime.now() - start_time).total_seconds()

                    return {
                        "success": True,
                        "rows_affected": rows_affected,
                        "execution_time": execution_time,
                        "error": None,
                    }

                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            finally:
                conn.close()

        except ImportError:
            logger.error("DuckDB not installed")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": "DuckDB driver not installed",
            }
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"DuckDB DML error ({error_type}): {e}")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML execution failed: {str(e)}",
            }
