"""
QueryfyAI - Cassandra Schema Extractor

Cassandra-specific implementation of schema extraction.
Uses CQL to query system_schema tables for keyspace and table metadata.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from .base import SchemaExtractor
from .sensitive_field_mixin import SensitiveFieldMixin

logger = logging.getLogger(__name__)


class CassandraSchemaExtractor(SchemaExtractor, SensitiveFieldMixin):
    """
    Cassandra schema extractor using cassandra-driver.

    Extracts:
    - Keyspaces (equivalent to schemas)
    - Tables with columns
    - Partition keys and clustering keys
    - Secondary indexes
    - Materialized views
    """

    DB_TYPE = "cassandra"
    SYSTEM_KEYSPACES = [
        "system",
        "system_auth",
        "system_distributed",
        "system_schema",
        "system_traces",
        "system_views",
        "system_virtual_schema",
    ]

    def _parse_connection_url(self, url: str) -> Dict[str, Any]:
        """
        Parse Cassandra connection URL.

        Format: cassandra://user:pass@host:port/keyspace
        """
        from urllib.parse import unquote, urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 9042,
            "username": unquote(parsed.username) if parsed.username else None,
            "password": unquote(parsed.password) if parsed.password else None,
            "keyspace": parsed.path.lstrip("/") if parsed.path else None,
        }

    @asynccontextmanager
    async def _get_connection(self, connection_url: str):
        """
        Get Cassandra session.

        Note: cassandra-driver is synchronous, so we run it in a thread executor.
        """
        loop = asyncio.get_event_loop()
        session = await loop.run_in_executor(None, self._create_session, connection_url)
        try:
            yield session
        finally:
            await loop.run_in_executor(None, self._close_session, session)

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

        # Store cluster reference for cleanup
        session._cluster_ref = cluster

        # Set default keyspace if provided
        if params["keyspace"]:
            session.set_keyspace(params["keyspace"])

        logger.info(f"Connected to Cassandra: {params['host']}:{params['port']}")
        return session

    def _close_session(self, session):
        """Close Cassandra session and cluster."""
        try:
            if hasattr(session, "_cluster_ref"):
                session._cluster_ref.shutdown()
        except Exception as e:
            logger.warning(f"Error closing Cassandra session: {e}")

    async def _get_tables(self, session) -> List[tuple]:
        """
        Get all user tables from all non-system keyspaces.

        Returns:
            List of (table_name, keyspace_name) tuples
        """
        loop = asyncio.get_event_loop()

        def _fetch_tables():
            # Get all keyspaces
            keyspace_query = """
                SELECT keyspace_name
                FROM system_schema.keyspaces
            """
            keyspace_rows = session.execute(keyspace_query)

            tables = []
            for ks_row in keyspace_rows:
                keyspace = ks_row.keyspace_name
                if keyspace in self.SYSTEM_KEYSPACES:
                    continue

                # Get tables in this keyspace
                table_query = """
                    SELECT table_name
                    FROM system_schema.tables
                    WHERE keyspace_name = %s
                """
                table_rows = session.execute(table_query, [keyspace])

                for t_row in table_rows:
                    tables.append((t_row.table_name, keyspace))

            return tables

        return await loop.run_in_executor(None, _fetch_tables)

    async def _get_columns(
        self, session, table: str, keyspace: str
    ) -> List[Dict[str, Any]]:
        """
        Get columns for a table including partition/clustering key info.

        The 'kind' column indicates:
        - 'partition_key': Part of the partition key
        - 'clustering': Clustering column
        - 'regular': Regular column
        - 'static': Static column
        """
        loop = asyncio.get_event_loop()

        def _fetch_columns():
            query = """
                SELECT
                    column_name,
                    type,
                    kind,
                    position
                FROM system_schema.columns
                WHERE keyspace_name = %s AND table_name = %s
            """
            rows = session.execute(query, [keyspace, table])

            columns = []
            for row in rows:
                col_dict = {
                    "name": row.column_name,
                    "type": row.type,
                    "nullable": row.kind not in ("partition_key", "clustering"),
                    "key_type": row.kind,  # partition_key, clustering, regular, static
                    "position": row.position,
                }

                # Add comment for key columns (helpful for LLM)
                if row.kind == "partition_key":
                    col_dict["comment"] = "PARTITION KEY - Required in WHERE clause"
                elif row.kind == "clustering":
                    col_dict["comment"] = (
                        f"CLUSTERING KEY (position {row.position}) - Determines sort order"
                    )
                elif row.kind == "static":
                    col_dict["comment"] = "STATIC - Shared across all rows in partition"

                columns.append(col_dict)

            # Sort: partition keys first, then clustering, then regular
            key_order = {"partition_key": 0, "clustering": 1, "static": 2, "regular": 3}
            columns.sort(
                key=lambda c: (key_order.get(c["key_type"], 4), c.get("position", 0))
            )

            return columns

        return await loop.run_in_executor(None, _fetch_columns)

    async def _get_primary_keys(self, session, table: str, keyspace: str) -> List[str]:
        """
        Get primary key columns (partition + clustering keys).
        """
        loop = asyncio.get_event_loop()

        def _fetch_pks():
            query = """
                SELECT column_name, kind, position
                FROM system_schema.columns
                WHERE keyspace_name = %s AND table_name = %s
                AND kind IN ('partition_key', 'clustering')
            """
            rows = session.execute(query, [keyspace, table])

            # Separate partition and clustering keys
            partition_keys = []
            clustering_keys = []

            for row in rows:
                if row.kind == "partition_key":
                    partition_keys.append((row.position, row.column_name))
                else:
                    clustering_keys.append((row.position, row.column_name))

            # Sort by position and combine
            partition_keys.sort()
            clustering_keys.sort()

            return [col for _, col in partition_keys] + [
                col for _, col in clustering_keys
            ]

        return await loop.run_in_executor(None, _fetch_pks)

    async def _get_foreign_keys(
        self, session, table: str, keyspace: str
    ) -> List[Dict[str, Any]]:
        """
        Cassandra doesn't have foreign keys (denormalized data model).
        """
        return []

    async def _get_views(self, session) -> List[Dict[str, Any]]:
        """
        Get materialized views.
        """
        loop = asyncio.get_event_loop()

        def _fetch_views():
            views = []

            # Get keyspaces first
            keyspace_rows = session.execute(
                "SELECT keyspace_name FROM system_schema.keyspaces"
            )

            for ks_row in keyspace_rows:
                keyspace = ks_row.keyspace_name
                if keyspace in self.SYSTEM_KEYSPACES:
                    continue

                # Get views in this keyspace
                try:
                    view_query = """
                        SELECT view_name, base_table_name
                        FROM system_schema.views
                        WHERE keyspace_name = %s
                    """
                    view_rows = session.execute(view_query, [keyspace])

                    for v_row in view_rows:
                        views.append(
                            {
                                "name": v_row.view_name,
                                "schema": keyspace,
                                "base_table": v_row.base_table_name,
                            }
                        )
                except Exception as e:
                    logger.debug(f"Could not get views for keyspace {keyspace}: {e}")

            return views

        return await loop.run_in_executor(None, _fetch_views)

    async def _get_row_count_estimate(
        self, session, table: str, keyspace: str
    ) -> Optional[int]:
        """
        Get estimated row count.

        Note: Cassandra doesn't track exact counts, so we sample.
        """
        loop = asyncio.get_event_loop()

        def _estimate_count():
            try:
                # Count with limit to estimate
                query = f"SELECT COUNT(*) FROM {keyspace}.{table} LIMIT 10000"
                row = session.execute(query).one()
                return row.count if row else None
            except Exception as e:
                logger.debug(
                    f"Could not estimate row count for {keyspace}.{table}: {e}"
                )
                return None

        return await loop.run_in_executor(None, _estimate_count)

    async def _get_indexes(
        self, session, table: str, keyspace: str
    ) -> List[Dict[str, Any]]:
        """
        Get secondary indexes for a table.
        """
        loop = asyncio.get_event_loop()

        def _fetch_indexes():
            query = """
                SELECT index_name, kind, options
                FROM system_schema.indexes
                WHERE keyspace_name = %s AND table_name = %s
            """
            rows = session.execute(query, [keyspace, table])

            indexes = []
            for row in rows:
                target = row.options.get("target", "") if row.options else ""
                indexes.append(
                    {
                        "name": row.index_name,
                        "type": row.kind,
                        "target": target,
                    }
                )

            return indexes

        return await loop.run_in_executor(None, _fetch_indexes)

    async def _sample_column_values(
        self,
        session,
        table: str,
        keyspace: str,
        columns: List[Dict[str, Any]],
    ) -> None:
        """
        Sample distinct values for low-cardinality text columns.

        Modifies columns in place to add sample_values.
        Uses base class constants for consistency across extractors.

        SECURITY: Skips sensitive fields (password, token, email, etc.)
        NOTE: Uses ALLOW FILTERING which may be slow on large tables.
        """
        loop = asyncio.get_event_loop()

        # Capture instance variables for use in sync function
        max_fields = self.MAX_FIELDS_TO_SAMPLE
        max_distinct = self.MAX_DISTINCT_VALUES
        is_sensitive = self._is_sensitive_field
        is_low_card = self._is_low_cardinality

        def _sample_values():
            # Cassandra text types that support DISTINCT
            text_types = ("text", "varchar", "ascii")

            columns_sampled = 0
            for col in columns:
                if columns_sampled >= max_fields:
                    break

                col_name = col["name"]
                col_type = col["type"].lower()

                # Only sample text columns
                if not any(t in col_type for t in text_types):
                    continue

                # Skip sensitive fields (from SensitiveFieldMixin)
                if is_sensitive(col_name):
                    continue

                # Skip partition/clustering keys (they're already well-known)
                if col.get("key_type") in ("partition_key", "clustering"):
                    continue

                try:
                    # Quote identifier to handle reserved words
                    quoted_col = f'"{col_name}"'
                    # Note: ALLOW FILTERING needed for non-indexed columns
                    query = f"""
                        SELECT DISTINCT {quoted_col}
                        FROM {keyspace}.{table}
                        LIMIT {max_distinct}
                        ALLOW FILTERING
                    """
                    rows = session.execute(query)
                    values = [
                        str(row[0])
                        for row in rows
                        if row[0] is not None and row[0] != ""
                    ]

                    # Only keep if low-cardinality (uses base class method)
                    if is_low_card(values):
                        col["sample_values"] = values
                        columns_sampled += 1

                except Exception as e:
                    logger.debug(f"Could not sample values for {col_name}: {e}")

        await loop.run_in_executor(None, _sample_values)

    async def extract(self, connection_url: str) -> Dict[str, Any]:
        """
        Extract Cassandra schema with additional metadata.

        Extends base extraction to include:
        - Partition key information
        - Clustering key information
        - Secondary indexes
        """
        schema = self._initialize_schema()

        try:
            logger.info(f"Extracting schema for {self.DB_TYPE}...")

            async with self._get_connection(connection_url) as session:
                # Get all tables
                tables = await self._get_tables(session)
                logger.info(f"Found {len(tables)} tables")

                # For each table, extract metadata
                for table_name, keyspace in tables:
                    table_info = {
                        "name": table_name,
                        "schema": keyspace,  # keyspace as schema
                        "columns": [],
                        "primary_keys": [],
                        "partition_keys": [],
                        "clustering_keys": [],
                        "foreign_keys": [],
                        "indexes": [],
                        "row_count_estimate": None,
                    }

                    # Get columns (includes key information)
                    columns = await self._get_columns(session, table_name, keyspace)
                    table_info["columns"] = columns

                    # Sample values for low-cardinality text columns
                    try:
                        await self._sample_column_values(
                            session, table_name, keyspace, columns
                        )
                    except Exception as e:
                        logger.debug(f"Could not sample column values: {e}")

                    # Extract partition and clustering keys from columns
                    table_info["partition_keys"] = [
                        c["name"]
                        for c in columns
                        if c.get("key_type") == "partition_key"
                    ]
                    table_info["clustering_keys"] = [
                        c["name"] for c in columns if c.get("key_type") == "clustering"
                    ]
                    table_info["primary_keys"] = (
                        table_info["partition_keys"] + table_info["clustering_keys"]
                    )

                    # Get secondary indexes
                    try:
                        table_info["indexes"] = await self._get_indexes(
                            session, table_name, keyspace
                        )
                    except Exception as e:
                        logger.debug(f"Failed to get indexes for {table_name}: {e}")

                    # Get row count estimate
                    try:
                        table_info["row_count_estimate"] = (
                            await self._get_row_count_estimate(
                                session, table_name, keyspace
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Failed to get row count for {table_name}: {e}")

                    schema["tables"].append(table_info)

                # Get materialized views
                try:
                    schema["views"] = await self._get_views(session)
                    logger.info(f"Found {len(schema['views'])} materialized views")
                except Exception as e:
                    logger.debug(f"Failed to get views: {e}")

            from datetime import datetime

            schema["extracted_at"] = datetime.now().isoformat()
            logger.info(
                f"Schema extraction complete: {len(schema['tables'])} tables, "
                f"{len(schema.get('views', []))} views"
            )

            return schema

        except Exception as e:
            logger.error(f"Schema extraction failed: {e}")
            from datetime import datetime

            return {
                "db_type": self.DB_TYPE,
                "tables": [],
                "views": [],
                "collections": [],
                "error": str(e),
                "extracted_at": datetime.now().isoformat(),
            }
