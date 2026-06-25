"""
QueryfyAI Benchmarks - Query Executor

Executes queries against benchmark databases using the existing backend
executor registry.  Implements the ``QueryExecutor`` protocol defined in
``core.runner``.

Supports multi-dialect execution:
- SQLite (lightweight fallback, no backend needed)
- PostgreSQL, MySQL, MongoDB via backend executor registry
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Ensure the backend package is importable
_backend_root = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _backend_root not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_root))

# Map connection URL schemes to backend executor db_type names
_URL_SCHEME_TO_DB_TYPE = {
    "sqlite": "sqlite",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mysql": "mysql",
    "mongodb": "mongodb",
    "cassandra": "cassandra",
    "dynamodb": "dynamodb",
}


def _infer_db_type(url: str) -> str:
    """Infer database type from a connection URL scheme."""
    scheme = url.split("://")[0].split("+")[0].lower() if "://" in url else ""
    return _URL_SCHEME_TO_DB_TYPE.get(scheme, "")


class BenchmarkQueryExecutor:
    """Execute queries against benchmark databases.

    Maintains a mapping of ``{db_name: connection_url}`` and delegates
    to the backend executor registry for each database type.

    Falls back to a lightweight SQLite executor when the backend is
    not available (useful for offline evaluation of BIRD Mini-Dev).

    For cross-dialect benchmarking (e.g. BIRD SQLite → PostgreSQL),
    the executor auto-detects the target database type from the
    connection URL and uses the appropriate backend executor.

    Args:
        connection_map: Maps ``db_name`` to a connection URL string.
        db_type: Default database type for all connections (e.g.
            ``"sqlite"``, ``"postgresql"``).
        timeout: Query execution timeout in seconds.
    """

    def __init__(
        self,
        connection_map: Dict[str, str],
        db_type: str = "sqlite",
        timeout: int = 30,
    ) -> None:
        self.connection_map = connection_map
        self.db_type = db_type
        self.timeout = timeout

    async def execute(
        self,
        query: str,
        db_name: str,
        connection_url: str = "",
    ) -> Any:
        """Execute *query* and return the result dict.

        Uses the connection from ``connection_map[db_name]`` first,
        falling back to *connection_url*.

        The executor detects the database type from the connection URL
        scheme, allowing a single executor instance to route queries to
        different database engines.

        Returns:
            ``{"success": bool, "columns": [...], "rows": [...], ...}``
        """
        url = self.connection_map.get(db_name, connection_url)
        if not url:
            return {"success": False, "rows": [], "columns": [], "error": "no_connection_url"}

        # Detect the actual db_type from the URL (supports cross-dialect)
        effective_db_type = _infer_db_type(url) or self.db_type

        # Try the backend executor first
        try:
            return await self._execute_via_backend(query, url, effective_db_type)
        except ImportError:
            pass

        # Fallback: direct SQLite execution
        if effective_db_type == "sqlite" or url.startswith("sqlite"):
            return self._execute_sqlite(query, url)

        return {"success": False, "rows": [], "columns": [], "error": "no_executor_available"}

    async def _execute_via_backend(
        self, query: str, url: str, db_type: str
    ) -> Dict[str, Any]:
        """Delegate to the backend executor registry."""
        from app.services.executors import get_executor

        executor = get_executor(db_type)
        return await executor.execute(
            connection_url=url,
            query=query,
            limit=10000,
            timeout=self.timeout,
        )

    def _execute_sqlite(self, query: str, url: str) -> Dict[str, Any]:
        """Lightweight SQLite execution without backend dependency."""
        db_path = url.replace("sqlite:///", "").replace("sqlite://", "")
        try:
            conn = sqlite3.connect(db_path, timeout=self.timeout)
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            conn.close()
            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }
        except Exception as exc:
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "error": str(exc),
            }
