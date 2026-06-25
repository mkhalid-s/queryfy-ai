"""
QueryfyAI - Conversation Tools

Tools for accessing conversation context and previous query results.
Enables agent to reference and build upon previous queries in conversation.
"""

import json
import logging
from typing import Any, Optional

from app.services.session_store import session_store
from app.services.tools.registry import ToolContext

logger = logging.getLogger(__name__)


async def _redact_sample_rows(
    db_config: Any,
    columns: "list",
    rows: "list",
    sql: Optional[str] = None,
) -> None:
    """
    Belt-and-braces PII redaction at the ``get_previous_result``
    return boundary. ``execute_and_analyze`` redacts upstream before
    writing to the cache, but ``session_store.get_cached_result``
    reads from a separate store that could be fed by a legacy or
    future code path we didn't audit. Re-applying redaction here
    closes the leak path regardless of how ``rows`` got populated.

    When the cached entry has the originating ``sql``, the query-
    scoped helper narrows the dictionary lookup to referenced tables.
    Older cache entries without ``sql`` fall through to connection-
    wide OR-semantics inside the helper.

    No-op when ``db_config`` is missing or the columns list is empty.
    """
    if not db_config or not columns or not rows:
        return
    try:
        from app.services.tools.query_tools import (
            _load_pii_column_set_for_query,
            _redact_pii_in_rows,
        )

        pii_columns = await _load_pii_column_set_for_query(
            db_config, list(columns), sql
        )
        _redact_pii_in_rows(rows, pii_columns)
        if pii_columns:
            logger.info(
                "get_previous_result.pii_masked",
                extra={
                    "pii_columns": sorted(pii_columns),
                    "affected_rows": len(rows),
                },
            )
    except Exception as e:
        # Defence-in-depth — never block the tool on a PII-lookup
        # failure. Fall through with unmasked rows only if the helper
        # itself is unreachable, which logs loudly via the helper.
        logger.warning("get_previous_result: PII redaction skipped: %s", e)


async def get_previous_result(
    context: ToolContext,
    query_reference: str = "last",
) -> str:
    """
    Retrieve result data from a previous query in this conversation.

    Use this tool when user asks to:
    - "Break down the previous result"
    - "Filter that data" or "from those results"
    - Analyze or transform prior query output
    - Reference "the data" or "those numbers"

    Args:
        context: Tool execution context with session_id
        query_reference: "last" or "previous" for most recent, or specific query_id

    Returns:
        JSON string with columns, row_count, and sample rows (max 10)
    """
    # Validate query_reference
    if query_reference not in ["last", "previous"] and not query_reference.startswith(
        "query_"
    ):
        logger.warning(
            f"Invalid query_reference: {query_reference}, defaulting to 'last'"
        )
        query_reference = "last"

    logger.info(
        f"get_previous_result called: session={context.session_id[:8]}, "
        f"reference={query_reference}"
    )

    result = session_store.get_cached_result(
        context.session_id,
        query_reference if query_reference != "previous" else "last",
    )

    if not result:
        logger.warning(
            f"No previous results found in cache for {context.session_id[:8]}"
        )
        return json.dumps(
            {
                "error": "No previous results found in cache.",
                "hint": "User may not have run a query yet in this conversation.",
            }
        )

    # Return structured result with sample data.
    # Phase 4.2: surface ``rows_ref`` so the LLM can chain into
    # inspect_cached_result / get_cached_rows for the FULL row set
    # rather than getting stuck with the 10-row sample. Without this,
    # follow-ups routed through this legacy tool see only 10 of 9000
    # rows and silently degrade.
    #
    # Belt-and-braces redaction of the 10-row sample before
    # returning. ``execute_and_analyze`` redacts upstream at the
    # cache write, but ``get_cached_result`` reads through a
    # different accessor that could be fed by a legacy or future
    # code path. Re-applying redaction here closes the tool's
    # observable output regardless of how rows entered the cache.
    sample_rows = list(result["rows"][:10])  # copy so we don't mutate cache
    # Pass the originating SQL through so the redaction helper can
    # narrow the dictionary lookup to referenced tables. Older cache
    # entries without ``sql`` fall through to connection-wide OR-
    # semantics inside the helper.
    await _redact_sample_rows(
        getattr(context, "db_config", None),
        result["columns"],
        sample_rows,
        result.get("sql"),
    )
    response = {
        "columns": result["columns"],
        "row_count": result["row_count"],
        "sample_rows": sample_rows,
        "sql_used": result.get("sql", "N/A"),
        "has_more": result["row_count"] > 10,
        "cached_at": result.get("timestamp", "N/A"),
        "rows_ref": result.get("rows_ref"),
        "next_step_hint": (
            "If rows_ref is present, prefer inspect_cached_result(rows_ref, ...) "
            "or get_cached_rows(rows_ref, ...) for follow-up analysis on this "
            "dataset — they see the FULL result, not the 10-row sample shown here."
        ),
    }

    logger.debug(
        f"Returning cached result: {result['row_count']} rows, "
        f"{len(result['columns'])} columns"
    )

    return json.dumps(response, indent=2)
