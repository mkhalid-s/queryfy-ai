"""
QueryfyAI - Query Tools

Tools for SQL execution and examples:
- find_similar_queries: Find similar past queries for few-shot learning
- execute_sql: Execute a SQL query and return results (legacy)
- execute_and_analyze: Execute SQL + full analysis (analyst mode)
- get_sample_data: Get sample rows from a table
"""

import logging
import random
import re
import sys
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.security import ErrorSanitizer
from app.services.tools.registry import ToolContext

logger = logging.getLogger(__name__)


def _extract_tables_from_sql(sql: str) -> List[Tuple[Optional[str], str]]:
    """
    Extract every table / collection reference from a query string.
    Returns a list of ``(schema_or_None, table)`` pairs in order of
    appearance, ``[]`` for unparseable / empty input.

    Two regex passes cover the dialects analyst-mode emits:
    SQL / Cassandra CQL / DynamoDB PartiQL all share the
    ``FROM/JOIN/INSERT INTO/UPDATE`` shape; MongoDB shell uses
    ``db.<collection>.<method>(…)``.

    Known limitations worth flagging:
    - CTE aliases (``WITH foo AS (...) SELECT * FROM foo``) are
      included — harmless since the dictionary lookup won't have an
      entry for ``foo``.
    - Mongo aggregate pipelines: ``$lookup.from`` is NOT extracted
      (would need pipeline JSON parsing). Only the primary
      ``db.<coll>.aggregate()`` collection is captured.
    """
    if not sql:
        return []
    try:
        import sqlparse
        normalised = sqlparse.format(sql, strip_comments=True)
    except Exception:
        # If sqlparse barfs, fall back to the raw SQL — the regex
        # tolerates raw input fine, just won't strip comments.
        normalised = sql

    out: List[Tuple[Optional[str], str]] = []
    seen: Set[Tuple[Optional[str], str]] = set()

    # SQL-shape: FROM / JOIN / INSERT INTO / UPDATE. Cassandra CQL
    # and DynamoDB PartiQL fall under this umbrella.
    sql_pattern = re.compile(
        r'\b(?:FROM|JOIN|INTO|UPDATE)\s+'
        r'([`"]?[a-zA-Z_][\w]*[`"]?(?:\s*\.\s*[`"]?[a-zA-Z_][\w]*[`"]?)?)',
        re.IGNORECASE,
    )
    for match in sql_pattern.finditer(normalised):
        raw = match.group(1).replace('"', "").replace("`", "").replace(" ", "")
        parts = raw.split(".")
        if len(parts) == 2:
            pair: Tuple[Optional[str], str] = (parts[0], parts[1])
        else:
            pair = (None, parts[0])
        if pair not in seen:
            seen.add(pair)
            out.append(pair)

    # MongoDB shell syntax: db.<collection>.<method>(...).
    # ``db`` is the database from the connection URL; the collection
    # sits at the top level of that DB. Returning (None, collection)
    # matches how the data-dictionary stores Mongo entries.
    mongo_pattern = re.compile(
        r'\bdb\.([a-zA-Z_][\w]*)\s*\.',
        re.IGNORECASE,
    )
    for match in mongo_pattern.finditer(normalised):
        pair = (None, match.group(1))
        if pair not in seen:
            seen.add(pair)
            out.append(pair)

    return out


# Conservative column-name heuristic used only when a table has NO
# ColumnDescription entries in the data dictionary. Once the
# dictionary is populated, explicit is_pii=False on a column
# suppresses the heuristic for that column — the heuristic is
# fallback, not override. Matches on case-insensitive substring.
PII_COLUMN_NAME_HEURISTIC: "frozenset[str]" = frozenset({
    "email",
    "ssn",
    "password",
    "credit_card",
    "creditcard",
    "card_number",
    "token",
    "api_key",
    "apikey",
    "secret",
    "phone",
    "address",
    "authorization",
    "auth_token",
})


def _pii_columns_for_table(
    columns: List[str],
    table_descriptions: Optional[Dict[str, Dict[str, Any]]],
) -> Set[str]:
    """
    Decide which column names should have values redacted in
    sample-data output.

    Rule:
    - Column has a ColumnDescription entry → honour ``is_pii`` exactly.
    - Column has NO entry → fall back to the name-substring heuristic
      (defence-in-depth: include rather than miss).

    Never raises; returns an empty set when no signal is available.
    """
    if table_descriptions is None:
        table_descriptions = {}
    pii: Set[str] = set()
    for col in columns:
        desc = table_descriptions.get(col)
        if desc is not None:
            if desc.get("is_pii"):
                pii.add(col)
            continue
        col_lower = col.lower()
        for token in PII_COLUMN_NAME_HEURISTIC:
            if token in col_lower:
                pii.add(col)
                break
    return pii


async def _load_pii_column_set_for_table(
    db_config: Any,
    columns: List[str],
    table_identifier: Optional[str],
) -> Set[str]:
    """
    Resolve PII columns for a tool that knows its source table.

    Consults the data dictionary first (explicit ``is_pii=True``
    wins); falls back to the column-name heuristic only for columns
    with no dictionary entry. Never raises — on any dictionary
    failure drops to heuristic-only so the tool keeps working.

    Used by ``get_sample_data`` which receives ``schema.table`` as
    input. Tools running arbitrary SQL should use
    ``_load_pii_column_set_for_query`` instead so the dictionary
    lookup is narrowed to referenced tables.
    """
    if not columns:
        return set()

    table_descriptions: Optional[Dict[str, Dict[str, Any]]] = None
    try:
        from app.services.data_dictionary import data_dictionary
        from app.services.vector_db import vector_db

        if table_identifier:
            schema_part, dot, table_part = table_identifier.partition(".")
            if dot:
                sch: Optional[str] = schema_part
                tbl = table_part
            else:
                sch = None
                tbl = table_identifier
        else:
            sch = None
            tbl = ""

        table_descriptions = await data_dictionary.get_table_descriptions(
            connection_hash=vector_db._hash_connection(db_config.connection_url),
            table_name=tbl,
            schema_name=sch,
        )
    except Exception as e:
        logger.warning(
            "PII table-scoped lookup failed, using heuristic only: %s", e
        )

    return _pii_columns_for_table(columns, table_descriptions)


async def _load_pii_column_set_for_connection(
    db_config: Any,
    columns: List[str],
) -> Set[str]:
    """
    Resolve PII columns for a tool that does NOT know its source
    table — e.g. ``execute_and_analyze`` / ``execute_sql`` running
    arbitrary SQL that may JOIN multiple tables.

    OR-semantics: if any ``ColumnDescription`` on this connection
    flags a same-named column as ``is_pii=True``, mask it. Defence-
    in-depth at the cost of occasional false positives (e.g.,
    ``audit_logs.email`` gets masked because ``users.email`` is
    flagged). Use ``_load_pii_column_set_for_query`` when the SQL
    is available — it narrows the lookup to referenced tables and
    avoids the false-positive case.

    Falls back to the column-name heuristic for columns that have no
    dictionary entry anywhere. Never raises.
    """
    if not columns:
        return set()

    aggregated: Dict[str, Dict[str, Any]] = {}
    try:
        from app.services.data_dictionary import data_dictionary
        from app.services.vector_db import vector_db

        connection_hash = vector_db._hash_connection(db_config.connection_url)
        # Use a generous limit so small-to-medium dictionaries fit in a
        # single round-trip. list_column_descriptions defaults to 100,
        # which would silently mask only a prefix of real columns.
        # Pagination added as a safety net for very large dictionaries.
        page_limit = 10000
        offset = 0
        while True:
            page = await data_dictionary.list_column_descriptions(
                connection_hash=connection_hash,
                limit=page_limit,
                offset=offset,
            )
            items = page.get("items", []) if isinstance(page, dict) else []
            for row in items:
                col_name = row.get("column_name")
                if not col_name:
                    continue
                existing = aggregated.get(col_name)
                # OR-semantics: any True wins over False.
                new_is_pii = bool(row.get("is_pii"))
                if existing is None:
                    aggregated[col_name] = {
                        "is_pii": new_is_pii,
                        "_description_exists": True,
                    }
                elif new_is_pii:
                    existing["is_pii"] = True
            total = page.get("total", len(items)) if isinstance(page, dict) else len(items)
            offset += len(items)
            if len(items) < page_limit or offset >= total:
                break
    except Exception as e:
        logger.warning(
            "PII connection-scoped lookup failed, using heuristic only: %s", e
        )

    return _pii_columns_for_table(columns, aggregated if aggregated else None)


