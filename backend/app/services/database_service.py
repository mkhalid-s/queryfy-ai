"""
QueryfyAI - Database Service

Universal database connection and schema extraction.
Uses ConnectionPoolManager for efficient connection reuse.
Includes query result caching for performance optimization.
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from app.api.metrics import record_db_query
from app.core.config import settings
from app.core.telemetry import get_tracer
from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager
from app.services.executors import get_executor
from app.services.schema_extractors import get_extractor as get_schema_extractor
from app.services.security import SecurityService

logger = logging.getLogger(__name__)

# Get tracer for this module
_tracer = get_tracer(__name__)


def _get_cache_service():
    """Lazy import to avoid circular dependency"""
    try:
        from app.services.cache_service import cache_service

        return cache_service
    except ImportError:
        return None


class DatabaseService:
    """Handles connections to various database types and schema extraction"""

    @staticmethod
    def parse_connection_url(db_type: str, url: str) -> Dict[str, Any]:
        """Parse connection URL based on database type"""

        if db_type == "bigquery":
            # Format: bigquery://project-id/dataset
            try:
                parts = url.replace("bigquery://", "").split("/")
                if not parts or not parts[0]:
                    raise ValueError("BigQuery URL must include a project ID: bigquery://project-id/dataset")
                return {
                    "project": parts[0],
                    "dataset": parts[1] if len(parts) > 1 else None,
                }
            except (IndexError, AttributeError) as e:
                raise ValueError("Invalid BigQuery URL format. Expected: bigquery://project-id/dataset") from e

        if db_type == "snowflake":
            # Format: snowflake://user:pass@account/database/schema?warehouse=WH
            try:
                parsed = urlparse(url)
                path_parts = [p for p in parsed.path.strip("/").split("/") if p]
                params = parse_qs(parsed.query)
                return {
                    "user": parsed.username,
                    "password": parsed.password,
                    "account": parsed.hostname,
                    "database": path_parts[0] if path_parts else None,
                    "schema": path_parts[1] if len(path_parts) > 1 else "PUBLIC",
                    "warehouse": params.get("warehouse", [None])[0],
                    "role": params.get("role", [None])[0],
                }
            except (IndexError, AttributeError) as e:
                raise ValueError("Invalid Snowflake URL format. Expected: snowflake://user:pass@account/database/schema") from e

        if db_type == "mongodb":
            return {"uri": url}

        # Standard SQL databases (postgresql, mysql, sqlserver, oracle)
        parsed = urlparse(url)
        return {
            "host": parsed.hostname,
            "port": parsed.port,
            "database": parsed.path.strip("/").split("/")[0] if parsed.path else None,
            "user": parsed.username,
            "password": parsed.password,
            "options": parse_qs(parsed.query),
        }

    @staticmethod
    def validate_connection_url(db_type: str, url: str) -> tuple[bool, str]:
        """Validate connection URL format and return (is_valid, error_message)"""
        if not url or not url.strip():
            return False, "Connection URL is empty"

        try:
            parsed = urlparse(url)

            # Embedded databases (file-based, no hostname required)
            embedded_dbs = ["duckdb", "sqlite"]
            if db_type in embedded_dbs:
                # DuckDB/SQLite use file paths: duckdb:///path/to/file.duckdb or duckdb://:memory:
                if not parsed.scheme:
                    return (
                        False,
                        f"Invalid URL format. Use: {db_type}:///path/to/database.{db_type}",
                    )
                # :memory: is valid for in-memory databases
                if parsed.netloc == ":memory:" or url.endswith(":memory:"):
                    return True, "OK"
                # Must have a path for file-based
                if not parsed.path or parsed.path == "/":
                    return (
                        False,
                        f"No file path found. Format: {db_type}:///path/to/database.{db_type}",
                    )
                return True, "OK"

            # DynamoDB - supports both local and AWS
            if db_type == "dynamodb":
                if not parsed.hostname:
                    return (
                        False,
                        "No hostname/region found. Formats: dynamodb://localhost:8000 (local) or dynamodb://us-east-1 (AWS)",
                    )
                # Valid hostnames: localhost, AWS regions (us-east-1, eu-west-1, etc.)
                return True, "OK"

            # Check for common issues (server-based databases)
            if not parsed.hostname:
                return (
                    False,
                    "No hostname found in URL. Format: postgresql://user:pass@hostname:port/database",
                )

            if parsed.hostname in ["hostname", "host", "your-host", "example.com"]:
                return (
                    False,
                    f"Please replace '{parsed.hostname}' with your actual database hostname (e.g., 'localhost' or IP address)",
                )

            # Some databases don't require username (MongoDB with localhost, Cassandra, ClickHouse)
            no_auth_dbs = ["mongodb", "cassandra", "clickhouse"]
            if not parsed.username and db_type not in no_auth_dbs:
                return (
                    False,
                    "No username found in URL. Format: postgresql://user:pass@hostname:port/database",
                )

            if not parsed.path or parsed.path == "/":
                return (
                    False,
                    "No database name found in URL. Format: postgresql://user:pass@hostname:port/database",
                )

            # Check if hostname looks like a placeholder
            if (
                "your" in parsed.hostname.lower()
                or "example" in parsed.hostname.lower()
            ):
                return (
                    False,
                    f"'{parsed.hostname}' looks like a placeholder. Use your actual database hostname.",
                )

            return True, "OK"

        except Exception as e:
            logger.error(f"URL validation failed: {e}")
            return False, "Invalid connection URL format. Please check the URL syntax."

    @staticmethod
    def get_pool_manager():
        """Get the connection pool manager instance"""
        return pool_manager

    @staticmethod
    def get_pooled_connection(config: DatabaseConfig):
        """
        Get a pooled database connection (recommended).

        Usage:
            async with DatabaseService.get_pooled_connection(config) as conn:
                result = await conn.fetch("SELECT * FROM users")
        """
        # Validate first
        is_valid, error_msg = DatabaseService.validate_connection_url(
            config.db_type, config.connection_url
        )
        if not is_valid:
            raise ValueError(error_msg)

        return pool_manager.get_connection(config)

    @staticmethod
    async def test_connection(config: DatabaseConfig) -> Dict[str, Any]:
        """
        Test database connection using the executor pattern.

        Uses the Strategy Pattern with database-specific executors
        for consistent connection testing across all database types.
        """
        try:
            executor = get_executor(config.db_type)
            return await executor.test_connection(config.connection_url)
        except ValueError as e:
            # Unsupported database type
            logger.error(f"Connection test failed: {e}")
            return {"success": False, "message": str(e)}
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            from app.services.security import ErrorSanitizer
            return {"success": False, "message": ErrorSanitizer.sanitize_error(e)}

    @staticmethod
    async def extract_schema(config: DatabaseConfig) -> Dict[str, Any]:
        """
        Extract complete schema from database.

        Delegates to extract_schema_with_extractor() which uses the
        Template Method pattern for cleaner, extensible schema extraction.
        """
        return await DatabaseService.extract_schema_with_extractor(config)

    @staticmethod
    async def extract_schema_with_extractor(config: DatabaseConfig) -> Dict[str, Any]:
        """
        Extract schema using the Template Method pattern extractor.

        This is the new implementation using schema extractors.
        Provides cleaner separation of concerns and easier extensibility.

        Args:
            config: Database configuration

        Returns:
            Schema dictionary with tables, columns, keys, and views
        """
        logger.info(f"extract_schema_with_extractor - db_type: {config.db_type}")

        extractor = get_schema_extractor(config.db_type)

        if not extractor:
            logger.warning(f"No schema extractor for: {config.db_type}")
            return {
                "db_type": config.db_type,
                "tables": [],
                "views": [],
                "collections": [],
                "error": f"Schema extraction not yet implemented for {config.db_type}",
                "extracted_at": datetime.now().isoformat(),
            }

        return await extractor.extract(config.connection_url)

    # SECURITY: Maximum query execution time (seconds)
    # Configurable via QUERY_TIMEOUT_SECONDS env variable
    QUERY_TIMEOUT_SECONDS = settings.QUERY_TIMEOUT_SECONDS

    @staticmethod
    def _get_cache_key(config: DatabaseConfig, sql: str, limit: int) -> str:
        """
        Generate database-level cache key (shared across sessions).

        Cache key format: query:{db_hash}:{sql_hash}:{limit}
        """
        db_hash = hashlib.sha256(config.connection_url.encode()).hexdigest()[:16]
        sql_hash = hashlib.sha256(sql.encode()).hexdigest()[:16]
        return f"{db_hash}:{sql_hash}:{limit}"

    @staticmethod
    async def invalidate_cache(config: DatabaseConfig):
        """Invalidate all cached queries for a database"""
        cache_service = _get_cache_service()
        if cache_service:
            db_hash = hashlib.sha256(config.connection_url.encode()).hexdigest()[:16]
            await cache_service.invalidate_prefix(f"query:{db_hash}:")
            logger.info(f"Invalidated query cache for database: {db_hash}")

    @staticmethod
    async def execute_query(
        config: DatabaseConfig, sql: str, limit: int = 500, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Execute read-only query and return results.

        Uses the Strategy Pattern with database-specific executors for cleaner
        separation of concerns and easier extensibility.

        Features:
        - Connection pooling for efficient resource usage
        - Query result caching (database-level, shared across sessions)
        - force_refresh=True bypasses cache for fresh data

        Args:
            config: Database configuration
            sql: SQL query to execute
            limit: Maximum rows to return
            force_refresh: If True, bypass cache and get fresh data

        Returns:
            Dict with columns, rows, row_count, execution_time, from_cache flag
        """
        # Start tracing span
        span = _tracer.start_span("db.execute_query")
        span.set_attribute("db.system", config.db_type)
        span.set_attribute("db.query_length", len(sql))
        span.set_attribute("db.limit", limit)

        logger.info(
            f"execute_query called - db_type: {config.db_type}, sql length: {len(sql)}"
        )

        try:
            # 1. Check cache (unless force_refresh)
            cache_service = _get_cache_service()
            cache_key = DatabaseService._get_cache_key(config, sql, limit)

            if cache_service and not force_refresh:
                try:
                    cached = await cache_service.get_query_result(cache_key)
                    if cached:
                        logger.debug(f"Query cache hit: {cache_key[:16]}")
                        span.set_attribute("db.from_cache", True)
                        # Record cache hit metric
                        record_db_query(
                            db_type=config.db_type,
                            status="success",
                            duration_seconds=0,  # Cache hit is instant
                            rows_returned=cached.get("row_count", 0),
                            cache_hit=True,
                        )
                        return {
                            **cached,
                            "from_cache": True,
                            "cache_key": cache_key[:16],
                        }
                except Exception as e:
                    logger.warning(f"Cache read error: {e}")

            # 2. Validate query is read-only (pass db_type for MongoDB support)
            is_safe, message = SecurityService.validate_generated_sql(
                sql, config.db_type
            )
            if not is_safe:
                logger.warning(f"Query validation failed: {message}")
                raise ValueError(message)
            logger.debug("Query validation passed")

            # 3. Get executor for this database type (Strategy Pattern)
            try:
                executor = get_executor(config.db_type)
            except ValueError:
                raise ValueError(f"Unsupported database type: {config.db_type}")

            # 4. Execute query using executor
            start_time = datetime.now()

            try:
                result = await executor.execute(
                    connection_url=config.connection_url,
                    query=sql,
                    limit=limit,
                    timeout=DatabaseService.QUERY_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Query timeout after {DatabaseService.QUERY_TIMEOUT_SECONDS}s"
                )
                raise ValueError(
                    f"Query exceeded maximum execution time of {DatabaseService.QUERY_TIMEOUT_SECONDS} seconds"
                )

            execution_time = (datetime.now() - start_time).total_seconds()

            # 5. Handle executor result
            if not result.get("success", True):
                raise ValueError(result.get("error", "Query execution failed"))

            # 6. Format response
            results = {
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "has_more": result.get("has_more", False),
                "execution_time": execution_time,
                "from_cache": False,
            }

            # 7. Serialize special types
            for row in results["rows"]:
                for key, value in row.items():
                    if hasattr(value, "isoformat"):
                        row[key] = value.isoformat()
                    elif hasattr(value, "__float__"):
                        row[key] = float(value)

            # 8. Cache the result (always cache, even on force_refresh for next time)
            if cache_service and results.get("rows"):
                try:
                    await cache_service.set_query_result(
                        cache_key, results, ttl=settings.CACHE_TTL_QUERY
                    )
                    logger.debug(f"Query result cached: {cache_key[:16]}")
                except Exception as e:
                    logger.warning(f"Cache write error: {e}")

            # Record span attributes
            span.set_attribute("db.rows_returned", results.get("row_count", 0))
            span.set_attribute("db.execution_time", execution_time)
            span.set_attribute("db.from_cache", False)

            # Record Prometheus metrics
            record_db_query(
                db_type=config.db_type,
                status="success",
                duration_seconds=execution_time,
                rows_returned=results.get("row_count", 0),
                cache_hit=False,
            )

            return results

        except Exception as e:
            span.record_exception(e)
            # Record Prometheus error metric
            record_db_query(
                db_type=config.db_type,
                status="error",
                duration_seconds=0,
                cache_hit=False,
            )
            raise
        finally:
            span.end()
