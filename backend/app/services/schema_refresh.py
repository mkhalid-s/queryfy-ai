"""
Single-table schema refresh primitive.

Lets analyst-mode flows refresh ONE table's metadata in the vector
DB without re-extracting the whole connection — typical triggers
are missing NoSQL partition keys on the indexed copy, or schema
drift discovered via column-not-found errors at query time.

Async, never raises, per-table distributed lock so two concurrent
refresh attempts on the same table collapse into one DB round-trip.

MongoDB is feature-flagged off via ``SCHEMA_AUTO_REFRESH_MONGO`` —
its "refresh" is document re-sampling, identical in cost to the
manual ``/schema/refresh`` endpoint. Operators can opt in.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.core.config import settings
from app.services.distributed_lock import refresh_table_lock
from app.services.schema_extractors import get_extractor

logger = logging.getLogger(__name__)

# Status reasons surfaced in the return dict + logs. Stable strings —
# operators may grep for them.
STATUS_OK = "ok"
STATUS_LOCKED_OUT = "locked_out"
STATUS_UNSUPPORTED_DB = "unsupported_db_type"
STATUS_NO_EXTRACTOR = "no_extractor"
STATUS_MONGO_DISABLED = "mongodb_disabled"
STATUS_FAILED = "failed"
STATUS_VECTOR_DB_UNAVAILABLE = "vector_db_unavailable"


def _refresh_result(
    success: bool,
    reason: str,
    *,
    db_type: str = "unknown",
    table_name: str = "",
    error: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "success": success,
        "reason": reason,
        "db_type": db_type,
        "table_name": table_name,
    }
    if error:
        payload["error"] = error
    return payload


async def _build_table_dict_sql(
    extractor: Any,
    db_type: str,
    schema_name: Optional[str],
    table_name: str,
    connection_url: str,
) -> Dict[str, Any]:
    """
    Construct a single-table dict matching ``store_schema``'s shape
    for SQL / Cassandra extractors. Uses the existing per-table
    methods on the extractor — no code duplication.
    """
    async with extractor._get_connection(connection_url) as conn:
        columns = await extractor._get_columns(conn, table_name, schema_name or "")
        try:
            primary_keys = await extractor._get_primary_keys(
                conn, table_name, schema_name or ""
            )
        except Exception as e:
            logger.debug(
                "refresh_table_schema: primary_keys fetch failed for %s: %s",
                table_name,
                e,
            )
            primary_keys = []
        try:
            foreign_keys = await extractor._get_foreign_keys(
                conn, table_name, schema_name or ""
            )
        except Exception as e:
            logger.debug(
                "refresh_table_schema: foreign_keys fetch failed for %s: %s",
                table_name,
                e,
            )
            foreign_keys = []

    table_dict: Dict[str, Any] = {
        "name": table_name,
        "schema": schema_name,
        "columns": columns,
        "primary_keys": primary_keys,
        "foreign_keys": foreign_keys,
        "db_type": db_type,
    }

    # Cassandra: derive partition / clustering keys from the per-column
    # ``key_type`` field. The full extractor sorts by position too —
    # mirror that.
    if db_type == "cassandra":
        partition_pairs = sorted(
            ((c.get("position", 0), c["name"]) for c in columns
             if c.get("key_type") == "partition_key")
        )
        clustering_pairs = sorted(
            ((c.get("position", 0), c["name"]) for c in columns
             if c.get("key_type") == "clustering")
        )
        table_dict["partition_keys"] = [n for _, n in partition_pairs]
        table_dict["clustering_keys"] = [n for _, n in clustering_pairs]

    return table_dict


async def _build_table_dict_dynamodb(
    extractor: Any,
    table_name: str,
    connection_url: str,
) -> Dict[str, Any]:
    """
    DynamoDB lives in a separate path because its key schema is on
    ``DescribeTable.KeySchema`` (not in a SELECT), and "columns" are
    inferred from sample items rather than introspection.
    """
    async with extractor._get_connection(connection_url) as client:
        meta = await extractor._describe_table(client, table_name)
        # Pull a small sample for column inference. Even at 50 items
        # this is much cheaper than a full extraction across all
        # tables.
        try:
            samples = await extractor._sample_items(client, table_name, limit=50)
            columns = extractor._infer_attributes_from_sample(samples)
        except Exception as e:
            logger.debug(
                "refresh_table_schema: DynamoDB sample failed for %s: %s",
                table_name,
                e,
            )
            columns = []

    key_schema = meta.get("KeySchema", []) or []
    partition_key = next(
        (k.get("AttributeName") for k in key_schema if k.get("KeyType") == "HASH"),
        None,
    )
    sort_key = next(
        (k.get("AttributeName") for k in key_schema if k.get("KeyType") == "RANGE"),
        None,
    )

    return {
        "name": table_name,
        "schema": "default",  # DynamoDB has no schemas
        "columns": columns,
        "partition_key": partition_key,
        "sort_key": sort_key,
        "db_type": "dynamodb",
    }


async def refresh_table_schema(
    db_config: Any,
    schema_name: Optional[str],
    table_name: str,
    *,
    reason: str = "unspecified",
) -> Dict[str, Any]:
    """
    Refresh the indexed metadata for a single table.

    Args:
        db_config: A DatabaseConfig (or shaped-alike) exposing
            ``db_type`` and ``connection_url`` strings.
        schema_name: Schema / keyspace / database; ``None`` for
            backends that don't use one (MongoDB, DynamoDB).
        table_name: Table / collection name. Required.
        reason: Free-form tag stored in the log line so ops can
            trace which trigger fired the refresh (e.g.
            ``"empty_partition_keys"``, ``"column_not_found"``).

    Returns:
        ``{"success": bool, "reason": str, "db_type": str,
            "table_name": str, "error": str | None}``.

    Never raises. On any failure path a structured log line is
    emitted and the dict tells the caller why nothing happened so
    they can decide whether to retry or surface it.
    """
    db_type = (getattr(db_config, "db_type", "") or "").lower()
    connection_url = getattr(db_config, "connection_url", "") or ""

    if not table_name:
        return _refresh_result(False, STATUS_FAILED,
                               db_type=db_type, table_name="",
                               error="empty table_name")
    if not connection_url:
        return _refresh_result(False, STATUS_FAILED,
                               db_type=db_type, table_name=table_name,
                               error="empty connection_url on db_config")

    if db_type in {"mongodb", "mongo"} and not getattr(
        settings, "SCHEMA_AUTO_REFRESH_MONGO", False
    ):
        # Default-off: re-sampling for Mongo costs the same as a full
        # /schema/refresh. Operators opt in via the env flag.
        logger.info(
            "schema_refresh.skipped",
            extra={
                "table_name": table_name,
                "db_type": db_type,
                "reason": reason,
                "skip_reason": STATUS_MONGO_DISABLED,
            },
        )
        return _refresh_result(False, STATUS_MONGO_DISABLED,
                               db_type=db_type, table_name=table_name)

    extractor = get_extractor(db_type)
    if extractor is None:
        logger.warning(
            "schema_refresh.no_extractor",
            extra={
                "table_name": table_name,
                "db_type": db_type,
                "reason": reason,
            },
        )
        return _refresh_result(False, STATUS_NO_EXTRACTOR,
                               db_type=db_type, table_name=table_name)

    # Hash here so the lock key matches what the consumers see.
    from app.services.vector_db import vector_db
    conn_hash = vector_db._hash_connection(connection_url)

    async with await refresh_table_lock(conn_hash, schema_name, table_name) as lock:
        if not getattr(lock, "acquired", True):
            # Another worker is already refreshing this table — skip
            # rather than pile up redundant DB metadata calls.
            logger.info(
                "schema_refresh.locked_out",
                extra={
                    "table_name": table_name,
                    "db_type": db_type,
                    "reason": reason,
                },
            )
            return _refresh_result(False, STATUS_LOCKED_OUT,
                                   db_type=db_type, table_name=table_name)

        try:
            if db_type == "dynamodb":
                table_dict = await _build_table_dict_dynamodb(
                    extractor, table_name, connection_url
                )
            elif db_type in {"mongodb", "mongo"}:
                # Flag was on; the per-collection live-refresh path
                # is not implemented yet. Single-collection live
                # refresh is a follow-up if metrics show the cost is
                # justified relative to the manual full refresh.
                logger.warning(
                    "schema_refresh.mongo_unsupported_path",
                    extra={"table_name": table_name, "reason": reason},
                )
                return _refresh_result(False, STATUS_UNSUPPORTED_DB,
                                       db_type=db_type, table_name=table_name)
            else:
                table_dict = await _build_table_dict_sql(
                    extractor,
                    db_type,
                    schema_name,
                    table_name,
                    connection_url,
                )
        except Exception as e:
            logger.error(
                "schema_refresh.fetch_failed",
                extra={
                    "table_name": table_name,
                    "db_type": db_type,
                    "reason": reason,
                    "error": str(e),
                },
            )
            return _refresh_result(False, STATUS_FAILED,
                                   db_type=db_type,
                                   table_name=table_name,
                                   error=str(e))

        ok = vector_db.update_table_in_schema(connection_url, table_dict)
        if not ok:
            logger.warning(
                "schema_refresh.vector_db_write_failed",
                extra={
                    "table_name": table_name,
                    "db_type": db_type,
                    "reason": reason,
                },
            )
            return _refresh_result(False, STATUS_VECTOR_DB_UNAVAILABLE,
                                   db_type=db_type, table_name=table_name)

        logger.info(
            "schema_refresh.ok",
            extra={
                "table_name": table_name,
                "db_type": db_type,
                "reason": reason,
                "schema_name": schema_name or "",
            },
        )
        return _refresh_result(True, STATUS_OK,
                               db_type=db_type, table_name=table_name)
