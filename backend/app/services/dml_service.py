"""
QueryfyAI - DML (Data Modification Language) Service

Handles INSERT, UPDATE, DELETE operations with safety modes:
- Preview: Shows what would change without executing
- Sandbox: Executes in transaction and rolls back
- Confirm: Executes with explicit user confirmation

Security Features:
- Confirmation tokens with 5-minute expiry
- Single-use tokens (prevent replay attacks)
- WHERE clause required for UPDATE/DELETE
- DROP/TRUNCATE/ALTER always blocked

IMPORTANT - Distributed Deployment Limitation:
Token storage uses the application's CacheService, which may be backed by:
- Redis: Full distributed support (recommended for multi-instance deployments)
- In-memory: Single-instance only - tokens will NOT be shared across instances

For production deployments with multiple backend instances, ensure Redis is
configured (REDIS_URL environment variable) to enable token sharing.
See: backend/app/services/cache_service.py for configuration details.
"""

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from app.core.logging_config import get_logger
from app.models.schemas import DatabaseConfig, DMLPreviewResult
from app.services.cache_service import cache_service
from app.services.database_service import DatabaseService
from app.services.security import SecurityService

logger = get_logger(__name__)


# DML capability matrix for each database type
DML_CAPABILITIES = {
    # Tier 1: Full DML support (Preview + Sandbox + Confirm)
    "postgresql": {
        "modes": ["preview", "sandbox", "confirm"],
        "has_transactions": True,
        "notes": "Full ACID transaction support",
    },
    "mysql": {
        "modes": ["preview", "sandbox", "confirm"],
        "has_transactions": True,
        "notes": "Full ACID transaction support",
    },
    "sqlserver": {
        "modes": ["preview", "sandbox", "confirm"],
        "has_transactions": True,
        "notes": "Full ACID transaction support",
    },
    "oracle": {
        "modes": ["preview", "sandbox", "confirm"],
        "has_transactions": True,
        "notes": "Full ACID transaction support",
    },
    "sqlite": {
        "modes": ["preview", "sandbox", "confirm"],
        "has_transactions": True,
        "notes": "Full ACID transaction support (file-based)",
    },
    "duckdb": {
        "modes": ["preview", "sandbox", "confirm"],
        "has_transactions": True,
        "notes": "Full ACID transaction support (analytical)",
    },
    "mongodb": {
        "modes": ["preview", "sandbox", "confirm"],
        "has_transactions": True,
        "notes": "Requires replica set or sharded cluster for transactions (MongoDB 4.0+)",
        "warning": "Standalone MongoDB servers do not support sandbox mode",
    },
    # Tier 2: No sandbox support (Preview + Confirm only) - deferred
    "snowflake": {
        "modes": ["preview", "confirm"],
        "has_transactions": False,
        "warning": "No rollback support - changes are immediate",
    },
    "redshift": {
        "modes": ["preview", "confirm"],
        "has_transactions": False,
        "warning": "VACUUM recommended after large deletes",
    },
    "databricks": {
        "modes": ["preview", "confirm"],
        "has_transactions": True,
        "warning": "Delta Lake ACID - sandbox mode deferred",
    },
    "clickhouse": {
        "modes": ["preview", "confirm"],
        "has_transactions": False,
        "warning": "Async mutations - changes may take time to apply",
    },
    "bigquery": {
        "modes": ["preview", "confirm"],
        "has_transactions": False,
        "warning": "Job-based execution - quotas apply",
    },
    "trino": {
        "modes": ["preview", "confirm"],
        "has_transactions": False,
        "warning": "Connector-dependent - verify with your catalog",
    },
    # Tier 3: No DML support
    "cassandra": {
        "modes": [],
        "has_transactions": False,
        "blocked": "CQL DML not supported - use native Cassandra tools",
    },
    "dynamodb": {
        "modes": [],
        "has_transactions": False,
        "blocked": "PartiQL does not support mutations - use AWS SDK",
    },
    "hive": {
        "modes": [],
        "has_transactions": False,
        "blocked": "Hive DML requires ACID tables - not supported",
    },
}


# Confirmation token prefix for Redis
CONFIRMATION_KEY_PREFIX = "dml:confirm:"


