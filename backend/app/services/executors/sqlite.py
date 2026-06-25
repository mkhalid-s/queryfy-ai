"""
QueryfyAI - SQLite Query Executor

Synchronous SQL executor for SQLite - Python's built-in database.
Essential for testing, local development, demos, and embedded apps.
Uses standard SQL LIMIT syntax.

IMPORTANT - Deployment Considerations:
========================================
SQLite is an embedded database. The database file must be accessible to the
backend server process. This works well for:

  - Local development and testing
  - Self-hosted single-user deployments
  - Demo environments with sample data
  - CI/CD pipelines with test fixtures
  - Embedded applications

For multi-user production deployments:
  - Database files must be on shared storage (NFS, EFS, etc.)
  - Docker/K8s: Mount volumes with database files
    docker run -v /host/data:/app/data ...
    Connection: sqlite:///app/data/mydb.sqlite
  - Consider SQLite limitations: single-writer, file locking

NOT recommended for:
  - Multi-tenant SaaS where users expect to query their local files
  - High-concurrency write workloads
  - Scenarios where the server cannot access the database file path

For production multi-user scenarios, consider PostgreSQL or MySQL instead.
"""

import logging
import sqlite3
from typing import Any, Dict, Optional

from .base import SyncQueryExecutor

logger = logging.getLogger(__name__)


class SQLiteExecutor(SyncQueryExecutor):
    """
    SQLite query executor using Python's built-in sqlite3 module.

    Features:
    - No external dependencies (built into Python)
    - File-based or in-memory databases
    - Standard SQL with LIMIT support
    - Great for testing and development

    Connection URL formats:
    - sqlite:///path/to/database.db
    - sqlite:///:memory:
    - sqlite:///./relative/path.db
    """

    DB_TYPE = "sqlite"
    SUPPORTS_DML = True
    SUPPORTS_SANDBOX = True

    def execute_sync(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute query using SQLite."""
        try:
            db_path = self._parse_sqlite_url(connection_url)

            # Connect with timeout if specified
            conn = sqlite3.connect(
                db_path, timeout=timeout or 30.0, check_same_thread=False
            )

            try:
                # Enable foreign keys for better data integrity
                conn.execute("PRAGMA foreign_keys = ON")

                cursor = conn.cursor()

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
            logger.error(f"SQLite executor error: {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    def test_connection_sync(self, connection_url: str) -> Dict[str, Any]:
        """Test SQLite connection."""
        try:
            db_path = self._parse_sqlite_url(connection_url)

            conn = sqlite3.connect(db_path, timeout=10.0)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT sqlite_version()")
                version = cursor.fetchone()[0]

                # Check database mode
                mode = "in-memory" if db_path == ":memory:" else f"file: {db_path}"

                return {
                    "success": True,
                    "message": f"Connection successful ({mode})",
                    "version": f"SQLite {version}",
                }
            finally:
                conn.close()

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def _parse_sqlite_url(self, url: str) -> str:
        """
        Parse SQLite connection URL.

        Formats:
        - sqlite:///path/to/database.db
        - sqlite:///:memory:
        - sqlite:///./relative/path.db
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)

        # Handle :memory: special case
        if parsed.path == "/:memory:" or url.endswith(":memory:"):
            return ":memory:"

        # Handle file path
        path = parsed.path
        if not path or path == "/":
            return ":memory:"

        # Remove leading slash for file paths
        # sqlite:///path -> /path (Unix) or sqlite:///C:/path -> C:/path (Windows)
        if path.startswith("/"):
            # Check for Windows path like /C:/
            if len(path) > 2 and path[2] == ":":
                path = path[1:]

        return path

    def execute_dml_sync(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute DML (INSERT, UPDATE, DELETE) with transaction control.

        Args:
            connection_url: SQLite connection URL
            sql: DML statement to execute
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict with rows_affected, execution_time, error
        """
        from datetime import datetime

        start_time = datetime.now()

        try:
            db_path = self._parse_sqlite_url(connection_url)

            # Connect with manual transaction control (isolation_level=None for autocommit off)
            # We'll manage transactions explicitly
            conn = sqlite3.connect(
                db_path,
                timeout=timeout,
                check_same_thread=False,
                isolation_level=None,  # Manual transaction management
            )

            try:
                cursor = conn.cursor()

                # Begin transaction explicitly
                cursor.execute("BEGIN IMMEDIATE")

                try:
                    cursor.execute(sql)
                    rows_affected = cursor.rowcount

                    if rollback:
                        cursor.execute("ROLLBACK")
                        logger.info(
                            f"SQLite DML sandbox: {rows_affected} rows (rolled back)"
                        )
                    else:
                        cursor.execute("COMMIT")
                        logger.info(f"SQLite DML executed: {rows_affected} rows")

                    execution_time = (datetime.now() - start_time).total_seconds()

                    return {
                        "success": True,
                        "rows_affected": rows_affected,
                        "execution_time": execution_time,
                        "error": None,
                    }

                except Exception:
                    cursor.execute("ROLLBACK")
                    raise

            finally:
                conn.close()

        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"SQLite DML error ({error_type}): {e}")
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": f"DML execution failed: {str(e)}",
            }