async def _load_pii_column_set_for_query(
    db_config: Any,
    columns: List[str],
    sql: Optional[str],
) -> Set[str]:
    """
    Table-aware PII redaction.

    Narrows the dictionary lookup to tables referenced by ``sql`` so
    a column flagged ``is_pii=True`` on one table doesn't bleed
    across queries that don't touch it (e.g. ``users.email`` doesn't
    mask ``audit_logs.email`` flagged False).

    Falls through to the connection-wide helper when ``sql`` is
    missing OR when it parses to no identifiers (pure CTEs,
    computed tables, exotic syntax). OR-semantics holds within the
    narrowed set; heuristic fills gaps for unmapped columns.

    Never raises. On any internal error the connection-wide helper is
    called as a defence-in-depth fallback.
    """
    if not columns:
        return set()
    if not sql:
        return await _load_pii_column_set_for_connection(db_config, columns)

    table_refs = _extract_tables_from_sql(sql)
    if not table_refs:
        return await _load_pii_column_set_for_connection(db_config, columns)

    aggregated: Dict[str, Dict[str, Any]] = {}
    try:
        from app.services.data_dictionary import data_dictionary
        from app.services.vector_db import vector_db

        connection_hash = vector_db._hash_connection(db_config.connection_url)
        for schema_name, table_name in table_refs:
            try:
                table_desc = await data_dictionary.get_table_descriptions(
                    connection_hash=connection_hash,
                    table_name=table_name,
                    schema_name=schema_name,
                )
            except Exception as inner_e:
                logger.debug(
                    "PII per-table lookup failed for %s.%s: %s",
                    schema_name or "",
                    table_name,
                    inner_e,
                )
                continue
            if not isinstance(table_desc, dict):
                continue
            # OR-semantics within the narrowed set: a True wins, but
            # a True only fires if it's on a referenced table — that's
            # — narrowing across same-named columns is the point.
            for col_name, desc in table_desc.items():
                new_is_pii = bool((desc or {}).get("is_pii"))
                existing = aggregated.get(col_name)
                if existing is None:
                    aggregated[col_name] = {
                        "is_pii": new_is_pii,
                        "_description_exists": True,
                    }
                elif new_is_pii:
                    existing["is_pii"] = True
    except Exception as e:
        logger.warning(
            "PII query-scoped lookup failed, falling back to "
            "connection-wide OR-semantics: %s",
            e,
        )
        return await _load_pii_column_set_for_connection(db_config, columns)

    return _pii_columns_for_table(columns, aggregated if aggregated else None)


def _redact_pii_in_rows(
    rows: List[Dict[str, Any]],
    pii_columns: Set[str],
) -> None:
    """
    Mutate ``rows`` in place, replacing values in ``pii_columns`` with
    the literal ``[REDACTED]``. Safe no-op on rows that don't support
    ``__setitem__`` (custom row objects). Does NOT allocate a new list,
    so shallow-copied downstream slices inherit the mask.
    """
    if not pii_columns or not rows:
        return
    for row in rows:
        if not hasattr(row, "__setitem__"):
            continue
        for col in pii_columns:
            if col in row and row[col] is not None:
                row[col] = "[REDACTED]"


def _redact_insight_cell_values(
    insights: Any,
    pii_columns: Set[str],
) -> Any:
    """
    Belt-and-braces cleanup for ``detect_insights`` output. Even when
    upstream rows are redacted, the detector's output dicts can still
    surface raw cell values if a future detector reads original
    references. We walk the common shapes and redact any cell value
    that appears under a PII column name.

    Known shapes (all defensive — missing keys are skipped silently):
      - insight["metrics"]["outliers"][].value         → literal
      - insight["metrics"]["outliers"][].identifier    → "col=value"
      - insight["metrics"]["group"]                    → grouped value
      - insight["metrics"]["significant_diffs"][].group

    Returns the same object (modifies in place for dict items; passes
    through non-dict inputs unchanged).
    """
    if not isinstance(insights, list) or not pii_columns:
        return insights

    def _mask_identifier(s: Any) -> Any:
        # Identifiers look like "col=value" or "col_a=v_a, col_b=v_b".
        # Redact only the values whose key is in ``pii_columns``.
        if not isinstance(s, str):
            return s
        parts = []
        for piece in s.split(","):
            piece = piece.strip()
            if "=" in piece:
                k, _, _ = piece.partition("=")
                if k.strip() in pii_columns:
                    parts.append(f"{k.strip()}=[REDACTED]")
                    continue
            parts.append(piece)
        return ", ".join(parts)

    for insight in insights:
        if not isinstance(insight, dict):
            continue
        metrics = insight.get("metrics")
        if not isinstance(metrics, dict):
            continue

        # outliers[] with value / identifier
        outliers = metrics.get("outliers")
        if isinstance(outliers, list):
            # Some outlier shapes include a ``column`` field naming
            # the source column. Redact .value when that column is PII.
            for outlier in outliers:
                if not isinstance(outlier, dict):
                    continue
                src_col = outlier.get("column") or insight.get("column_name")
                if src_col and src_col in pii_columns:
                    outlier["value"] = "[REDACTED]"
                if "identifier" in outlier:
                    outlier["identifier"] = _mask_identifier(outlier["identifier"])

        # significant_diffs[] with group (comparison detectors)
        diffs = metrics.get("significant_diffs")
        if isinstance(diffs, list):
            for diff in diffs:
                if not isinstance(diff, dict):
                    continue
                group_col = diff.get("group_column") or insight.get("group_column")
                if group_col and group_col in pii_columns:
                    diff["group"] = "[REDACTED]"

        # Top-level group key (concentration / segment detectors)
        group_col = insight.get("group_column") or insight.get("column_name")
        if group_col and group_col in pii_columns and "group" in metrics:
            metrics["group"] = "[REDACTED]"

    return insights


def sanitize_value(v):
    """Sanitize a single value for JSON serialization.

    - Preserves None, int, float, bool as-is
    - Converts everything else to string
    - Strips control characters
    - Truncates strings longer than 100 chars
    """
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    # Replace control characters with space
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', s)
    # Truncate long strings
    if len(s) > 100:
        s = s[:100] + "..."
    return s


async def find_similar_queries(
    context: ToolContext,
    query: str,
    limit: int = 3
) -> str:
    """
    Find previously successful queries similar to the current question.

    Wraps: vector_db.find_similar_queries()

    Args:
        context: Tool execution context with connection info
        query: The natural language question to find similar queries for
        limit: Maximum number of similar queries to return

    Returns:
        Formatted string with similar queries and their SQL
    """
    from app.services.vector_db import vector_db

    if not context.connection_url:
        return "Error: No database connection. Please connect to a database first."

    try:
        # Find similar queries from vector DB
        similar = vector_db.find_similar_queries(
            connection_url=context.connection_url,
            query=query,
            n=limit
        )

        if not similar:
            return f"""No similar queries found for: "{query}"

This might be a new type of question. Consider:
1. Breaking down the question into simpler parts
2. Looking at the schema to understand available tables
3. Starting with a basic query and iterating"""

        # Format the output
        output_lines = [f"Similar queries found ({len(similar)} results):", ""]

        for i, q in enumerate(similar, 1):
            nl_query = q.get('query', q.get('nl_query', 'Unknown question'))
            sql = q.get('sql', 'No SQL available')
            rating = q.get('rating', 0)

            output_lines.append(f"Example {i}:")
            output_lines.append(f"  Question: {nl_query}")
            output_lines.append("  SQL:")
            # Indent SQL for readability
            for sql_line in sql.split('\n'):
                output_lines.append(f"    {sql_line}")

            if rating > 0:
                output_lines.append(f"  Rating: {'*' * rating}")
            output_lines.append("")

        return "\n".join(output_lines)

    except Exception as e:
        logger.error(f"find_similar_queries error: {e}", exc_info=True)
        return f"Error finding similar queries: {ErrorSanitizer.sanitize_error(e)}"


