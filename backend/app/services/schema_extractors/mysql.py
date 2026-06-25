"""
QueryfyAI - MySQL Schema Extractor

MySQL-specific implementation of schema extraction.
Uses ConnectionPoolManager for efficient connection reuse.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager

from .base import SchemaExtractor

logger = logging.getLogger(__name__)


class MySQLSchemaExtractor(SchemaExtractor):
    """MySQL schema extractor using aiomysql."""

    DB_TYPE = "mysql"
    SYSTEM_SCHEMAS = ["information_schema", "mysql", "performance_schema", "sys"]

    def _parse_connection_url(self, url: str) -> Dict[str, Any]:
        """Parse MySQL connection URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username or "root",
            "password": parsed.password or "",
            "db": parsed.path.lstrip("/") if parsed.path else "",
        }

    @asynccontextmanager
    async def _get_connection(self, connection_url: str):
        """Get MySQL connection from pool manager."""
        config = DatabaseConfig(db_type="mysql", connection_url=connection_url)
        async with pool_manager.get_connection(config) as conn:
            yield conn

    async def _get_tables(self, conn) -> List[tuple]:
        """Get all user tables."""
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT table_name, table_schema
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            """
            )
            rows = await cursor.fetchall()
            return [(row[0], row[1]) for row in rows]

    async def _get_columns(self, conn, table: str, schema: str) -> List[Dict[str, Any]]:
        """Get columns for a table including comments/descriptions."""
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    column_name,
                    column_type,
                    is_nullable,
                    column_default,
                    column_comment
                FROM information_schema.columns
                WHERE table_name = %s AND table_schema = %s
                ORDER BY ordinal_position
            """,
                (table, schema),
            )
            rows = await cursor.fetchall()

            columns = []
            for row in rows:
                col_dict = {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "default": str(row[3])[:100] if row[3] else None,
                }
                # Include comment if available (valuable for LLM understanding)
                if row[4]:
                    col_dict["comment"] = row[4][:500]
                columns.append(col_dict)

            return columns

    async def _get_primary_keys(self, conn, table: str, schema: str) -> List[str]:
        """Get primary key columns."""
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT column_name
                FROM information_schema.key_column_usage
                WHERE table_name = %s AND table_schema = %s
                AND constraint_name = 'PRIMARY'
                ORDER BY ordinal_position
            """,
                (table, schema),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def _get_foreign_keys(
        self, conn, table: str, schema: str
    ) -> List[Dict[str, Any]]:
        """Get foreign key constraints."""
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    kcu.column_name,
                    kcu.referenced_table_schema,
                    kcu.referenced_table_name,
                    kcu.referenced_column_name
                FROM information_schema.key_column_usage kcu
                WHERE kcu.table_name = %s AND kcu.table_schema = %s
                AND kcu.referenced_table_name IS NOT NULL
            """,
                (table, schema),
            )
            rows = await cursor.fetchall()

            return [
                {
                    "column": row[0],
                    "references_schema": row[1],
                    "references_table": row[2],
                    "references_column": row[3],
                }
                for row in rows
            ]

    async def _get_views(self, conn) -> List[Dict[str, Any]]:
        """Get all views."""
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT table_name, table_schema
                FROM information_schema.views
                WHERE table_schema NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            """
            )
            rows = await cursor.fetchall()
            return [{"name": row[0], "schema": row[1]} for row in rows]

    async def _get_row_count_estimate(
        self, conn, table: str, schema: str
    ) -> Optional[int]:
        """Get estimated row count."""
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT table_rows
                FROM information_schema.tables
                WHERE table_name = %s AND table_schema = %s
            """,
                (table, schema),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row and row[0] else None
