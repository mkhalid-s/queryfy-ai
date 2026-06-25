"""
QueryfyAI - Prompt Providers Registry

Registry pattern for database-specific prompt providers.
Similar to executors and schema_extractors registries.

Usage:
    from app.services.prompt_providers import get_prompt_provider

    provider = get_prompt_provider("mongodb")
    prompt = provider.get_system_prompt(schema, history)
    cleaned_query = provider.clean_response(llm_output)

Adding a new database type:
    1. Create a new file (e.g., neo4j.py)
    2. Implement PromptProvider subclass
    3. Register in PROMPT_PROVIDERS dict below
"""

import logging
from typing import Dict, Type

from .base import PromptProvider
from .cassandra import CassandraPromptProvider
from .dynamodb import DynamoDBPromptProvider
from .mongodb import MongoDBPromptProvider
from .sql import (
    BigQueryPromptProvider,
    DuckDBPromptProvider,
    MySQLPromptProvider,
    PostgreSQLPromptProvider,
    SnowflakePromptProvider,
    SQLitePromptProvider,
    SQLPromptProvider,
    SQLServerPromptProvider,
)

logger = logging.getLogger(__name__)

# =============================================================================
# PROMPT PROVIDER REGISTRY
# =============================================================================

PROMPT_PROVIDERS: Dict[str, Type[PromptProvider]] = {
    # SQL Databases (use generic SQL provider as default)
    "postgresql": PostgreSQLPromptProvider,
    "mysql": MySQLPromptProvider,
    "sqlserver": SQLServerPromptProvider,
    "mssql": SQLServerPromptProvider,
    "oracle": SQLPromptProvider,
    "sqlite": SQLitePromptProvider,
    "duckdb": DuckDBPromptProvider,
    # Cloud Data Warehouses
    "snowflake": SnowflakePromptProvider,
    "bigquery": BigQueryPromptProvider,
    "redshift": SQLPromptProvider,
    "databricks": SQLPromptProvider,
    # Analytics Engines
    "clickhouse": SQLPromptProvider,
    "athena": SQLPromptProvider,
    "trino": SQLPromptProvider,
    "presto": SQLPromptProvider,
    "hive": SQLPromptProvider,
    "spark": SQLPromptProvider,
    # NoSQL
    "mongodb": MongoDBPromptProvider,
    "cassandra": CassandraPromptProvider,
    "dynamodb": DynamoDBPromptProvider,
}

# Default provider for unknown database types
DEFAULT_PROVIDER = SQLPromptProvider


def get_prompt_provider(db_type: str) -> Type[PromptProvider]:
    """
    Get the prompt provider for a database type.

    Args:
        db_type: Database type identifier (e.g., "postgresql", "mongodb")

    Returns:
        PromptProvider class for the database type
    """
    db_type_lower = db_type.lower()
    provider = PROMPT_PROVIDERS.get(db_type_lower)

    if provider is None:
        logger.debug(
            f"No specific prompt provider for '{db_type}', using default SQL provider"
        )
        return DEFAULT_PROVIDER

    return provider


def register_prompt_provider(db_type: str, provider: Type[PromptProvider]) -> None:
    """
    Register a custom prompt provider at runtime.

    Args:
        db_type: Database type identifier
        provider: PromptProvider subclass

    Example:
        from app.services.prompt_providers import register_prompt_provider

        class MyCustomProvider(PromptProvider):
            DB_TYPE = "mydb"
            ...

        register_prompt_provider("mydb", MyCustomProvider)
    """
    PROMPT_PROVIDERS[db_type.lower()] = provider
    logger.info(f"Registered prompt provider for '{db_type}'")


def list_supported_providers() -> list:
    """List all registered prompt providers."""
    return list(PROMPT_PROVIDERS.keys())


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Core classes
    "PromptProvider",
    "SQLPromptProvider",
    "MongoDBPromptProvider",
    # Registry functions
    "get_prompt_provider",
    "register_prompt_provider",
    "list_supported_providers",
    # Registry dict (for advanced use)
    "PROMPT_PROVIDERS",
]
