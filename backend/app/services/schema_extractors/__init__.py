"""
QueryfyAI - Schema Extractors

Template Method Pattern implementation for database schema extraction.
Each database type has its own extractor that inherits from the base class
and implements database-specific extraction logic.

Usage:
    from app.services.schema_extractors import get_extractor

    extractor = get_extractor("postgresql")
    schema = await extractor.extract(connection_url)
"""

import logging
from typing import Dict, Optional

from .base import MongoDBSchemaExtractor, SchemaExtractor
from .cassandra import CassandraSchemaExtractor
from .dynamodb import DynamoDBSchemaExtractor
from .generic_sql import GenericSQLSchemaExtractor
from .mongodb import MongoDBSchemaExtractor as MongoDBExtractor
from .mysql import MySQLSchemaExtractor
from .postgresql import PostgreSQLSchemaExtractor
from .sensitive_field_mixin import SensitiveFieldMixin

logger = logging.getLogger(__name__)


# Registry of specialized schema extractors
EXTRACTORS: Dict[str, SchemaExtractor] = {
    "postgresql": PostgreSQLSchemaExtractor(),
    "mysql": MySQLSchemaExtractor(),
    "mariadb": MySQLSchemaExtractor(),  # MariaDB uses MySQL schema
    "mongodb": MongoDBExtractor(),
    "cassandra": CassandraSchemaExtractor(),
    "dynamodb": DynamoDBSchemaExtractor(),
}

# SQL databases that can use the generic extractor as fallback
# These all support information_schema queries or similar
GENERIC_SQL_DATABASES = [
    "snowflake",
    "bigquery",
    "sqlserver",
    "oracle",
    "redshift",
    "databricks",
    "clickhouse",
    "trino",
    "presto",
    "athena",
    "hive",
    "spark",
    "duckdb",  # Supports information_schema
    "sqlite",  # Uses sqlite_master (handled in generic extractor)
]


def get_extractor(db_type: str) -> Optional[SchemaExtractor]:
    """
    Get the schema extractor for a database type.

    If a specialized extractor exists, it is returned.
    Otherwise, for SQL databases, a generic extractor using
    information_schema is returned.

    Args:
        db_type: Database type (e.g., "postgresql", "mysql", "mongodb")

    Returns:
        SchemaExtractor instance or None if not supported
    """
    db_type_lower = db_type.lower()

    # Check for specialized extractor first
    if db_type_lower in EXTRACTORS:
        return EXTRACTORS[db_type_lower]

    # Use generic SQL extractor for supported databases
    if db_type_lower in GENERIC_SQL_DATABASES:
        logger.info(f"Using generic SQL extractor for {db_type}")
        return GenericSQLSchemaExtractor(db_type=db_type_lower)

    # No extractor available
    logger.warning(f"No schema extractor available for {db_type}")
    return None


def get_supported_databases() -> list:
    """Get list of database types with schema extractors."""
    return list(EXTRACTORS.keys()) + GENERIC_SQL_DATABASES


def has_specialized_extractor(db_type: str) -> bool:
    """Check if a specialized (non-generic) extractor exists."""
    return db_type.lower() in EXTRACTORS


def register_extractor(db_type: str, extractor: SchemaExtractor) -> None:
    """
    Register a custom schema extractor.

    Args:
        db_type: Database type identifier
        extractor: SchemaExtractor instance
    """
    EXTRACTORS[db_type.lower()] = extractor


__all__ = [
    "SchemaExtractor",
    "MongoDBSchemaExtractor",
    "SensitiveFieldMixin",
    "GenericSQLSchemaExtractor",
    "get_extractor",
    "get_supported_databases",
    "has_specialized_extractor",
    "register_extractor",
    "EXTRACTORS",
]
