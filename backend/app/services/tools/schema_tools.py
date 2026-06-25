"""
QueryfyAI - Schema Tools

Tools for exploring database structure:
- search_tables: Find relevant tables based on a search term
- get_table_schema: Get detailed schema for a specific table

Supports both SQL (PostgreSQL, MySQL) and NoSQL (MongoDB, Cassandra, DynamoDB) databases.
Returns schema-qualified names (e.g., "schema.table" for SQL, "keyspace.table" for Cassandra).
"""

import logging
import re
from typing import Any, Optional

from app.services.security import ErrorSanitizer
from app.services.tools.registry import ToolContext

logger = logging.getLogger(__name__)


def _get_qualified_name(table_name: str, schema: Optional[str], db_type: str) -> str:
    """
    Get the fully qualified table/collection name based on database type.

    - PostgreSQL/MySQL: schema.table (e.g., "public.users", "demoapp.policies")
    - Cassandra: keyspace.table
    - MongoDB: database.collection (schema represents database)
    - DynamoDB: just table name (no schema concept)
    """
    if not schema:
        return table_name

    # Skip for DynamoDB (no schema concept)
    if db_type and 'dynamo' in db_type.lower():
        return table_name

    # For all other databases, use schema.table format
    return f"{schema}.{table_name}"


async def search_tables(
    context: ToolContext,
    query: str,
    max_results: int = 5
) -> str:
    """
    Search for database tables relevant to a query.

    Returns schema-qualified table names (e.g., "schema.table" for PostgreSQL,
    "keyspace.table" for Cassandra) that can be used directly in queries.

    Args:
        context: Tool execution context with connection info
        query: Search term (e.g., 'customer', 'order', 'revenue')
        max_results: Maximum number of tables to return

    Returns:
        Formatted string with matching tables and their qualified names
    """
    from app.services.vector_db import vector_db

    if not context.connection_url:
        return "Error: No database connection. Please connect to a database first."

    # Get db_type from context
    db_type = ""
    if context.db_config:
        db_type = context.db_config.get('db_type', '') if isinstance(context.db_config, dict) else getattr(context.db_config, 'db_type', '')

    try:
        # Get relevant schema from vector DB
        schema_text = vector_db.get_relevant_schema(
            connection_url=context.connection_url,
            query=query,
            max_items=max_results
        )

        if not schema_text or schema_text == "No schema information available":
            return f"No tables found matching '{query}'. Try a different search term or check if the schema has been indexed."

        # Parse the schema text to extract table information
        tables = _parse_schema_text(schema_text)

        if not tables:
            # Fallback: return raw schema text
            return f"Tables matching '{query}':\n\n{schema_text}"

        # Format the output with qualified names
        output_lines = [f"Tables matching '{query}':", ""]
        output_lines.append("IMPORTANT: Use the full qualified name (with schema/keyspace prefix) in your SQL queries.")
        output_lines.append("")

        for table in tables[:max_results]:
            # Get schema-qualified name
            qualified_name = _get_qualified_name(
                table['name'],
                table.get('schema'),
                db_type
            )
            output_lines.append(f"  - {qualified_name}")

            # Show schema info if different from name
            if table.get('schema') and '.' not in table['name']:
                output_lines.append(f"    Schema/Keyspace: {table['schema']}")

            if table.get('columns'):
                output_lines.append(f"    Columns: {', '.join(table['columns'][:8])}")
                if len(table['columns']) > 8:
                    output_lines.append(f"    ... and {len(table['columns']) - 8} more columns")

            # Show key info for NoSQL databases
            if table.get('partition_keys'):
                output_lines.append(f"    Partition Keys: {', '.join(table['partition_keys'])} (REQUIRED in WHERE)")
            if table.get('partition_key'):
                output_lines.append(f"    Partition Key: {table['partition_key']} (REQUIRED)")

            output_lines.append("")

        return "\n".join(output_lines)

    except Exception as e:
        logger.error(f"search_tables error: {e}", exc_info=True)
        return f"Error searching tables: {ErrorSanitizer.sanitize_error(e)}"