async def execute_sql(
    context: ToolContext,
    sql: str,
    limit: Optional[int] = None
) -> str:
    """
    Execute a SQL query and return results.

    Wraps: DatabaseService.execute_query()

    IMPORTANT: Only SELECT queries are allowed for safety.

    Limits (Phase 1 - Conservative Rollout):
    - Default: 1000 rows (from AGENT_QUERY_LIMIT_DEFAULT)
    - Maximum: 10000 rows (from AGENT_QUERY_LIMIT_MAX)
    - Target (Phase 3): 5000/20000 rows after metrics validation

    Note: For analyst mode with full statistical analysis, prefer execute_and_analyze
    which includes memory guards and intelligent sampling.

    Args:
        context: Tool execution context with database config
        sql: The SQL SELECT query to execute
        limit: Maximum number of rows to return (defaults to AGENT_QUERY_LIMIT_DEFAULT)

    Returns:
        JSON string with query results (includes both display text and structured data)
    """
    import json

    from app.core.config import settings
    from app.models.schemas import DatabaseConfig
    from app.services.database_service import DatabaseService

    if not context.db_config:
        return json.dumps({
            "success": False,
            "error": "No database connection. Please connect to a database first.",
            "display": "Error: No database connection. Please connect to a database first."
        })

    # Determine limit with safety bounds (same logic as execute_and_analyze)
    if limit is None:
        limit = settings.AGENT_QUERY_LIMIT_DEFAULT
    elif limit > settings.AGENT_QUERY_LIMIT_MAX:
        limit = settings.AGENT_QUERY_LIMIT_MAX
        logger.warning(f"execute_sql: Requested limit {limit} exceeds max, capping at {settings.AGENT_QUERY_LIMIT_MAX}")

    try:
        # Create DatabaseConfig from context
        db_config = DatabaseConfig(**context.db_config) if isinstance(context.db_config, dict) else context.db_config

        # Execute the query - always use fresh data for agent decisions
        result = await DatabaseService.execute_query(
            config=db_config,
            sql=sql,
            limit=limit,
            force_refresh=True,  # Agent needs fresh data to make accurate decisions
        )

        if not result:
            return json.dumps({
                "success": True,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "display": "Query executed but returned no results."
            })

        # Extract structured data
        columns = result.get('columns', [])
        rows = result.get('rows', [])
        row_count = result.get('row_count', len(rows))
        execution_time = result.get('execution_time_ms', 0)

        # The legacy execute_sql path returns raw DB values verbatim
        # to the LLM. Use the query-scoped PII helper so the lookup
        # narrows to tables referenced in ``sql`` and we don't mask
        # audit_logs.email just because users.email is flagged
        # elsewhere on the connection. Falls back to connection-wide
        # OR-semantics if the SQL doesn't parse to any FROM/JOIN.
        pii_columns = await _load_pii_column_set_for_query(
            db_config, columns, sql
        )
        _redact_pii_in_rows(rows, pii_columns)
        if pii_columns:
            logger.info(
                "execute_sql.pii_masked",
                extra={
                    "pii_columns": sorted(pii_columns),
                    "affected_rows": len(rows),
                },
            )

        # Return all fetched rows (no sub-limiting)
        # The limit parameter controls how many rows to fetch
        sanitized_rows = [
            {col: sanitize_value(row.get(col)) for col in columns}
            for row in rows
        ] if rows else []

        # Brief display text (no table, just summary)
        display_text = f"Query executed successfully. {row_count} rows returned in {execution_time}ms."

        # Return compact JSON
        return json.dumps({
            "success": True,
            "columns": columns,
            "rows": sanitized_rows,
            "row_count": row_count,
            "execution_time_ms": execution_time,
            "display": display_text
        })

    except ValueError as e:
        # Security validation failed
        logger.warning(f"SQL validation failed: {e}")
        sanitized = ErrorSanitizer.sanitize_error(e)
        return json.dumps({
            "success": False,
            "error": sanitized,
            "display": f"Query rejected: {sanitized}\n\nOnly SELECT queries are allowed for safety."
        })

    except Exception as e:
        logger.error(f"execute_sql error: {e}", exc_info=True)
        sanitized = ErrorSanitizer.sanitize_error(e)
        return json.dumps({
            "success": False,
            "error": sanitized,
            "display": f"Error executing query: {sanitized}"
        })


def detect_data_characteristics(columns: List[str], rows: List[dict]) -> dict:
    """
    Detect data characteristics that may affect sampling quality.

    Returns:
        dict with keys:
        - has_time_series: bool - Data has date/time columns
        - has_id_sequence: bool - Data has sequential ID columns
        - has_outliers_risk: bool - Data may have rare high-value records
        - sampling_appropriate: bool - Overall sampling recommendation
        - warnings: List[str] - Specific warnings about sampling bias
    """
    warnings_list: List[str] = []
    characteristics: dict[str, Any] = {
        "has_time_series": False,
        "has_id_sequence": False,
        "has_outliers_risk": False,
        "sampling_appropriate": True,
        "warnings": warnings_list
    }

    # Check column names for time-series indicators
    time_keywords = ['date', 'time', 'timestamp', 'created', 'updated', 'modified']
    time_columns = [c for c in columns if any(kw in c.lower() for kw in time_keywords)]

    if time_columns:
        characteristics["has_time_series"] = True
        characteristics["sampling_appropriate"] = False
        warnings_list.append(
            f"Time-series data detected (columns: {', '.join(time_columns[:3])}). "
            "Random sampling may not capture recent trends or seasonal patterns."
        )

    # Check for sequential ID columns
    id_keywords = ['id', 'sequence', 'order_number', 'index']
    id_columns = [c for c in columns if any(kw in c.lower() for kw in id_keywords)]

    if id_columns:
        # Check if IDs are sequential (sample first 100 rows)
        sample_check = rows[:min(100, len(rows))]
        for id_col in id_columns:
            try:
                values = [r.get(id_col) for r in sample_check if r.get(id_col) is not None]
                if len(values) > 10:
                    # Check if mostly sequential
                    numeric_values = [int(v) for v in values if v is not None and str(v).isdigit()]
                    if len(numeric_values) > 5:
                        diffs = [numeric_values[i+1] - numeric_values[i]
                                for i in range(len(numeric_values)-1)]
                        avg_diff = sum(diffs) / len(diffs) if diffs else 0
                        if 0 < avg_diff < 2:  # Mostly sequential
                            characteristics["has_id_sequence"] = True
                            characteristics["sampling_appropriate"] = False
                            warnings_list.append(
                                f"Sequential ordering detected in '{id_col}'. "
                                "Random sampling may miss recently added records."
                            )
                            break  # Found one, don't check others
            except (ValueError, TypeError):
                pass  # Not numeric, skip

    # Check for potential outliers in numeric columns
    numeric_columns = []
    for col in columns:
        # Sample first 100 rows to check types
        sample_vals = [r.get(col) for r in rows[:min(100, len(rows))] if r.get(col) is not None]
        if sample_vals:
            # Check if mostly numeric
            numeric_count = sum(1 for v in sample_vals
                              if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.', '').replace('-', '').isdigit()))
            if numeric_count > len(sample_vals) * 0.8:  # 80%+ numeric
                numeric_columns.append(col)

    # Check for high variance (potential outliers)
    import statistics as _statistics_module
    for col in numeric_columns[:3]:  # Check up to 3 numeric columns
        try:
            float_values: List[float] = []
            for r in rows[:min(1000, len(rows))]:
                raw_val = r.get(col)
                if raw_val is not None and str(raw_val).replace('.', '').replace('-', '').isdigit():
                    float_values.append(float(raw_val))
            if len(float_values) > 10:
                mean: float = _statistics_module.mean(float_values)
                stdev: float = _statistics_module.stdev(float_values) if len(float_values) > 1 else 0.0
                # High coefficient of variation indicates outliers
                if mean > 0 and stdev > 0 and (stdev / mean) > 2:  # CV > 2 suggests high variance
                    characteristics["has_outliers_risk"] = True
                    warnings_list.append(
                        f"High variance detected in '{col}' (coefficient of variation > 2). "
                        "Random sampling may miss rare high-value records."
                    )
                    break  # Found one, don't check others
        except (ValueError, TypeError, _statistics_module.StatisticsError):
            pass  # Skip if calculation fails

    return characteristics


def extract_json_from_llm_response(content: str) -> list:
    """
    Robustly extract JSON array from LLM response.

    Handles all common LLM response formats:
    1. Clean JSON array: [{"type": "...", ...}, ...]
    2. Markdown code fence: ```json\n[...]\n```
    3. Text before/after JSON: "Here are insights:\n[...]\nLet me know..."
    4. Single object instead of array: {"type": "..."}
    5. Multiple code blocks or nested fences

    Returns:
        List of parsed JSON objects, or empty list if parsing fails
    """
    import json
    import re

    if not content or not content.strip():
        return []

    text = content.strip()

    # Step 1: Remove markdown code fences (handles ```json, ```JSON, ```, etc.)
    # Pattern matches opening fence with optional language, content, and closing fence
    code_block_pattern = r'```(?:json|JSON)?\s*\n?([\s\S]*?)\n?```'
    code_blocks = re.findall(code_block_pattern, text)

    if code_blocks:
        # Use the first code block that contains JSON
        for block in code_blocks:
            block = block.strip()
            if block.startswith('[') or block.startswith('{'):
                text = block
                break

    # Step 2: Find JSON array or object
    # Look for the outermost [ ] or { }
    json_array_match = re.search(r'\[[\s\S]*\]', text)
    json_object_match = re.search(r'\{[\s\S]*\}', text)

    json_str = None

    # Prefer array over object
    if json_array_match:
        json_str = json_array_match.group()
    elif json_object_match:
        # Wrap single object in array
        json_str = '[' + json_object_match.group() + ']'

    if not json_str:
        return []

    # Step 3: Clean common JSON issues from LLM output
    # Remove trailing commas before ] or }
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    # Step 4: Parse JSON
    try:
        result = json.loads(json_str)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return [result]
        else:
            return []
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parsing failed: {e}, attempting cleanup")

        # Step 5: Try more aggressive cleanup
        try:
            # Remove any non-printable characters except newlines/tabs
            json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', json_str)
            result = json.loads(json_str)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict):
                return [result]
        except json.JSONDecodeError:
            pass

        return []


