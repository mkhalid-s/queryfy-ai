"""
QueryfyAI - Query Executors

Strategy Pattern implementation for database query execution.
Each database type has its own executor that handles the specifics
of connecting and executing queries.

Usage:
    from app.services.executors import get_executor

    executor = get_executor("postgresql")
    result = await executor.execute(connection_url, query, limit=100)
"""

from typing import Dict

from .base import QueryExecutor, SyncQueryExecutor
from .cassandra import CassandraExecutor
from .duckdb import DuckDBExecutor
from .dynamodb import DynamoDBExecutor
from .mongodb import MongoDBExecutor
from .mysql import MySQLExecutor
from .postgresql import PostgreSQLExecutor
from .sqlite import SQLiteExecutor
from .sync_sql import (
    AthenaExecutor,
    BigQueryExecutor,
    ClickHouseExecutor,
    DatabricksExecutor,
    HiveExecutor,
    OracleExecutor,
    PrestoExecutor,
    RedshiftExecutor,
    SnowflakeExecutor,
    SparkExecutor,
    SQLServerExecutor,
    TrinoExecutor,
)

# Registry of all executors
EXECUTORS: Dict[str, QueryExecutor] = {
    "postgresql": PostgreSQLExecutor(),
    "mysql": MySQLExecutor(),
    "mariadb": MySQLExecutor(),  # MariaDB uses MySQL protocol
    "mongodb": MongoDBExecutor(),
    "snowflake": SnowflakeExecutor(),
    "bigquery": BigQueryExecutor(),
    "sqlserver": SQLServerExecutor(),
    "oracle": OracleExecutor(),
    "clickhouse": ClickHouseExecutor(),
    "trino": TrinoExecutor(),
    "presto": PrestoExecutor(),
    "athena": AthenaExecutor(),
    "hive": HiveExecutor(),
    "spark": SparkExecutor(),
    "redshift": RedshiftExecutor(),
    "databricks": DatabricksExecutor(),
    "duckdb": DuckDBExecutor(),
    "sqlite": SQLiteExecutor(),
    "cassandra": CassandraExecutor(),
    "dynamodb": DynamoDBExecutor(),
}


def get_executor(db_type: str) -> QueryExecutor:
    """
    Get the executor for a database type.

    Args:
        db_type: Database type (e.g., "postgresql", "mysql", "mongodb")

    Returns:
        QueryExecutor instance for the database type

    Raises:
        ValueError: If no executor exists for the database type
    """
    executor = EXECUTORS.get(db_type.lower())
    if not executor:
        raise ValueError(f"No executor registered for database type: {db_type}")
    return executor


def get_supported_databases() -> list:
    """Get list of supported database types."""
    return list(EXECUTORS.keys())


def register_executor(db_type: str, executor: QueryExecutor) -> None:
    """
    Register a custom executor for a database type.

    Args:
        db_type: Database type identifier
        executor: QueryExecutor instance
    """
    EXECUTORS[db_type.lower()] = executor


__all__ = [
    "QueryExecutor",
    "SyncQueryExecutor",
    "get_executor",
    "get_supported_databases",
    "register_executor",
    "EXECUTORS",
]