class DMLService:
    """Service for handling DML operations with safety modes."""

    CONFIRMATION_EXPIRY = timedelta(minutes=5)

    @staticmethod
    def get_capabilities(db_type: str) -> Dict[str, Any]:
        """
        Get DML capabilities for a database type.

        Args:
            db_type: Database type (postgresql, mysql, etc.)

        Returns:
            Dict with modes, has_transactions, notes, warning, blocked
        """
        return DML_CAPABILITIES.get(
            db_type.lower(),
            {
                "modes": [],
                "has_transactions": False,
                "blocked": "Unknown database type",
            },
        )

    @staticmethod
    def validate_mode(db_type: str, mode: str) -> Tuple[bool, str]:
        """
        Validate if a DML mode is supported for a database type.

        Args:
            db_type: Database type
            mode: DML mode (preview, sandbox, confirm)

        Returns:
            Tuple of (is_valid, message)
            - If valid: (True, warning_message_or_empty)
            - If invalid: (False, error_message)
        """
        caps = DMLService.get_capabilities(db_type)

        # Check if blocked entirely
        if caps.get("blocked"):
            return False, caps["blocked"]

        # Check if mode is supported
        if mode not in caps.get("modes", []):
            available = caps.get("modes", [])
            if not available:
                return False, f"DML operations not supported for {db_type}"
            return (
                False,
                f"Mode '{mode}' not supported for {db_type}. Available: {', '.join(available)}",
            )

        # Valid - return any warning
        return True, caps.get("warning", "")

    @staticmethod
    async def preview_dml(config: DatabaseConfig, sql: str) -> DMLPreviewResult:
        """
        Preview what a DML statement would do without executing.

        For UPDATE/DELETE: Shows affected rows
        For INSERT: Shows data to be inserted

        Args:
            config: Database configuration
            sql: DML SQL statement

        Returns:
            DMLPreviewResult with operation details
        """
        operation = SecurityService.detect_dml_operation(sql)

        if not operation:
            raise ValueError("Not a DML statement")

        if operation in SecurityService.BLOCKED_DML_OPERATIONS:
            raise ValueError(f"{operation} operations are not allowed")

        # Get preview SQL (converts DML to SELECT)
        preview_sql = SecurityService.get_dml_preview_sql(sql)

        if operation == "INSERT":
            # For INSERT, parse the SQL to show what would be inserted
            return DMLPreviewResult(
                operation=operation,
                table=DMLService._extract_table(sql),
                estimated_rows_affected=DMLService._count_insert_rows(sql),
                sample_changes=[{"action": "INSERT", "data": "See SQL for values"}],
                warnings=[],
                sql=sql,
            )

        if not preview_sql:
            raise ValueError(f"Cannot generate preview for {operation}")

        # Execute preview query to see affected rows
        try:
            result = await DatabaseService.execute_query(
                config, preview_sql, limit=100  # Preview limit
            )

            warnings = DMLService._generate_warnings(operation, result)

            return DMLPreviewResult(
                operation=operation,
                table=DMLService._extract_table(sql),
                estimated_rows_affected=result.get("row_count", 0),
                sample_changes=result.get("rows", [])[:10],
                warnings=warnings,
                sql=sql,
            )

        except Exception as e:
            logger.error(f"Preview query failed: {e}")
            raise ValueError(f"Failed to preview: {str(e)}")

    @staticmethod
    async def execute_sandbox(config: DatabaseConfig, sql: str) -> Dict[str, Any]:
        """
        Execute DML in a transaction and immediately rollback.
        Shows what would happen without persisting changes.

        Args:
            config: Database configuration
            sql: DML SQL statement

        Returns:
            Dict with rows_affected, execution_time, etc.
        """
        from app.services.executors import get_executor

        try:
            executor = get_executor(config.db_type)
        except ValueError:
            raise ValueError(f"Unsupported database type for DML: {config.db_type}")

        # Check if executor supports DML
        if not hasattr(executor, "execute_dml"):
            raise ValueError(f"DML not supported for {config.db_type}")

        start_time = datetime.now()

        # Execute with rollback flag
        result = await executor.execute_dml(
            connection_url=config.connection_url,
            sql=sql,
            rollback=True,  # Always rollback
        )

        execution_time = (datetime.now() - start_time).total_seconds()

        return {
            "success": True,
            "rows_affected": result.get("rows_affected", 0),
            "message": "Sandbox execution completed (changes rolled back)",
            "rollback_performed": True,
            "execution_time": execution_time,
        }

    @staticmethod
    async def generate_confirmation_token(session_id: str, sql: str) -> str:
        """
        Generate a confirmation token for DML execution.

        Token is:
        - Valid for 5 minutes
        - Single-use (deleted after validation)
        - Bound to specific session and SQL
        - Stored in Redis for distributed support

        Args:
            session_id: Session ID
            sql: SQL statement to confirm

        Returns:
            Confirmation token string
        """
        token = secrets.token_urlsafe(32)
        sql_hash = hashlib.sha256(sql.encode()).hexdigest()

        token_data = {
            "session_id": session_id,
            "sql_hash": sql_hash,
            "sql": sql,  # Optional: store full SQL for debugging
            "created_at": datetime.now().isoformat(),
        }

        # Store in Redis with 5 minute TTL
        key = f"{CONFIRMATION_KEY_PREFIX}{token}"
        ttl_seconds = int(DMLService.CONFIRMATION_EXPIRY.total_seconds())

        try:
            # Use cache service's underlying client or set method
            # Since CacheService abstracts this, we'll try to use its set method if available
            # or access the backend client directly if we need specific Redis commands

            # Assuming CacheService has a set method with TTL
            if cache_service._backend:
                await cache_service._backend.set(key, json.dumps(token_data), ttl=ttl_seconds)

            logger.info(
                "DML confirmation token generated",
                session_id=session_id[:8],
                expires_in_seconds=ttl_seconds,
            )
            return token

        except Exception as e:
            logger.error(f"Failed to store confirmation token: {e}")
            raise ValueError(
                "Could not generate confirmation token due to storage error"
            )

    @staticmethod
    async def validate_confirmation_token(
        token: str, session_id: str, sql: str
    ) -> bool:
        """
        Validate a confirmation token.

        Checks:
        - Token exists in Redis
        - Matches session ID
        - Matches SQL hash

        Args:
            token: Confirmation token to validate
            session_id: Expected session ID
            sql: Expected SQL statement

        Returns:
            True if valid, False otherwise
        """
        key = f"{CONFIRMATION_KEY_PREFIX}{token}"

        try:
            # Retrieve from Redis
            token_str = await cache_service._backend.get(key) if cache_service._backend else None
            token_data = json.loads(token_str) if token_str else None

            if not token_data:
                logger.warning("DML confirmation token not found or expired")
                return False

            # Check session match
            if token_data.get("session_id") != session_id:
                logger.warning("DML confirmation token session mismatch")
                return False

            # Check SQL hash match
            sql_hash = hashlib.sha256(sql.encode()).hexdigest()
            if token_data.get("sql_hash") != sql_hash:
                logger.warning("DML confirmation token SQL mismatch")
                return False

            # Valid - remove token (one-time use)
            if cache_service._backend:
                await cache_service._backend.delete(key)
            logger.info("DML confirmation token validated and consumed")
            return True

        except Exception as e:
            logger.error(f"Error validating confirmation token: {e}")
            return False

    @staticmethod
    async def execute_confirmed(config: DatabaseConfig, sql: str) -> Dict[str, Any]:
        """
        Execute DML after confirmation (persistent changes).

        This commits the changes to the database.

        Args:
            config: Database configuration
            sql: DML SQL statement

        Returns:
            Dict with rows_affected, execution_time, etc.
        """
        from app.services.executors import get_executor

        try:
            executor = get_executor(config.db_type)
        except ValueError:
            raise ValueError(f"Unsupported database type for DML: {config.db_type}")

        # Check if executor supports DML
        if not hasattr(executor, "execute_dml"):
            raise ValueError(f"DML not supported for {config.db_type}")

        start_time = datetime.now()

        # Execute with commit
        result = await executor.execute_dml(
            connection_url=config.connection_url,
            sql=sql,
            rollback=False,  # Commit changes
        )

        execution_time = (datetime.now() - start_time).total_seconds()

        rows_affected = result.get("rows_affected", 0)
        logger.info(
            "DML executed successfully",
            rows_affected=rows_affected,
            execution_time=execution_time,
        )

        return {
            "success": True,
            "rows_affected": rows_affected,
            "message": f"Successfully executed: {rows_affected} rows affected",
            "rollback_performed": False,
            "execution_time": execution_time,
        }

    @staticmethod
    def _extract_table(sql: str) -> str:
        """Extract table name from DML statement.

        Handles: simple (users), schema-qualified (public.users), quoted ("User Table")
        """
        # Pattern for table names: optional schema + table name (simple or quoted)
        table_pattern = r'((?:[\w]+\.)?(?:[\w]+|"[^"]+"))'
        patterns = [
            rf"INSERT\s+INTO\s+{table_pattern}",
            rf"UPDATE\s+{table_pattern}",
            rf"DELETE\s+FROM\s+{table_pattern}",
        ]
        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(1)
        return "unknown"

    @staticmethod
    def _count_insert_rows(sql: str) -> int:
        """Count number of rows being inserted."""
        # Count VALUES clauses
        values_matches = re.findall(r"\)\s*,\s*\(", sql)
        return len(values_matches) + 1 if "VALUES" in sql.upper() else 1

    @staticmethod
    def _generate_warnings(operation: str, result: Dict) -> List[str]:
        """Generate safety warnings based on preview results."""
        warnings = []
        row_count = result.get("row_count", 0)

        if row_count == 0:
            warnings.append(f"No rows will be affected by this {operation}")
        elif row_count > 100:
            warnings.append(f"This will affect {row_count} rows - please verify")
        if row_count > 1000:
            warnings.append(f"WARNING: Large operation affecting {row_count} rows!")

        return warnings

    @staticmethod
    def cleanup_expired_tokens():
        """
        Remove expired confirmation tokens.

        Deprecated: Redis handles expiration automatically via TTL.
        Kept for backward compatibility or in-memory fallback if needed.
        """
        pass
