"""
QueryfyAI - Generic SQL Schema Extractor

Fallback schema extractor for SQL databases that use information_schema.
Works with most SQL databases that follow the SQL standard.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager

from .base import SchemaExtractor

logger = logging.getLogger(__name__)


class GenericSQLSchemaExtractor(SchemaExtractor):
    """
    Generic SQL schema extractor using information_schema.

    This is a fallback extractor for databases that don't have
    a specialized extractor. It uses standard SQL queries against
    information_schema which is supported by most SQL databases.

    Supported features:
    - Table listing from information_schema.tables
    - Column metadata from information_schema.columns
    - Primary key detection (where supported)
    """

    # Common system schemas to exclude
    SYSTEM_SCHEMAS = [
        "information_schema",
        "pg_catalog",
        "pg_toast",
        "mysql",
        "performance_schema",
        "sys",
        "INFORMATION_SCHEMA",
    ]

    def __init__(self, db_type: str = "generic"):
        """Initialize with specific database type."""
        self.db_type = db_type
        self.DB_TYPE = (
            db_type  # Set class attribute for base class _initialize_schema()
        )
        self._connection_url = None  # Store for use in _get_connection

    @asynccontextmanager
    async def _get_connection(self, connection_url: str):
        """
        Get database connection using the pool manager.
        Implements abstract method from SchemaExtractor.
        """
        config = DatabaseConfig(db_type=self.db_type, connection_url=connection_url)  # type: ignore[arg-type]
        async with pool_manager.get_connection(config) as conn:
            yield conn

    async def extract(self, connection_url: str) -> Dict[str, Any]:
        """
        Extract schema using standard information_schema queries.

        This method attempts to extract schema information using
        SQL standard queries. If specific queries fail, it gracefully
        degrades to return partial schema information.

        Special handling for SQLite which uses sqlite_master instead.
        """
        schema = self._initialize_schema()

        try:
            config = DatabaseConfig(db_type=self.db_type, connection_url=connection_url)  # type: ignore[arg-type]

            async with pool_manager.get_connection(config) as conn:
                # SQLite uses different schema queries
                if self.db_type == "sqlite":
                    tables = await self._get_tables_sqlite(conn)
                else:
                    tables = await self._get_tables(conn)

                for table_name, table_schema in tables:
                    if self.db_type == "sqlite":
                        table_info = {
                            "name": table_name,
                            "schema": table_schema,
                            "columns": await self._get_columns_sqlite(conn, table_name),
                            "primary_keys": await self._get_primary_keys_sqlite(
                                conn, table_name
                            ),
                        }
                    else:
                        table_info = {
                            "name": table_name,
                            "schema": table_schema,
                            "columns": await self._get_columns(
                                conn, table_name, table_schema
                            ),
                            "primary_keys": await self._safe_get_primary_keys(
                                conn, table_name, table_schema
                            ),
                        }
                    schema["tables"].append(table_info)

                # Try to get views
                if self.db_type == "sqlite":
                    schema["views"] = await self._get_views_sqlite(conn)
                else:
                    schema["views"] = await self._safe_get_views(conn)

        except Exception as e:
            logger.error(f"Schema extraction error for {self.db_type}: {e}")
            schema["error"] = str(e)
            schema["partial"] = True

        return schema

    async def _get_tables(self, conn) -> List[tuple]:
        """Get tables from information_schema."""
        # Build exclusion list for system schemas
        schema_placeholders = ", ".join([f"'{s}'" for s in self.SYSTEM_SCHEMAS])

        query = f"""
            SELECT table_name, table_schema
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
            AND table_schema NOT IN ({schema_placeholders})
            ORDER BY table_schema, table_name
            LIMIT 500
        """

        try:
            result = await self._execute_query(conn, query)
            return [(row[0], row[1]) for row in result]
        except Exception as e:
            logger.warning(f"Failed to get tables: {e}")
            return []

    async def _get_columns(self, conn, table: str, schema: str) -> List[Dict]:
        """Get columns from information_schema."""
        # Escape single quotes in identifiers to prevent SQL injection
        safe_table = table.replace("'", "''")
        safe_schema = schema.replace("'", "''")
        query = f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = '{safe_table}'
            AND table_schema = '{safe_schema}'
            ORDER BY ordinal_position
        """

        try:
            result = await self._execute_query(conn, query)
            return [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "default": row[3],
                }
                for row in result
            ]
        except Exception as e:
            logger.warning(f"Failed to get columns for {schema}.{table}: {e}")
            return []

    async def _safe_get_primary_keys(self, conn, table: str, schema: str) -> List[str]:
        """Try to get primary keys, return empty list on failure."""
        try:
            return await self._get_primary_keys(conn, table, schema)
        except Exception as e:
            logger.debug(f"Primary key query not supported: {e}")
            return []

    async def _get_primary_keys(self, conn, table: str, schema: str) -> List[str]:
        """Get primary keys from information_schema."""
        # Escape single quotes in identifiers to prevent SQL injection
        safe_table = table.replace("'", "''")
        safe_schema = schema.replace("'", "''")
        query = f"""
            SELECT column_name
            FROM information_schema.key_column_usage
            WHERE table_name = '{safe_table}'
            AND table_schema = '{safe_schema}'
            AND (constraint_name LIKE '%pkey%' OR constraint_name LIKE '%PRIMARY%')
        """

        result = await self._execute_query(conn, query)
        return [row[0] for row in result]

    async def _safe_get_views(self, conn) -> List[Dict]:
        """Try to get views, return empty list on failure."""
        try:
            return await self._get_views(conn)
        except Exception as e:
            logger.debug(f"View query not supported: {e}")
            return []

    async def _get_views(self, conn) -> List[Dict]:
        """Get views from information_schema."""
        schema_placeholders = ", ".join([f"'{s}'" for s in self.SYSTEM_SCHEMAS])

        query = f"""
            SELECT table_name, table_schema
            FROM information_schema.views
            WHERE table_schema NOT IN ({schema_placeholders})
            LIMIT 100
        """

        result = await self._execute_query(conn, query)
        return [{"name": row[0], "schema": row[1]} for row in result]

    async def _execute_query(self, conn, query: str) -> List[tuple]:
        """Execute query and return results as list of tuples."""
        import asyncio

        # Handle both async and sync connections
        if hasattr(conn, "fetch"):
            # Async connection (asyncpg)
            rows = await conn.fetch(query)
            return [tuple(row.values()) for row in rows]
        elif hasattr(conn, "cursor"):
            # Check if cursor is async
            cursor = conn.cursor()
            if asyncio.iscoroutinefunction(cursor.execute):
                # Async cursor (aiomysql)
                async with conn.cursor() as cur:
                    await cur.execute(query)
                    return await cur.fetchall()
            else:
                # Sync cursor - run in thread
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None, lambda: self._execute_sync(conn, query)
                )
        else:
            raise ValueError("Unknown connection type")

    def _execute_sync(self, conn, query: str) -> List[tuple]:
        """Execute sync query."""
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            return cursor.fetchall()
        finally:
            cursor.close()

    # ===========================================
    # SQLite-specific methods
    # ===========================================

    async def _get_tables_sqlite(self, conn) -> List[tuple]:
        """Get tables from SQLite using sqlite_master."""
        query = """
            SELECT name, 'main' as schema
            FROM sqlite_master
            WHERE type = 'table'
            AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            LIMIT 500
        """
        try:
            result = await self._execute_query(conn, query)
            return [(row[0], row[1]) for row in result]
        except Exception as e:
            logger.warning(f"Failed to get SQLite tables: {e}")
            return []

    async def _get_columns_sqlite(self, conn, table: str) -> List[Dict]:
        """Get columns from SQLite using PRAGMA table_info."""
        # Sanitize table name - escape double quotes for SQLite identifier
        safe_table = table.replace('"', '""')
        query = f'PRAGMA table_info("{safe_table}")'
        try:
            result = await self._execute_query(conn, query)
            # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
            return [
                {
                    "name": row[1],
                    "type": row[2] or "TEXT",
                    "nullable": not bool(row[3]),
                    "default": row[4],
                    "primary_key": bool(row[5]),
                }
                for row in result
            ]
        except Exception as e:
            logger.warning(f"Failed to get SQLite columns for {table}: {e}")
            return []

    async def _get_primary_keys_sqlite(self, conn, table: str) -> List[str]:
        """Get primary keys from SQLite using PRAGMA table_info."""
        # Sanitize table name - escape double quotes for SQLite identifier
        safe_table = table.replace('"', '""')
        query = f'PRAGMA table_info("{safe_table}")'
        try:
            result = await self._execute_query(conn, query)
            # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
            return [row[1] for row in result if row[5]]  # pk column is index 5
        except Exception as e:
            logger.debug(f"Failed to get SQLite primary keys for {table}: {e}")
            return []

    async def _get_views_sqlite(self, conn) -> List[Dict]:
        """Get views from SQLite using sqlite_master."""
        query = """
            SELECT name, 'main' as schema
            FROM sqlite_master
            WHERE type = 'view'
            AND name NOT LIKE 'sqlite_%'
            LIMIT 100
        """
        try:
            result = await self._execute_query(conn, query)
            return [{"name": row[0], "schema": row[1]} for row in result]
        except Exception as e:
            logger.debug(f"Failed to get SQLite views: {e}")
            return []
