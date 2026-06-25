"""
QueryfyAI - Centralized Constants

This module contains all hardcoded constants used throughout the application,
providing a single source of truth for database configurations, system schemas,
timeouts, and rate limits.
"""

import logging
import os
from typing import Dict, List, Tuple

_logger = logging.getLogger(__name__)


def _safe_int_env(name: str, default: int) -> int:
    """Parse an integer environment variable with fallback on invalid values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        _logger.warning(f"Invalid integer for {name}={raw!r}, using default {default}")
        return default


# ============================================
# DATABASE DEFAULT PORTS
# ============================================
DEFAULT_PORTS: Dict[str, int] = {
    "postgresql": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "mongodb": 27017,
    "sqlserver": 1433,
    "oracle": 1521,
    "redshift": 5439,
    "snowflake": 443,
    "bigquery": 443,
    "databricks": 443,
    "clickhouse": 8123,
    "athena": 443,
    "trino": 8080,
    "presto": 8080,
    "hive": 10000,
    "spark": 10000,
    "cassandra": 9042,
    "dynamodb": 8000,  # Local DynamoDB; AWS uses HTTPS on 443
}


# ============================================
# SYSTEM SCHEMAS TO EXCLUDE (per database type)
# These are internal schemas that should not be exposed
# ============================================
SYSTEM_SCHEMAS: Dict[str, List[str]] = {
    "postgresql": ["pg_catalog", "information_schema", "pg_toast"],
    "mysql": ["information_schema", "mysql", "performance_schema", "sys"],
    "mariadb": ["information_schema", "mysql", "performance_schema"],
    "sqlserver": ["sys", "INFORMATION_SCHEMA", "guest", "db_owner", "db_accessadmin"],
    "oracle": ["SYS", "SYSTEM", "DBSNMP", "XDB", "OUTLN", "CTXSYS", "MDSYS", "ORDSYS"],
    "redshift": ["pg_catalog", "information_schema", "pg_internal"],
    "snowflake": ["INFORMATION_SCHEMA"],
    "bigquery": [],  # BigQuery doesn't have system schemas in the same way
    "databricks": ["information_schema", "default"],
    "clickhouse": ["system", "INFORMATION_SCHEMA"],
    "athena": ["information_schema"],
    "trino": ["information_schema"],
    "presto": ["information_schema"],
    "hive": ["information_schema", "sys"],
    "spark": ["information_schema", "default"],
    "mongodb": ["admin", "local", "config"],  # MongoDB system databases
    "cassandra": [
        "system",
        "system_auth",
        "system_distributed",
        "system_schema",
        "system_traces",
    ],
    "dynamodb": [],  # DynamoDB doesn't have system tables
}


# ============================================
# DATABASE TYPE ALIASES
# Maps alternate names to canonical database types
# ============================================
DATABASE_TYPE_ALIASES: Dict[str, str] = {
    "postgres": "postgresql",
    "pg": "postgresql",
    "maria": "mariadb",
    "mssql": "sqlserver",
    "ms-sql": "sqlserver",
    "bq": "bigquery",
    "ch": "clickhouse",
    "aws-athena": "athena",
}


# ============================================
# TIMEOUTS (in seconds)
# ============================================
CONNECTION_TIMEOUT: int = _safe_int_env("DB_CONNECTION_TIMEOUT", 10)
QUERY_TIMEOUT: int = _safe_int_env("DB_QUERY_TIMEOUT", 30)
SCHEMA_EXTRACTION_TIMEOUT: int = _safe_int_env("SCHEMA_EXTRACTION_TIMEOUT", 60)
LLM_TIMEOUT: int = _safe_int_env("LLM_TIMEOUT", 120)


# ============================================
# RATE LIMITS
# Format: (max_requests, window_seconds)
# ============================================
RATE_LIMITS: Dict[str, Tuple[int, int]] = {
    "generate": (10, 60),  # 10 SQL generations per minute
    "execute": (30, 60),  # 30 query executions per minute
    "export": (5, 60),  # 5 exports per minute
    "followup": (20, 60),  # 20 follow-ups per minute
    "classify": (30, 60),  # 30 classifications per minute
    "session_create": (5, 60),  # 5 session creations per minute per IP
    "default": (60, 60),  # Default: 60 requests per minute
}


# ============================================
# QUERY LANGUAGE TYPES
# ============================================
QUERY_LANGUAGE_SQL = "sql"
QUERY_LANGUAGE_MONGODB = "mongodb"
QUERY_LANGUAGE_CQL = "cql"  # Cassandra Query Language
QUERY_LANGUAGE_PARTIQL = "partiql"  # DynamoDB PartiQL


# ============================================
# DATABASE TO QUERY LANGUAGE MAPPING
# ============================================
DB_QUERY_LANGUAGES: Dict[str, str] = {
    "postgresql": QUERY_LANGUAGE_SQL,
    "mysql": QUERY_LANGUAGE_SQL,
    "mariadb": QUERY_LANGUAGE_SQL,
    "sqlserver": QUERY_LANGUAGE_SQL,
    "oracle": QUERY_LANGUAGE_SQL,
    "redshift": QUERY_LANGUAGE_SQL,
    "snowflake": QUERY_LANGUAGE_SQL,
    "bigquery": QUERY_LANGUAGE_SQL,
    "databricks": QUERY_LANGUAGE_SQL,
    "clickhouse": QUERY_LANGUAGE_SQL,
    "athena": QUERY_LANGUAGE_SQL,
    "trino": QUERY_LANGUAGE_SQL,
    "presto": QUERY_LANGUAGE_SQL,
    "hive": QUERY_LANGUAGE_SQL,
    "spark": QUERY_LANGUAGE_SQL,
    "mongodb": QUERY_LANGUAGE_MONGODB,
    "cassandra": QUERY_LANGUAGE_CQL,
    "dynamodb": QUERY_LANGUAGE_PARTIQL,
}


# ============================================
# ASYNC VS SYNC DATABASE DRIVERS
# Databases that support native async drivers
# ============================================
ASYNC_DATABASES: List[str] = [
    "postgresql",
    "mysql",
    "mongodb",
]

SYNC_DATABASES: List[str] = [
    "snowflake",
    "bigquery",
    "redshift",
    "databricks",
    "sqlserver",
    "oracle",
    "clickhouse",
    "athena",
    "trino",
    "presto",
    "hive",
    "spark",
    "mariadb",
    "cassandra",
    "dynamodb",
]


# ============================================
# SUPPORTED DATABASE TYPES
# ============================================
SUPPORTED_DATABASES: List[str] = list(DB_QUERY_LANGUAGES.keys())


# ============================================
# LIMIT SYNTAX PER DATABASE
# Some databases use different LIMIT syntax
# ============================================
LIMIT_SYNTAX: Dict[str, str] = {
    "postgresql": "LIMIT {n}",
    "mysql": "LIMIT {n}",
    "mariadb": "LIMIT {n}",
    "sqlserver": "TOP {n}",  # Actually goes after SELECT
    "oracle": "FETCH FIRST {n} ROWS ONLY",  # Oracle 12c+
    "redshift": "LIMIT {n}",
    "snowflake": "LIMIT {n}",
    "bigquery": "LIMIT {n}",
    "databricks": "LIMIT {n}",
    "clickhouse": "LIMIT {n}",
    "athena": "LIMIT {n}",
    "trino": "LIMIT {n}",
    "presto": "LIMIT {n}",
    "hive": "LIMIT {n}",
    "spark": "LIMIT {n}",
    "mongodb": "",  # MongoDB uses .limit() method, not SQL syntax
    "cassandra": "LIMIT {n}",  # CQL uses LIMIT like SQL
    "dynamodb": "LIMIT {n}",  # PartiQL supports LIMIT
}


# ============================================
# EXPORT FORMAT TYPES
# ============================================
EXPORT_FORMATS: List[str] = ["csv", "json", "excel", "parquet"]


# ============================================
# SECURITY CONSTANTS
# ============================================
CSRF_TOKEN_EXPIRY_SECONDS: int = 3600  # 1 hour
MAX_INPUT_LENGTH: int = 5000
BLOCKED_SQL_KEYWORDS: List[str] = [
    "DROP",
    "DELETE",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "INSERT",
    "UPDATE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "xp_",
    "sp_",
]


# ============================================
# HELPER FUNCTIONS
# ============================================
def get_default_port(db_type: str) -> int:
    """Get the default port for a database type."""
    canonical = DATABASE_TYPE_ALIASES.get(db_type.lower(), db_type.lower())
    return DEFAULT_PORTS.get(canonical, 0)


def get_system_schemas(db_type: str) -> List[str]:
    """Get the list of system schemas to exclude for a database type."""
    canonical = DATABASE_TYPE_ALIASES.get(db_type.lower(), db_type.lower())
    return SYSTEM_SCHEMAS.get(canonical, [])


def get_query_language(db_type: str) -> str:
    """Get the query language for a database type."""
    canonical = DATABASE_TYPE_ALIASES.get(db_type.lower(), db_type.lower())
    return DB_QUERY_LANGUAGES.get(canonical, QUERY_LANGUAGE_SQL)


def is_async_database(db_type: str) -> bool:
    """Check if a database supports async drivers."""
    canonical = DATABASE_TYPE_ALIASES.get(db_type.lower(), db_type.lower())
    return canonical in ASYNC_DATABASES


def normalize_db_type(db_type: str) -> str:
    """Normalize database type to canonical form."""
    return DATABASE_TYPE_ALIASES.get(db_type.lower(), db_type.lower())