async def get_table_schema(
    context: ToolContext,
    table_name: str,
    include_sample_values: bool = False
) -> str:
    """
    Get detailed schema for a specific table.

    Accepts both simple names ("users") and qualified names ("public.users").
    For SQL databases, will try to find the table in available schemas.

    Args:
        context: Tool execution context with connection info
        table_name: Name of the table (can be "table" or "schema.table")
        include_sample_values: Whether to include sample values

    Returns:
        Formatted string with column details and qualified name for queries
    """
    from app.services.vector_db import vector_db

    if not context.connection_url:
        return "Error: No database connection. Please connect to a database first."

    # Get db_type from context
    db_type = ""
    if context.db_config:
        db_type = context.db_config.get('db_type', '') if isinstance(context.db_config, dict) else getattr(context.db_config, 'db_type', '')

    # Parse table name - might be "schema.table" or just "table"
    schema_hint = None
    simple_name = table_name
    if '.' in table_name:
        parts = table_name.split('.', 1)
        schema_hint = parts[0]
        simple_name = parts[1]

    try:
        # Query for tables matching this name
        schema_text = vector_db.get_relevant_schema(
            connection_url=context.connection_url,
            query=f"table {simple_name}",
            max_items=5  # Get more to find the right schema
        )

        if not schema_text or schema_text == "No schema information available":
            return (
                f"Table '{table_name}' not found in the indexed schema.\n\n"
                f"Suggestions:\n"
                f"  1. Use search_tables tool to find available tables\n"
                f"  2. The table might be in a different schema - try 'schema.{simple_name}'\n"
                f"  3. Check if the database schema has been indexed"
            )

        # Parse and find the matching table
        tables = _parse_schema_text(schema_text)
        target_table = None
        alternative_tables = []

        for table in tables:
            table_simple = table['name'].split('.')[-1] if '.' in table['name'] else table['name']

            # Exact match with schema
            if schema_hint and table.get('schema', '').lower() == schema_hint.lower():
                if table_simple.lower() == simple_name.lower():
                    target_table = table
                    break

            # Match by simple name (collect alternatives)
            if table_simple.lower() == simple_name.lower():
                if not target_table:
                    target_table = table
                else:
                    alternative_tables.append(table)

        if not target_table:
            # No match found - provide helpful error
            available = [_get_qualified_name(t['name'], t.get('schema'), db_type) for t in tables[:5]]
            return (
                f"Table '{table_name}' not found.\n\n"
                f"Similar tables found:\n"
                f"  {chr(10).join('  - ' + t for t in available)}\n\n"
                f"Use search_tables to find the correct table name."
            )

        # NoSQL partition-key live-metadata fallback.
        # If the indexed copy of a Cassandra/DynamoDB table is missing
        # partition_keys / partition_key (most often because the
        # original extraction captured an incomplete row), trigger a
        # single-table live refresh, then re-fetch the indexed copy
        # and re-parse. Bounded: one refresh attempt per call. Falls
        # through to the original (empty-keys) data on any failure
        # so the agent still sees something actionable.
        db_type_lower = (db_type or "").lower()
        needs_partition_refresh = (
            db_type_lower in {"cassandra", "dynamodb"}
            and not target_table.get("partition_keys")
            and not target_table.get("partition_key")
        )
        if needs_partition_refresh and context.db_config:
            try:
                from app.models.schemas import DatabaseConfig
                from app.services.schema_refresh import refresh_table_schema

                _db_cfg = (
                    DatabaseConfig(**context.db_config)
                    if isinstance(context.db_config, dict)
                    else context.db_config
                )
                refresh_result = await refresh_table_schema(
                    db_config=_db_cfg,
                    schema_name=target_table.get("schema") or schema_hint,
                    table_name=target_table["name"].split(".")[-1],
                    reason="empty_partition_keys",
                )
                if refresh_result.get("success"):
                    # Re-fetch the indexed copy after the live refresh.
                    schema_text2 = vector_db.get_relevant_schema(
                        connection_url=context.connection_url,
                        query=f"table {simple_name}",
                        max_items=5,
                    )
                    if schema_text2 and schema_text2 != "No schema information available":
                        tables2 = _parse_schema_text(schema_text2)
                        for t2 in tables2:
                            t2_simple = t2["name"].split(".")[-1] if "." in t2["name"] else t2["name"]
                            if t2_simple.lower() == simple_name.lower():
                                target_table = t2
                                break
                        logger.info(
                            "get_table_schema.partition_keys_refreshed",
                            extra={
                                "table": target_table["name"],
                                "db_type": db_type_lower,
                                "now_has_partition_keys": bool(
                                    target_table.get("partition_keys")
                                    or target_table.get("partition_key")
                                ),
                            },
                        )
                else:
                    logger.warning(
                        "get_table_schema.partition_refresh_failed",
                        extra={
                            "table": target_table["name"],
                            "db_type": db_type_lower,
                            "reason": refresh_result.get("reason"),
                            "error": refresh_result.get("error"),
                        },
                    )
            except Exception as e:
                # Never break the tool because the fallback fired.
                # Surface as a warning; tool returns the original
                # (empty-keys) view so the agent at least sees columns.
                logger.warning(
                    "get_table_schema: partition-keys fallback failed: %s", e
                )

        # Build output with qualified name
        qualified_name = _get_qualified_name(
            target_table['name'],
            target_table.get('schema'),
            db_type
        )

        output_lines = [f"Schema for '{qualified_name}':", ""]

        # Show alternative schemas if table exists in multiple schemas
        if alternative_tables:
            alt_names = [_get_qualified_name(t['name'], t.get('schema'), db_type) for t in alternative_tables]
            output_lines.append(f"NOTE: This table also exists in other schemas: {', '.join(alt_names)}")
            output_lines.append("")

        output_lines.append(f"Use this name in queries: {qualified_name}")
        output_lines.append("")
        output_lines.append("Columns:")

        for col in target_table.get('columns', []):
            col_info = f"  - {col}"
            if target_table.get('column_types', {}).get(col):
                col_info += f" ({target_table['column_types'][col]})"
            output_lines.append(col_info)

        if target_table.get('primary_key'):
            output_lines.append(f"\nPrimary Key: {target_table['primary_key']}")

        # NoSQL key info
        if target_table.get('partition_keys'):
            output_lines.append(f"\nPartition Keys (REQUIRED in WHERE): {', '.join(target_table['partition_keys'])}")
        if target_table.get('clustering_keys'):
            output_lines.append(f"Clustering Keys: {', '.join(target_table['clustering_keys'])}")

        if target_table.get('foreign_keys'):
            output_lines.append("\nForeign Keys:")
            for fk in target_table['foreign_keys']:
                output_lines.append(f"  - {fk}")

        # Optionally get sample values
        if include_sample_values:
            from app.services.tools.query_tools import get_sample_data
            sample = await get_sample_data(context, qualified_name, limit=3)
            output_lines.append("\nSample Data:")
            output_lines.append(sample)

        # Track explored table for conversation context
        from app.services.session_store import session_store
        session = session_store.get(context.session_id)
        if session:
            explored = session.get("explored_tables", [])
            if qualified_name not in explored:
                explored.append(qualified_name)
                session_store.update(context.session_id, {"explored_tables": explored})
                logger.debug(
                    f"Added {qualified_name} to explored tables for session {context.session_id[:8]}"
                )

        return "\n".join(output_lines)

    except Exception as e:
        logger.error(f"get_table_schema error: {e}", exc_info=True)
        return f"Error getting schema for '{table_name}': {ErrorSanitizer.sanitize_error(e)}"