def _build_analysis_digest(
    rows: List[dict],
    columns: List[str],
    sql: str,
    statistics: dict,
    quality: dict,
    aggregated: bool,
    existing_insights: list,
) -> dict:
    """
    Build a compact, LLM-friendly digest of the query result.

    This is the load-bearing primitive of the "talk to your data"
    experience. The LLM never sees raw bulk rows — it sees THIS,
    which carries the ground-truth numbers + enough exemplars to
    reason about the distribution.

    Structure is fixed so prompts stay predictable. Total size is
    bounded by column count (not row count) — typical ~3-5KB.

    Contents:
      sql                   — the query (truncated) for reference
      row_count             — true count (not preview)
      column_count          — len(columns)
      columns               — full list
      aggregated            — GROUP BY / aggregate flag from 3a.3
      quality_score         — overall DQ (0-100) if computed
      statistics            — per-column: min/max/mean/median/stdev/quartiles
      numeric_exemplars     — top-5 + bottom-5 rows per top-3 numeric columns
      categorical_top       — top-10 distinct values per top-3 categorical columns
      detector_findings     — statistical-engine insights (concentration,
                              trend, anomaly, comparison), trimmed
    """
    digest: Dict[str, Any] = {
        "sql": (sql or "")[:500],
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": columns,
        "aggregated": aggregated,
        "quality_score": (quality or {}).get("overall_score"),
        "statistics": statistics or {},
    }

    # Numeric exemplars — top-5 and bottom-5 rows sorted by each
    # major numeric column. Gives the LLM concrete examples of
    # extremes to narrate ("Agent X has $500 premium vs median $2700").
    numeric_cols = [
        name
        for name, stats_ in (statistics or {}).items()
        if isinstance(stats_, dict) and stats_.get("mean") is not None
    ][:3]

    if numeric_cols and rows:
        exemplars: Dict[str, Any] = {}
        for col in numeric_cols:
            valid_rows = [
                r for r in rows
                if isinstance(r.get(col), (int, float))
                and not isinstance(r.get(col), bool)
            ]
            if len(valid_rows) < 2:
                continue
            sorted_rows = sorted(valid_rows, key=lambda r: r[col])
            # Shorten string cells so the digest stays compact.
            def _trim_row(row: dict) -> dict:
                return {
                    k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v)
                    for k, v in row.items()
                }
            exemplars[col] = {
                "lowest_5": [_trim_row(r) for r in sorted_rows[:5]],
                "highest_5": [_trim_row(r) for r in sorted_rows[-5:][::-1]],
            }
        if exemplars:
            digest["numeric_exemplars"] = exemplars

    # Categorical frequencies — top-10 values per major non-numeric
    # column. Lets the LLM say "NA region has 1,200 policies vs
    # LATAM's 34" without raw rows.
    if rows:
        non_numeric_cols = [
            c for c in columns if c not in numeric_cols
        ][:3]
        cat_top: Dict[str, Any] = {}
        for col in non_numeric_cols:
            counts: Dict[Any, int] = {}
            for r in rows:
                v = r.get(col)
                if v is None:
                    continue
                try:
                    counts[v] = counts.get(v, 0) + 1
                except TypeError:
                    continue  # unhashable, skip
            if not counts:
                continue
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
            cat_top[col] = [{"value": str(v)[:60], "count": c} for v, c in top]
        if cat_top:
            digest["categorical_top"] = cat_top

    # Detector findings — forward what detect_insights already produced
    # so the LLM knows "the concentration detector flagged this column"
    # and can cite it directly. Trim each finding's description so the
    # digest stays compact.
    if existing_insights:
        trimmed = []
        for ins in existing_insights[:10]:
            if not isinstance(ins, dict):
                continue
            trimmed.append({
                "type": ins.get("type"),
                "severity": ins.get("severity"),
                "title": (ins.get("title") or "")[:140],
                "column_name": ins.get("column_name"),
                "description": (ins.get("description") or "")[:280],
            })
        if trimmed:
            digest["detector_findings"] = trimmed

    return digest


