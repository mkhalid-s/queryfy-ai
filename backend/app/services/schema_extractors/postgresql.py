"""
QueryfyAI - PostgreSQL Schema Extractor

PostgreSQL-specific implementation of schema extraction.
Uses ConnectionPoolManager for efficient connection reuse.
OPTIMIZED: Uses batch queries to avoid N+1 query problem.
"""

import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager

from .base import SchemaExtractor

logger = logging.getLogger(__name__)


class PostgreSQLSchemaExtractor(SchemaExtractor):
    """PostgreSQL schema extractor using asyncpg."""

    DB_TYPE = "postgresql"
    SYSTEM_SCHEMAS = ["pg_catalog", "information_schema", "pg_toast"]

    @asynccontextmanager
    async def _get_connection(self, connection_url: str):
        """Get PostgreSQL connection from pool manager."""
        config = DatabaseConfig(db_type="postgresql", connection_url=connection_url)
        async with pool_manager.get_connection(config) as conn:
            yield conn

    async def _get_tables(self, conn) -> List[tuple]:
        """Get all user tables."""
        query = """
            SELECT table_name, table_schema
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
        """
        rows = await conn.fetch(query)
        return [(row["table_name"], row["table_schema"]) for row in rows]

    async def _get_columns(self, conn, table: str, schema: str) -> List[Dict[str, Any]]:
        """Get columns for a table including comments/descriptions."""
        # Query columns with comments from pg_description
        query = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                pgd.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_catalog.pg_statio_all_tables st
                ON c.table_schema = st.schemaname AND c.table_name = st.relname
            LEFT JOIN pg_catalog.pg_description pgd
                ON pgd.objoid = st.relid
                AND pgd.objsubid = c.ordinal_position
            WHERE c.table_name = $1 AND c.table_schema = $2
            ORDER BY c.ordinal_position
        """
        rows = await conn.fetch(query, table, schema)

        columns = []
        for row in rows:
            col_type = row["data_type"]

            # Add length/precision info for relevant types
            if row["character_maximum_length"]:
                col_type += f"({row['character_maximum_length']})"
            elif row["numeric_precision"] and row["data_type"] in (
                "numeric",
                "decimal",
            ):
                col_type += f"({row['numeric_precision']},{row['numeric_scale'] or 0})"

            col_dict = {
                "name": row["column_name"],
                "type": col_type,
                "nullable": row["is_nullable"] == "YES",
                "default": (
                    str(row["column_default"])[:100] if row["column_default"] else None
                ),
            }

            # Include comment if available (valuable for LLM understanding)
            if row["column_comment"]:
                col_dict["comment"] = row["column_comment"][:500]

            columns.append(col_dict)

        # Sample distinct values for low-cardinality string columns
        # This helps LLM generate correct case/spelling for WHERE clauses
        # SECURITY: Uses identifier quoting to prevent SQL injection
        skip_patterns = [
            "password",
            "token",
            "secret",
            "email",
            "ssn",
            "phone",
            "address",
            "key",
            "hash",
        ]
        for col in columns:
            col_type = col["type"].lower()
            col_name = col["name"]

            # Only varchar/text/char columns
            if not any(t in col_type for t in ["char", "text"]):
                continue

            # Skip potentially sensitive columns
            if any(p in col_name.lower() for p in skip_patterns):
                continue

            try:
                # SECURITY: Use identifier quoting to prevent SQL injection
                quoted_col = self._quote_identifier(col_name)
                quoted_schema = self._quote_identifier(schema)
                quoted_table = self._quote_identifier(table)

                query = f"""
                    SELECT DISTINCT {quoted_col}
                    FROM {quoted_schema}.{quoted_table}
                    WHERE {quoted_col} IS NOT NULL
                    LIMIT 25
                """
                rows = await conn.fetch(query)
                # Only keep if genuinely low-cardinality (e.g., status, type, category)
                if 1 < len(rows) <= 20:
                    col["sample_values"] = [r[col_name] for r in rows]
            except Exception:
                pass  # Silently skip on any error

        return columns

    async def _get_primary_keys(self, conn, table: str, schema: str) -> List[str]:
        """Get primary key columns."""
        query = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = $1 AND n.nspname = $2 AND i.indisprimary
        """
        rows = await conn.fetch(query, table, schema)
        return [row["attname"] for row in rows]

    async def _get_foreign_keys(
        self, conn, table: str, schema: str
    ) -> List[Dict[str, Any]]:
        """Get foreign key constraints."""
        query = """
            SELECT
                kcu.column_name,
                ccu.table_schema AS foreign_schema,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.table_name = $1 AND tc.table_schema = $2
            AND tc.constraint_type = 'FOREIGN KEY'
        """
        rows = await conn.fetch(query, table, schema)

        return [
            {
                "column": row["column_name"],
                "references_schema": row["foreign_schema"],
                "references_table": row["foreign_table"],
                "references_column": row["foreign_column"],
            }
            for row in rows
        ]

    async def _get_views(self, conn) -> List[Dict[str, Any]]:
        """Get all views."""
        query = """
            SELECT table_name, table_schema
            FROM information_schema.views
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        """
        rows = await conn.fetch(query)
        return [
            {"name": row["table_name"], "schema": row["table_schema"]} for row in rows
        ]

    async def _get_row_count_estimate(
        self, conn, table: str, schema: str
    ) -> Optional[int]:
        """Get estimated row count from statistics."""
        query = """
            SELECT reltuples::bigint AS estimate
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = $1 AND n.nspname = $2
        """
        row = await conn.fetchrow(query, table, schema)
        return int(row["estimate"]) if row and row["estimate"] >= 0 else None

    # =========================================================================
    # BATCH QUERY METHODS - Optimize N+1 queries
    # =========================================================================

    async def _get_all_columns_batch(self, conn) -> Dict[tuple[str, str], List[Dict[str, Any]]]:
        """
        Get columns for ALL tables in a single query.
        Returns: Dict mapping (schema, table) -> list of columns
        """
        query = """
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.ordinal_position,
                pgd.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_catalog.pg_statio_all_tables st
                ON c.table_schema = st.schemaname AND c.table_name = st.relname
            LEFT JOIN pg_catalog.pg_description pgd
                ON pgd.objoid = st.relid
                AND pgd.objsubid = c.ordinal_position
            WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
        rows = await conn.fetch(query)

        # Group by table
        columns_by_table: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

        for row in rows:
            col_type = row["data_type"]

            # Add length/precision info
            if row["character_maximum_length"]:
                col_type += f"({row['character_maximum_length']})"
            elif row["numeric_precision"] and row["data_type"] in (
                "numeric",
                "decimal",
            ):
                col_type += f"({row['numeric_precision']},{row['numeric_scale'] or 0})"

            col_dict = {
                "name": row["column_name"],
                "type": col_type,
                "nullable": row["is_nullable"] == "YES",
                "default": (
                    str(row["column_default"])[:100] if row["column_default"] else None
                ),
            }

            if row["column_comment"]:
                col_dict["comment"] = row["column_comment"][:500]

            key = (row["table_schema"], row["table_name"])
            columns_by_table[key].append(col_dict)

        return columns_by_table

    async def _get_all_primary_keys_batch(self, conn) -> Dict[tuple[str, str], List[str]]:
        """
        Get primary keys for ALL tables in a single query.
        Returns: Dict mapping (schema, table) -> list of PK column names
        """
        query = """
            SELECT
                n.nspname AS table_schema,
                c.relname AS table_name,
                a.attname AS column_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE i.indisprimary
            AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY n.nspname, c.relname
        """
        rows = await conn.fetch(query)

        pks_by_table: Dict[tuple[str, str], List[str]] = defaultdict(list)
        for row in rows:
            key = (row["table_schema"], row["table_name"])
            pks_by_table[key].append(row["column_name"])

        return pks_by_table

    async def _get_all_foreign_keys_batch(
        self, conn
    ) -> Dict[tuple[str, str], List[Dict[str, Any]]]:
        """
        Get foreign keys for ALL tables in a single query.
        Returns: Dict mapping (schema, table) -> list of FK dicts
        """
        query = """
            SELECT
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                ccu.table_schema AS foreign_schema,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY tc.table_schema, tc.table_name
        """
        rows = await conn.fetch(query)

        fks_by_table: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = (row["table_schema"], row["table_name"])
            fks_by_table[key].append(
                {
                    "column": row["column_name"],
                    "references_schema": row["foreign_schema"],
                    "references_table": row["foreign_table"],
                    "references_column": row["foreign_column"],
                }
            )

        return fks_by_table

    async def _get_all_row_counts_batch(self, conn) -> Dict[tuple[str, str], Optional[int]]:
        """
        Get estimated row counts for ALL tables in a single query.
        Returns: Dict mapping (schema, table) -> estimated row count
        """
        query = """
            SELECT
                n.nspname AS table_schema,
                c.relname AS table_name,
                c.reltuples::bigint AS estimate
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
            AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        """
        rows = await conn.fetch(query)

        counts_by_table: Dict[tuple[str, str], Optional[int]] = {}
        for row in rows:
            key = (row["table_schema"], row["table_name"])
            estimate = row["estimate"]
            counts_by_table[key] = int(estimate) if estimate >= 0 else None

        return counts_by_table

    def _quote_identifier(self, identifier: str) -> str:
        """
        Safely quote a PostgreSQL identifier to prevent SQL injection.
        Doubles any internal quotes and wraps in quotes.
        """
        # Replace any existing double quotes with escaped double quotes
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'

    async def _sample_values_batch(
        self, conn, columns_by_table: Dict[tuple[str, str], List[Dict[str, Any]]]
    ) -> None:
        """
        Sample column values for low-cardinality string columns.
        Modifies columns_by_table in place.
        Limited to avoid overwhelming the database.
        SECURITY: Uses identifier quoting to prevent SQL injection.
        """
        skip_patterns = [
            "password",
            "token",
            "secret",
            "email",
            "ssn",
            "phone",
            "address",
            "key",
            "hash",
        ]
        max_tables_to_sample = 50  # Limit sampling to avoid long extraction times

        tables_sampled = 0
        for key, columns in columns_by_table.items():
            schema, table = key
            if tables_sampled >= max_tables_to_sample:
                break

            for col in columns:
                col_type = col["type"].lower()
                col_name = col["name"]

                # Only varchar/text/char columns
                if not any(t in col_type for t in ["char", "text"]):
                    continue

                # Skip sensitive columns
                if any(p in col_name.lower() for p in skip_patterns):
                    continue

                try:
                    # SECURITY: Use identifier quoting to prevent SQL injection
                    quoted_col = self._quote_identifier(col_name)
                    quoted_schema = self._quote_identifier(schema)
                    quoted_table = self._quote_identifier(table)

                    query = f"""
                        SELECT DISTINCT {quoted_col}
                        FROM {quoted_schema}.{quoted_table}
                        WHERE {quoted_col} IS NOT NULL
                        LIMIT 25
                    """
                    rows = await conn.fetch(query)
                    # Only keep if low-cardinality
                    if 1 < len(rows) <= 20:
                        col["sample_values"] = [r[col_name] for r in rows]
                except Exception:
                    pass  # Skip on error

            tables_sampled += 1

    async def extract(self, connection_url: str) -> Dict[str, Any]:
        """
        Optimized schema extraction using batch queries.
        Reduces O(4N) queries to O(4) queries + optional sampling.
        """
        schema: Dict[str, Any] = {
            "db_type": self.DB_TYPE,
            "tables": [],
            "views": [],
            "collections": [],
            "extracted_at": None,
        }

        try:
            logger.info(
                f"Extracting schema for {self.DB_TYPE} (optimized batch mode)..."
            )

            async with self._get_connection(connection_url) as conn:
                # Step 1: Get all tables
                tables = await self._get_tables(conn)
                logger.info(f"Found {len(tables)} tables")

                # Step 2: Batch fetch all metadata (4 queries instead of 4N)
                columns_by_table = await self._get_all_columns_batch(conn)
                pks_by_table = await self._get_all_primary_keys_batch(conn)
                fks_by_table = await self._get_all_foreign_keys_batch(conn)
                counts_by_table = await self._get_all_row_counts_batch(conn)

                logger.info("Batch metadata fetched, assembling tables...")

                # Step 3: Sample values for low-cardinality columns (optional)
                try:
                    await self._sample_values_batch(conn, columns_by_table)
                except Exception as e:
                    logger.debug(f"Sample values extraction skipped: {e}")

                # Step 4: Assemble table info from batch results
                for table_name, table_schema in tables:
                    key = (table_schema, table_name)

                    table_info = {
                        "name": table_name,
                        "schema": table_schema,
                        "columns": columns_by_table.get(key, []),
                        "primary_keys": pks_by_table.get(key, []),
                        "foreign_keys": fks_by_table.get(key, []),
                        "row_count_estimate": counts_by_table.get(key),
                    }

                    schema["tables"].append(table_info)

                # Step 5: Get views
                try:
                    schema["views"] = await self._get_views(conn)
                    logger.info(f"Found {len(schema['views'])} views")
                except Exception as e:
                    logger.debug(f"Failed to get views: {e}")

            schema["extracted_at"] = datetime.now().isoformat()
            logger.info(
                f"Schema extraction complete: {len(schema['tables'])} tables, "
                f"{len(schema.get('views', []))} views"
            )

            return schema

        except Exception as e:
            logger.error(f"Schema extraction failed: {e}")
            return {
                "db_type": self.DB_TYPE,
                "tables": [],
                "views": [],
                "collections": [],
                "error": str(e),
                "extracted_at": datetime.now().isoformat(),
            }