def _parse_schema_text(schema_text: str) -> list[dict[str, Any]]:
    """
    Parse schema text from vector_db into structured format.

    The vector_db returns schema in various formats depending on
    how it was indexed. This function attempts to parse common formats.

    Supported formats:
    - SQL: "Table: schema.tablename" or "Table: tablename (schema: schemaname)"
    - Cassandra: "Table: keyspace.tablename"
    - MongoDB: "Collection: database.collectionname"
    - DynamoDB: "Table: tablename"
    """
    tables: list[dict[str, Any]] = []
    current_table: Optional[dict[str, Any]] = None

    lines = schema_text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Look for table definitions
        # Format: "Table: tablename" or "Table: schema.tablename" or "Table: tablename (schema: xxx)"
        # Also handles "Collection:" for MongoDB
        if line.lower().startswith('table:') or line.lower().startswith('table ') or line.lower().startswith('collection:'):
            # Extract name part after the label
            if ':' in line:
                name_part = line.split(':', 1)[-1].strip()
            else:
                name_part = line.split()[1]

            # Check for (schema: xxx) or (keyspace: xxx) or (database: xxx) suffix
            schema_name = None
            schema_match = re.search(r'\((?:schema|keyspace|database):\s*([^\)]+)\)', name_part, re.IGNORECASE)
            if schema_match:
                schema_name = schema_match.group(1).strip()
                # Remove the schema part from name
                name_part = re.sub(r'\s*\((?:schema|keyspace|database):[^\)]+\)', '', name_part).strip()

            table_name = name_part.strip('`"[]')

            # Check if name already contains schema (schema.table format)
            if '.' in table_name and not schema_name:
                parts = table_name.split('.', 1)
                schema_name = parts[0]
                table_name = parts[1]

            if current_table:
                tables.append(current_table)
            current_table = {
                'name': table_name,
                'schema': schema_name,
                'columns': [],
                'column_types': {},
                'foreign_keys': []
            }

        elif 'CREATE TABLE' in line.upper():
            parts = line.split()
            for i, part in enumerate(parts):
                if part.upper() == 'TABLE' and i + 1 < len(parts):
                    full_name = parts[i + 1].strip('`"[]();')
                    # Check for schema.table format
                    schema_name = None
                    table_name = full_name
                    if '.' in full_name:
                        schema_parts = full_name.split('.', 1)
                        schema_name = schema_parts[0]
                        table_name = schema_parts[1]
                    if current_table:
                        tables.append(current_table)
                    current_table = {
                        'name': table_name,
                        'schema': schema_name,
                        'columns': [],
                        'column_types': {},
                        'foreign_keys': []
                    }
                    break

        # Look for column definitions
        elif current_table and (line.startswith('-') or line.startswith('  ')):
            # Format: "- column_name (type)" or "  column_name type"
            col_line = line.lstrip('- ')
            parts = col_line.split()
            if parts:
                col_name = parts[0].strip('`"[],:')
                col_type = parts[1].strip('(),') if len(parts) > 1 else None

                if col_name and col_name.upper() not in ['PRIMARY', 'FOREIGN', 'KEY', 'CONSTRAINT']:
                    assert current_table is not None
                    current_table['columns'].append(col_name)
                    if col_type:
                        current_table['column_types'][col_name] = col_type

        # Look for primary key
        elif current_table and 'PRIMARY KEY' in line.upper():
            pk_parts = line.split('(')
            if len(pk_parts) > 1:
                pk_cols = pk_parts[1].split(')')[0]
                current_table['primary_key'] = pk_cols.strip()

        # Look for foreign key
        elif current_table and 'FOREIGN KEY' in line.upper():
            assert current_table is not None
            current_table['foreign_keys'].append(line.strip())

        # Look for partition key (Cassandra, DynamoDB)
        elif current_table and 'PARTITION KEY' in line.upper():
            pk_match = re.search(r'partition key[s]?[:\s]*([^\n\(]+)', line, re.IGNORECASE)
            if pk_match:
                keys = [k.strip() for k in pk_match.group(1).split(',')]
                current_table['partition_keys'] = keys
            elif '(' in line:
                pk_cols = line.split('(')[1].split(')')[0]
                current_table['partition_keys'] = [k.strip() for k in pk_cols.split(',')]

        # Look for clustering key (Cassandra)
        elif current_table and 'CLUSTERING KEY' in line.upper():
            ck_match = re.search(r'clustering key[s]?[:\s]*([^\n\(]+)', line, re.IGNORECASE)
            if ck_match:
                keys = [k.strip() for k in ck_match.group(1).split(',')]
                current_table['clustering_keys'] = keys

        # Look for sort key (DynamoDB)
        elif current_table and 'SORT KEY' in line.upper():
            sk_match = re.search(r'sort key[:\s]*([^\n\(]+)', line, re.IGNORECASE)
            if sk_match:
                current_table['sort_key'] = sk_match.group(1).strip()

    # Don't forget the last table
    if current_table:
        tables.append(current_table)

    return tables