async def enhance_insights_with_llm(
    context: ToolContext,
    rows: List[dict],
    columns: List[str],
    sql: str,
    statistics: dict,
    existing_insights: list,
    question: Optional[str] = None,
    quality: Optional[dict] = None,
    aggregated: bool = False,
) -> list:
    """
    Generate LLM business insights grounded in the user's ORIGINAL question.

    Architecture note (post-remediation): the LLM never receives the
    raw row set. Instead it gets a DIGEST — stats + top-5/bottom-5
    rows by each numeric column + categorical frequencies + the user's
    question. The digest is ~3-5KB regardless of how many rows the
    query returned, so this function fires on ALL analyst queries
    (previously capped at 100 rows and only aggregated SQL — which
    silently disabled business insights on the analytical workloads
    that needed them most).

    Division of labour:
      - Analysis engines (detect_insights, compute_statistics) produce
        DETERMINISTIC facts — stats, outlier exemplars, Pareto ratios.
      - This function gives those facts + the user's question to the
        LLM and asks it to produce narrative insights grounded in
        BOTH. The LLM never computes numbers; it cites them.

    Args:
        context: Tool execution context with LLM config.
        rows: Full row set (used only to pick exemplars for the digest).
        columns: Column names.
        sql: The original SQL query.
        statistics: Pre-computed statistics (ground-truth numbers).
        existing_insights: Statistical findings from detect_insights.
        question: The user's original natural-language question.
        quality: Pre-computed data-quality assessment.
        aggregated: True for GROUP BY / aggregate queries.

    Returns:
        Enhanced insights list with LLM-generated business narrative
        prepended to ``existing_insights``. Falls back to
        ``existing_insights`` unchanged on any failure.
    """
    try:
        from app.models.schemas import LLMConfig
        from app.services.llm_service import LLMService

        # Build a compact digest. Size is O(columns), not O(rows) —
        # ~3-5KB even for 10,000-row result sets.
        digest = _build_analysis_digest(
            rows=rows,
            columns=columns,
            sql=sql,
            statistics=statistics,
            quality=quality or {},
            aggregated=aggregated,
            existing_insights=existing_insights,
        )

        # Compose the prompt. The user's question is the anchor —
        # without it the LLM writes generic stat descriptions.
        user_question = (question or "").strip()
        if not user_question:
            user_question = (
                "(No question provided — describe the most important "
                "findings in the data.)"
            )

        logger.info(
            "enhance_insights_with_llm: firing on %d rows (%d columns, "
            "aggregated=%s). digest ~%d bytes.",
            len(rows),
            len(columns),
            aggregated,
            len(str(digest)),
        )

        prompt = f"""You are a senior data analyst answering a business question.

THE USER ASKED:
{user_question}

QUERY EXECUTED:
{sql[:800]}

DATA DIGEST (pre-computed facts — cite these, don't recalculate):
{digest}

Your task: write 3-5 specific, quantitative business insights that ANSWER
the user's question. Ground every claim in the digest — use actual
column names, numbers, and category values from it.

Each insight must:
- Start with a concrete FINDING (not "the data shows...").
- Cite specific numbers from the digest (means, ranges, top/bottom
  exemplars, concentration ratios).
- End with a SO-WHAT — what this means for decisions.
- Include 1-2 actionable follow-ups when the finding warrants them.

Return a JSON array. Each element must match this exact shape:
[
  {{
    "type": "business_insight",
    "severity": "high" | "medium" | "low",
    "title": "Concrete finding (5-12 words, no hedging)",
    "description": "One paragraph grounded in digest numbers",
    "recommendations": ["Follow-up 1", "Follow-up 2"]
  }}
]

Severity:
- "high" = material impact (>20% of total, critical outlier, risk signal)
- "medium" = notable pattern worth attention
- "low" = informational observation

Do NOT:
- Invent numbers not in the digest.
- Write generic statements ("the data shows variation").
- Repeat the user's question back at them.
- Say "see insights below" — YOU are the insights."""

        # Get LLM config from tool context
        if not context.llm_config:
            logger.warning(
                "LLM insight enhancement SKIPPED — no llm_config on tool "
                "context. Business insights won't appear in the summary. "
                "Check that the session was created with a valid LLM provider."
            )
            return existing_insights

        # Convert dict to LLMConfig object if needed
        llm_config = LLMConfig(**context.llm_config) if isinstance(context.llm_config, dict) else context.llm_config

        # Prepare messages
        messages = [{"role": "user", "content": prompt}]

        # Call LLM service (handle OAuth Gateway)
        # Use 4000 tokens to allow complete structured JSON responses with full recommendations
        if llm_config.provider == "oauth_gateway":
            content, usage = await LLMService._call_oauth_gateway(
                llm_config,
                messages,
                temperature=0.3,
                max_tokens=4000,
                stream=False,
            )
        else:
            # Standard LiteLLM call for other providers
            from litellm import acompletion
            model = LLMService._get_model_string(llm_config)
            api_config = LLMService._get_api_config(llm_config)

            response = await acompletion(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=4000,
                **api_config
            )
            content = response.choices[0].message.content

        # Parse LLM response using robust extractor (handles all DB types consistently)
        llm_insights = extract_json_from_llm_response(content)

        # If extraction failed but we have content, create a single insight from raw text
        if not llm_insights and content and content.strip():
            # Strip markdown fences for fallback display
            fallback_text = content.strip()
            if '```' in fallback_text:
                import re
                fallback_text = re.sub(r'```(?:json|JSON)?\s*', '', fallback_text)
                fallback_text = fallback_text.replace('```', '').strip()

            llm_insights = [{
                "type": "business_insight",
                "severity": "info",
                "description": fallback_text  # Full content - no truncation
            }]

        # Phase 1 Day 2b dedup keys insights by (type, column_name).
        # LLM-generated insights have no natural column_name — without
        # a sentinel, every LLM insight collapses under
        # ("business_insight", "") and dedup keeps only one. Stamp a
        # unique sentinel per insight so each is preserved.
        for idx, insight in enumerate(llm_insights):
            if "column_name" not in insight or not insight.get("column_name"):
                insight["column_name"] = f"_llm_{idx}"

        # Prepend LLM insights to existing insights (show business context first)
        enhanced = llm_insights + existing_insights

        logger.info(f"Successfully enhanced insights with {len(llm_insights)} LLM-generated insights")
        return enhanced

    except Exception as e:
        # Graceful fallback: return original insights if LLM fails
        logger.warning(f"LLM insight enhancement failed: {e}, using statistical insights only")
        return existing_insights


async def execute_and_analyze(
    context: ToolContext,
    sql: str,
    limit: Optional[int] = None,
    question: Optional[str] = None,
) -> str:
    """
    Execute SQL query and perform full statistical analysis on complete result set.

    This is the PRIMARY tool for analyst mode - combines query execution with
    intelligent analysis.

    Limits (Phase 1 - Conservative Rollout):
    - Default: 1000 rows (configurable via AGENT_QUERY_LIMIT_DEFAULT)
    - Maximum: 10000 rows (configurable via AGENT_QUERY_LIMIT_MAX)
    - Target (Phase 3): 5000/20000 rows after metrics validation

    Memory Protection:
    - 50MB threshold prevents OOM
    - Sampling for datasets > 1000 rows
    - String truncation before analysis

    Args:
        context: Tool execution context with database config
        sql: The SQL SELECT query to execute
        limit: Optional row limit (defaults to AGENT_QUERY_LIMIT_DEFAULT)

    Returns:
        JSON string with:
        - Pre-computed insights (trends, outliers, concentrations)
        - Statistical analysis (mean, median, distributions)
        - Data quality assessment
        - Chart recommendations
        - Row count and execution metadata
    """
    import json

    from app.core.config import settings
    from app.models.schemas import DatabaseConfig
    from app.services.analysis_engines import (
        assess_data_quality,
        compute_statistics,
        detect_insights,
        recommend_chart,
    )
    from app.services.database_service import DatabaseService

    if not context.db_config:
        return json.dumps({
            "success": False,
            "error": "No database connection. Please connect to a database first."
        })

    # Determine limit with safety bounds
    if limit is None:
        limit = settings.AGENT_QUERY_LIMIT_DEFAULT
    elif limit > settings.AGENT_QUERY_LIMIT_MAX:
        limit = settings.AGENT_QUERY_LIMIT_MAX
        logger.warning(f"Requested limit {limit} exceeds max, capping at {settings.AGENT_QUERY_LIMIT_MAX}")

    try:
        # Create DatabaseConfig from context
        db_config = DatabaseConfig(**context.db_config) if isinstance(context.db_config, dict) else context.db_config

        # Execute the query with specified limit
        result = await DatabaseService.execute_query(
            config=db_config,
            sql=sql,
            limit=limit,
            force_refresh=True,
        )

        if not result or not result.get('rows'):
            return json.dumps({
                "success": True,
                "analyzed_rows": 0,
                "insights": [],
                "statistics": {},
                "quality": {"overall_score": 0},
                "chart": None,
                "message": "Query executed but returned no results."
            })

        # Extract full result set
        rows = result.get('rows', [])
        columns = result.get('columns', [])
        row_count = len(rows)
        execution_time = result.get('execution_time_ms', 0)

        # Redact at the boundary where rows enter the analysis
        # pipeline. Downstream consumers (statistics, detect_insights,
        # _build_analysis_digest, enhance_insights_with_llm,
        # sanitized_rows, preview_rows, result_cache.astore,
        # /api/v1/results/{rows_ref}, Excel export) all derive from
        # ``rows`` via shallow copies or dict references, so a single
        # upstream mutation cascades through them.
        #
        # Query-scoped lookup narrows to tables referenced by the SQL
        # across SQL/CQL/PartiQL/Mongo dialects. Connection-wide OR-
        # semantics is the safe fallback when the SQL doesn't parse
        # to identifiers (CTEs, computed tables, exotic syntax).
        pii_columns = await _load_pii_column_set_for_query(
            db_config, columns, sql
        )
        _redact_pii_in_rows(rows, pii_columns)
        if pii_columns:
            logger.info(
                "execute_and_analyze.pii_masked",
                extra={
                    "pii_columns": sorted(pii_columns),
                    "affected_rows": len(rows),
                },
            )

        logger.info(f"execute_and_analyze: Analyzing {row_count} rows from query")

        # ============================================================
        # SAFETY MITIGATIONS (memory guards + sampling)
        # ============================================================

        # 1. Memory guard: Estimate result set size to prevent OOM
        sample_for_size_check = rows[:min(100, len(rows))]
        estimated_size = sys.getsizeof(json.dumps(sample_for_size_check)) * (len(rows) / max(len(sample_for_size_check), 1))

        MEMORY_THRESHOLD_BYTES = 50_000_000  # 50 MB
        if estimated_size > MEMORY_THRESHOLD_BYTES:
            logger.warning(
                f"Result set too large for analysis: {estimated_size / 1_000_000:.1f} MB "
                f"(threshold: {MEMORY_THRESHOLD_BYTES / 1_000_000:.1f} MB)"
            )
            return json.dumps({
                "success": False,
                "error": "Result set too large for in-depth analysis",
                "rows_returned": len(rows),
                "size_mb": round(estimated_size / 1_000_000, 1),
                "recommendation": "Add WHERE clause to filter data, or use execute_sql for basic results"
            })

        # ============================================================
        # SAMPLING DECISION (with bias detection)
        # ============================================================

        # Phase 4.1: when the result cache is enabled we analyse the
        # FULL row set (bounded only by AGENT_QUERY_LIMIT_MAX = 10k,
        # which we consider the practical upper bound for in-process
        # analytics). The legacy 1000-row SAMPLING_THRESHOLD produced
        # insights on a random subset while the tool still returned
        # all rows, which then blew past the 50KB cap — the exact
        # "Result too large for processing" failure the user hit. With
        # the cache, the full rows never ride in the tool payload, so
        # we can analyse everything honestly.
        if settings.FIX_RESULT_CACHE:
            SAMPLING_THRESHOLD = max(
                settings.AGENT_QUERY_LIMIT_MAX,
                len(rows) + 1,
            )
        else:
            SAMPLING_THRESHOLD = 1000

        # Detect data characteristics before sampling
        data_characteristics = detect_data_characteristics(columns, rows)

        # Determine if sampling is appropriate
        should_sample = len(rows) > SAMPLING_THRESHOLD
        sample_size = min(SAMPLING_THRESHOLD, len(rows))
        used_sampling = False
        sampling_warnings = []

        if should_sample:
            if not data_characteristics["sampling_appropriate"]:
                # Data characteristics suggest sampling may introduce bias
                logger.warning(
                    f"execute_and_analyze: Data characteristics suggest sampling may introduce bias. "
                    f"Warnings: {data_characteristics['warnings']}"
                )

                # Decision tree:
                # 1. If dataset < 2500 rows: Analyze full set (acceptable performance hit)
                # 2. If dataset >= 2500 rows: Use sampling but add strong warnings
                if len(rows) < 2500:
                    logger.info(f"Analyzing full dataset ({len(rows)} rows) due to sampling concerns")
                    sampled_rows = rows
                    used_sampling = False
                else:
                    logger.info(f"Using sampling despite concerns (dataset too large: {len(rows)} rows)")
                    sampled_rows = random.sample(rows, sample_size)
                    used_sampling = True
                    sampling_warnings = data_characteristics["warnings"]
            else:
                # Sampling is appropriate for this data
                sampled_rows = random.sample(rows, sample_size)
                used_sampling = True
                logger.info(f"Sampling {sample_size} of {len(rows)} rows for analysis (performance optimization)")
        else:
            # Small dataset, no sampling needed
            sampled_rows = rows
            used_sampling = False

        # 3. Prepare data for analysis (smart truncation)
        def prepare_for_analysis(row):
            """
            Prepare row data for analysis engines.

            Strategy:
            - Keep numeric/date columns intact (needed for statistics)
            - Keep categorical strings intact (needed for grouping/patterns)
            - Only truncate very long text fields (> 500 chars)
            - Preserve data quality for meaningful analysis
            """
            prepared = {}
            for k, v in row.items():
                if v is None:
                    prepared[k] = v
                elif isinstance(v, str):
                    # Keep strings under 500 chars intact for good analysis
                    # Only truncate extremely long text (likely descriptions/notes)
                    if len(v) > 500:
                        prepared[k] = v[:500] + "..."
                    else:
                        prepared[k] = v
                else:
                    # Keep all non-string values intact (numbers, dates, booleans)
                    prepared[k] = v
            return prepared

        rows_for_analysis = [prepare_for_analysis(r) for r in sampled_rows]

        # ============================================================
        # ANALYZE DATASET (hybrid strategy for quality + performance)
        # ============================================================

        # Phase 4 cross-phase wiring: detect aggregation FIRST (was below
        # the stats-computation block before this commit). Both
        # compute_statistics call sites need the flag, and the aggregated
        # branch in statistics.py suppresses Gini/HHI metrics that would
        # otherwise be misleading on group-aggregated rows.
        aggregated_flag = False
        grouping_columns: list = []
        aggregate_columns: list = []
        if settings.FIX_AGGREGATION_DETECTION:
            try:
                from app.services.analysis_engines.aggregation_detector import (
                    detect_aggregation,
                )

                agg_info = detect_aggregation(sql, columns)
                aggregated_flag = bool(agg_info.get("aggregated"))
                grouping_columns = list(agg_info.get("grouping_columns") or [])  # type: ignore[call-overload]
                aggregate_columns = list(agg_info.get("aggregate_columns") or [])  # type: ignore[call-overload]
            except Exception as e:
                logger.warning(f"Aggregation detection failed: {e}")

        # CRITICAL: Compute statistics on FULL dataset for accuracy
        # Only use sampling for detailed pattern detection (performance)
        full_statistics = (
            compute_statistics(rows, aggregated=aggregated_flag)
            if len(rows) <= 10000
            else None
        )

        # Use sampled rows for pattern detection and insights
        # (This is where the performance bottleneck is)

        # ============================================================
        # HELPER: Clean numeric values for JSON serialization
        # ============================================================
        def sanitize_numeric(value):
            """Convert NaN/Infinity to JSON-safe values"""
            if isinstance(value, float):
                if value != value:  # NaN check
                    return None
                elif value == float('inf'):
                    return 999999999  # Large but finite number
                elif value == float('-inf'):
                    return -999999999
            return value

        def sanitize_dict(obj):
            """Recursively sanitize dictionary for JSON"""
            if isinstance(obj, dict):
                return {k: sanitize_dict(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [sanitize_dict(item) for item in obj]
            else:
                return sanitize_numeric(obj)

        # ============================================================
        # RUN ANALYSIS ENGINES
        # ============================================================

        # ``aggregated_flag`` was computed earlier (above the
        # full_statistics block). Reuse it here.

        # Phase 4 cross-phase wiring: surface progress through the
        # ToolContext.progress_emitter (Phase 3b.2). For 9000-row
        # queries the analysis phase takes 3-4 seconds and previously
        # produced no UI feedback because no driver-native progress
        # was emitted. The emitter is a no-op when None (legacy
        # tool callers, tests).
        emit_progress = getattr(context, "progress_emitter", None)

        def _progress(stage: str, percent: float) -> None:
            if not emit_progress:
                return
            try:
                emit_progress({
                    "stage": stage,
                    "percent": float(percent),
                    "rows_read": row_count,
                })
            except Exception as _e:  # never let instrumentation fail the tool
                logger.debug(f"progress_emitter failed silently: {_e}")

        _progress("analysis_starting", 0.0)

        # 1. Detect insights (trends, outliers, concentrations, etc.)
        # Use sampled data for pattern detection (performance optimization).
        # Phase 4 cross-phase wiring: ``aggregated`` flows through to
        # EVERY analysis engine (not just detect_insights) so each can
        # apply its own threshold / metric adjustments. Statistics
        # suppresses Gini/HHI for aggregated views; data_quality
        # surfaces the mode for UI labelling; recommend_chart biases
        # toward bar/column over scatter for grouped output.
        insights = detect_insights(
            rows_for_analysis,
            analysis_types=["all"],
            aggregated=aggregated_flag,
        )
        insights = sanitize_dict(insights) if insights else []
        # Defence-in-depth: detector output can carry raw cell values
        # in outliers / identifiers / group keys even when the input
        # rows are redacted, because a future detector might re-query
        # original references. Scrub those fields.
        insights = _redact_insight_cell_values(insights, pii_columns)
        _progress("insights_detected", 25.0)

        # Diagnostic: when detect_insights returns empty, log the
        # column shape so operators can tell whether the data was
        # structurally un-insightable (no numeric cols / no date cols /
        # uniform values) vs. a bug. Caught the "Analyzed N results.
        # See insights below" empty-promise UX.
        if not insights:
            logger.info(
                "detect_insights produced no findings "
                "(rows=%d, columns=%d, aggregated=%s) — summary will "
                "fall through to statistics narrative",
                len(rows_for_analysis),
                len(columns),
                aggregated_flag,
            )

        # 2. Compute statistics (mean, median, distributions)
        # CRITICAL: Use full dataset statistics for accuracy when available
        if full_statistics is not None:
            statistics = full_statistics
            logger.info(f"Using statistics computed on full dataset ({len(rows)} rows)")
        else:
            # Fallback to sampled statistics for extremely large datasets
            statistics = compute_statistics(
                rows_for_analysis, aggregated=aggregated_flag
            )
            logger.warning(f"Using statistics from sample ({len(rows_for_analysis)} rows) - dataset too large")
        statistics = sanitize_dict(statistics) if statistics else {}
        _progress("statistics_computed", 55.0)

        # 3. Assess data quality (completeness, consistency)
        quality = assess_data_quality(rows_for_analysis, aggregated=aggregated_flag)
        quality = sanitize_dict(quality) if quality else {}
        _progress("quality_assessed", 75.0)

        # 4. Recommend optimal chart
        chart_recommendation: Optional[dict[str, Any]] = recommend_chart(
            data=rows_for_analysis,
            insights={"insights": insights} if insights else None,
            aggregated=aggregated_flag,
        )
        chart_recommendation = sanitize_dict(chart_recommendation) if chart_recommendation else None
        _progress("chart_recommended", 90.0)

        # 5. LLM business-insight narration — ALWAYS fires (post
        # Step 1 rewrite). The LLM gets a ~3-5KB digest, not raw
        # rows, so there's no row-count cap. It grounds its findings
        # in the user's original ``question`` + deterministic stats.
        #
        # Observe whether narration actually produces business-
        # insight cards or silently degrades to statistical-only
        # output. The signal is surfaced in the tool response so
        # the agent / UI / ops can tell "this query intentionally
        # had no narrative" from "narrator skipped or failed".
        # Four states:
        #   ran_successfully — narrator added at least one LLM insight
        #   ran_but_empty     — narrator fired but returned no usable JSON
        #   skipped_no_llm_config — tool context has no LLM wired
        #   ran_without_question_anchor — narrated on a generic prompt
        has_llm_config = bool(getattr(context, "llm_config", None))
        has_question = bool(question and question.strip())
        if not has_question:
            logger.info(
                "execute_and_analyze: no question= provided; narrator "
                "falls back to generic stat-description prompt. "
                "Typically indicates the agent didn't thread the user's "
                "original ask. Check LLM prompt compliance."
            )

        pre_enhance_count = len(insights) if isinstance(insights, list) else 0
        insights = await enhance_insights_with_llm(
            context=context,
            rows=rows,
            columns=columns,
            sql=sql,
            statistics=statistics,
            existing_insights=insights,
            question=question,
            quality=quality,
            aggregated=aggregated_flag,
        )

        # CRITICAL: Sanitize insights after LLM enhancement
        # LLM-generated text may contain control characters that cause JSON serialization to fail
        insights = sanitize_dict(insights) if insights else []

        post_enhance_count = len(insights) if isinstance(insights, list) else 0
        if not has_llm_config:
            narrator_status = "skipped_no_llm_config"
            insights_type = "statistical_only"
        elif post_enhance_count == pre_enhance_count:
            # enhance_insights_with_llm returns existing_insights
            # unchanged on both "no LLM config" and "exception /
            # parse failure" — the length check distinguishes
            # "narrator actually added cards" from "no cards added".
            narrator_status = "ran_but_empty"
            insights_type = "statistical_only"
        else:
            narrator_status = (
                "ran_successfully"
                if has_question
                else "ran_without_question_anchor"
            )
            insights_type = "llm_business_plus_detectors"

        # NOTE: the previous "basic_stats synthesize" fallback is
        # removed. With the LLM narrator firing on every query (post
        # Step 1 rewrite) there's always either LLM business insights
        # or a detector finding — synthesising stat-dump cards on top
        # of that was noise that made real insights harder to find.
        # If both the LLM AND detectors return empty, the UI handles
        # it honestly via ``_generate_analysis_summary``'s
        # "no notable patterns" fallback.

        # Sampling disclaimer lives in its own ``sampling_used``
        # payload, not in the ``insights`` list. Mixing them caused
        # real business findings ("concentration risk") to compete
        # visually with meta-commentary ("Pattern detection based on
        # a random sample…"). Frontend renders this payload as its
        # own banner (``.sampling-notice`` in AIResponseCard.vue).
        has_full_stats = full_statistics is not None
        if used_sampling:
            sampling_used_payload: Optional[Dict[str, Any]] = {
                "used": True,
                "sample_size": sample_size,
                "total_rows": len(rows),
                "stats_on_full_dataset": has_full_stats,
                "warnings": list(sampling_warnings or []),
                "recommendation": (
                    "For time-series or ordered data, consider narrowing "
                    "your query with a date filter (e.g. WHERE date > "
                    "'2024-01-01') so the analyser sees the recent window "
                    "in full rather than a random sample."
                    if sampling_warnings
                    else None
                ),
            }
        else:
            sampling_used_payload = None

        # Sanitize rows for JSON serialization (same as execute_sql)
        sanitized_rows = [
            {col: sanitize_value(row.get(col)) for col in columns}
            for row in rows
        ] if rows else []

        # Phase 4.1: offload the full row set to the ResultCache so the
        # tool payload fits the 50KB budget regardless of how many rows
        # came back. The LLM gets a 20-row preview (enough context for
        # narration) plus a ``rows_ref`` handle it can drill into via
        # the Phase 4.2 follow-up tools; the frontend table fetches the
        # full set via /api/v1/results/{rows_ref}.
        rows_ref: Optional[str] = None
        preview_rows = sanitized_rows
        if settings.FIX_RESULT_CACHE and sanitized_rows:
            try:
                from app.services.result_cache import result_cache

                query_id = str(uuid.uuid4())
                # Phase 4 Batch E: astore wraps the sync redis SETEX in
                # asyncio.to_thread so the ~200ms write on a 9000-row
                # payload doesn't stall the SSE heartbeat merger.
                rows_ref = await result_cache.astore(
                    session_id=context.session_id,
                    query_id=query_id,
                    sql=sql,
                    columns=columns,
                    rows=sanitized_rows,
                    row_count=row_count,
                    db_type=getattr(db_config, "db_type", None),
                    metadata={
                        "execution_time_ms": execution_time,
                        "analyzed_rows": row_count,
                        "sample_size": sample_size,
                        "used_sampling": used_sampling,
                    },
                )
                # Keep 20 rows inline for the LLM — enough for narrative
                # ("there's a row with policy_id=9342 that's an outlier")
                # without carrying the full result in context.
                preview_rows = sanitized_rows[:20]
                # Structured log at the cache-write boundary — lets
                # ops correlate "execute_and_analyze cached this
                # rows_ref" with later "cache.slice hit" on the same
                # rows_ref to verify follow-up routing works.
                logger.info(
                    "cache.store.executed",
                    extra={
                        "rows_ref": rows_ref,
                        "row_count": row_count,
                        "preview_count": len(preview_rows),
                        "used_sampling": used_sampling,
                    },
                )
            except Exception as e:
                # Never fail the tool because the cache glitched. CRITICAL:
                # still truncate the preview — if we kept the full
                # ``sanitized_rows`` here, the registry's 50KB cap would
                # hard-reject the whole payload and discard the analysis
                # we just computed. That's the exact "Result too large
                # for processing" bug Phase 4.1 was meant to kill.
                # Surface ``rows_truncated`` so the frontend can show
                # "rows not available — refresh or re-run" instead of
                # silently displaying a 20-row sliver as if it were the
                # whole dataset.
                logger.warning(
                    f"ResultCache store failed (rows truncated to preview): {e}"
                )
                rows_ref = None
                preview_rows = sanitized_rows[:20]

        # Build response with both data AND analysis
        response = {
            "success": True,
            "analyzed_rows": row_count,
            "sampled_rows": sample_size,  # Number of rows actually analyzed
            "execution_time_ms": execution_time,
            "columns": columns,
            # Rows: preview when cached, full set when cache disabled
            # (legacy path). In either case row_count is truthful.
            "rows": preview_rows,
            "row_count": row_count,

            # Pre-computed analysis results
            "insights": insights,
            "statistics": statistics,
            "quality": quality,
            "chart": chart_recommendation,

            # Narrator observability. ``narrator_status`` and
            # ``insights_type`` let ops distinguish a genuine "no
            # patterns found" from silent degradation (missing
            # llm_config, parse failure, prompt-less narration).
            "narrator_status": narrator_status,
            "insights_type": insights_type,
            "question_threaded": has_question,

            # Sampling metadata as its own field, not as a synthetic
            # card in the insights list. ``None`` when the full
            # dataset was analysed; a dict with ``used``,
            # ``sample_size``, ``total_rows``, ``warnings``,
            # ``recommendation`` when sampling fired. Frontend
            # renders it as its own ``.sampling-notice`` banner.
            "sampling_used": sampling_used_payload,

            # The frontend needs to distinguish "chart would not
            # help here" from "recommender returned None". The
            # recommender doesn't currently expose a reason, so this
            # only flags presence/absence. Extending
            # ``recommend_chart`` to return a rationale is a follow-up.
            "chart_unavailable_reason": (
                None if chart_recommendation is not None
                else "no_chart_recommended"
            ),

            # Metadata
            "limit_applied": limit,
            "has_more": result.get('has_more', False),
            "message": (
                f"Analyzed {row_count} rows in {execution_time}ms"
                if not used_sampling
                else f"Analyzed {sample_size} sampled rows (of {row_count}) in {execution_time}ms"
            ),
        }

        # Phase 4.1: advertise the cache handle so follow-up tools and
        # the frontend can pull the full rows. ``preview_rows`` keeps
        # the UI table functional if it can't fetch via rows_ref.
        if rows_ref is not None:
            response["rows_ref"] = rows_ref
            response["preview_row_count"] = len(preview_rows)
            response["rows_cached"] = True
        elif settings.FIX_RESULT_CACHE and len(sanitized_rows) > len(preview_rows):
            # Cache was enabled but store failed; preview is a strict
            # subset of the real data. Tell the frontend so it can show
            # "rows not available, re-run query for full data" instead
            # of misrepresenting a preview as the complete result.
            response["rows_cached"] = False
            response["rows_truncated"] = True
            response["rows_truncated_reason"] = "cache_unavailable"

        # Phase 3a Day 3: surface aggregation flags in the tool payload so
        # downstream (Phase 3c insight thresholds, chart recommender,
        # system prompt templates) can differentiate aggregated-mode
        # results from raw rows. Phase 3c.1 hoisted the detection above
        # detect_insights; we just forward the already-computed values
        # here to keep a single source of truth.
        if settings.FIX_AGGREGATION_DETECTION:
            response["aggregated"] = aggregated_flag
            response["grouping_columns"] = grouping_columns
            response["aggregate_columns"] = aggregate_columns

        logger.info(
            f"execute_and_analyze complete: {row_count} rows, "
            f"{len(insights)} insights, {len(statistics)} stats"
        )

        # Serialize with proper handling of special characters and edge cases
        try:
            return json.dumps(
                response,
                ensure_ascii=False,  # Preserve unicode characters
                allow_nan=False,     # Fail on NaN/Infinity (convert beforehand)
                default=str          # Convert any remaining objects to strings
            )
        except (ValueError, TypeError) as e:
            # If JSON serialization still fails, clean the data and retry
            logger.error(f"Initial JSON serialization failed: {e}, attempting cleanup")

            # Recursive function to clean problematic values
            def clean_for_json(obj):
                """Clean data structure for JSON serialization"""
                if isinstance(obj, dict):
                    return {k: clean_for_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean_for_json(item) for item in obj]
                elif isinstance(obj, str):
                    # Remove control characters except newlines and tabs
                    import re
                    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', obj)
                elif isinstance(obj, (int, float, bool, type(None))):
                    # Handle NaN and Infinity
                    if isinstance(obj, float):
                        if obj != obj:  # NaN
                            return None
                        elif obj == float('inf'):
                            return "Infinity"
                        elif obj == float('-inf'):
                            return "-Infinity"
                    return obj
                else:
                    # Convert anything else to string
                    return str(obj)

            cleaned_response = clean_for_json(response)
            return json.dumps(cleaned_response, ensure_ascii=False)

    except ValueError as e:
        # Security validation failed. Log the full exception server-side
        # but surface only a sanitized message to the LLM — the system
        # prompt's "never leak internals" voice rule can be violated
        # downstream if raw exception text (DB server hostnames,
        # schema-path fragments, stack trace shards) reaches the LLM
        # via the tool-result message.
        logger.warning("SQL validation failed: %s", e)
        sanitized = ErrorSanitizer.sanitize_error(e)
        return json.dumps({
            "success": False,
            "error": sanitized,
            "message": f"Query rejected: {sanitized}"
        })

    except Exception as e:
        # Same sanitization contract as above — full exception is
        # captured in server logs via exc_info; LLM sees a clean string.
        logger.error("execute_and_analyze error: %s", e, exc_info=True)
        sanitized = ErrorSanitizer.sanitize_error(e)
        return json.dumps({
            "success": False,
            "error": sanitized,
            "message": f"Analysis failed: {sanitized}"
        })


async def get_sample_data(
    context: ToolContext,
    table_name: str,
    limit: int = 5
) -> str:
    """
    Get sample rows from a table to understand data format and values.

    Args:
        context: Tool execution context with database config
        table_name: Name of the table to get sample data from
        limit: Number of sample rows to return

    Returns:
        Formatted string with sample data
    """
    from app.models.schemas import DatabaseConfig
    from app.services.database_service import DatabaseService

    if not context.db_config:
        return "Error: No database connection. Please connect to a database first."

    try:
        # Create DatabaseConfig from context
        db_config = DatabaseConfig(**context.db_config) if isinstance(context.db_config, dict) else context.db_config

        # Sanitize table name to prevent SQL injection
        # Only allow alphanumeric, underscore, and dot (for schema.table)
        import re
        if not re.match(r'^[\w\.]+$', table_name):
            return f"Invalid table name: '{table_name}'. Table names can only contain letters, numbers, underscores, and dots."

        # Build query based on database type
        db_type = db_config.db_type.lower()

        if db_type == "mongodb":
            # MongoDB query format
            sql = f"db.{table_name}.find().limit({limit})"
        elif db_type == "dynamodb":
            # DynamoDB PartiQL format (uses double quotes for table names)
            sql = f'SELECT * FROM "{table_name}"'
        else:
            # SQL-based databases (PostgreSQL, MySQL, SQL Server, Oracle, Snowflake,
            # BigQuery, Databricks, Redshift, DuckDB, SQLite, Athena, Trino, Presto,
            # ClickHouse, Hive, Spark, Cassandra)
            sql = f"SELECT * FROM {table_name} LIMIT {limit}"

        # Always use fresh data for agent decisions
        result = await DatabaseService.execute_query(
            config=db_config,
            sql=sql,
            limit=limit,
            force_refresh=True,  # Agent needs fresh data to make accurate decisions
        )

        if not result or not result.get('rows'):
            return f"No data found in table '{table_name}'. The table might be empty."

        # Format the output
        columns = result.get('columns', [])
        rows = result.get('rows', [])

        # Redact PII cells before rendering. The shared table-scoped
        # helper consults the data dictionary first and falls back
        # to the name heuristic. Same mutation pattern as the
        # connection-scoped helper so both paths agree.
        pii_columns = await _load_pii_column_set_for_table(
            db_config, columns, table_name
        )
        _redact_pii_in_rows(rows, pii_columns)
        if pii_columns:
            logger.info(
                "get_sample_data: masked PII columns in %s: %s",
                table_name,
                sorted(pii_columns),
            )

        output_lines = [
            f"Sample data from '{table_name}' ({len(rows)} rows):",
            ""
        ]

        # Calculate column widths (rows are dict-like, access by column name)
        col_widths = {col: len(str(col)) for col in columns}
        for row in rows:
            for col in columns:
                val = row.get(col, '') if hasattr(row, 'get') else ''
                val_len = len(str(val) if val is not None else '')
                col_widths[col] = min(max(col_widths[col], val_len), 25)

        # Header
        header = " | ".join(str(col)[:col_widths[col]].ljust(col_widths[col]) for col in columns)
        output_lines.append(header)
        output_lines.append("-" * len(header))

        # Data rows (access by column name, not index)
        for row in rows:
            row_str = " | ".join(
                str(row.get(col, '') if hasattr(row, 'get') else '')[:col_widths[col]].ljust(col_widths[col])
                for col in columns
            )
            output_lines.append(row_str)

        # Add column info
        output_lines.append("")
        output_lines.append("Column summary:")
        for col in columns:
            # Get sample of unique values for this column (access by column name)
            values = [str(row.get(col, '')) for row in rows if hasattr(row, 'get')]
            unique_values = list(set(values))[:3]
            output_lines.append(f"  - {col}: sample values = {', '.join(unique_values)}")

        return "\n".join(output_lines)

    except Exception as e:
        logger.error(f"get_sample_data error: {e}", exc_info=True)
        return f"Error getting sample data from '{table_name}': {ErrorSanitizer.sanitize_error(e)}"
