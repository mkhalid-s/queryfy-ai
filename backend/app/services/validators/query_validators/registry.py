"""
QueryfyAI - Query Validator Registry

Registry for query validators implementing Factory + Registry Pattern.
Provides centralized validator management and query language mapping.
"""

from typing import Dict, Optional, Tuple

from .base import QueryValidator


class QueryValidatorRegistry:
    """
    Registry for query validators (Factory + Registry Pattern).

    Maintains a mapping of query languages to their validators,
    and database types to their query languages.

    Usage:
        # Register validators at module load time
        QueryValidatorRegistry.register("sql", SQLQueryValidator())

        # Validate a query
        is_valid, cleaned, error = QueryValidatorRegistry.validate_query(
            query, db_type="postgresql"
        )
    """

    _validators: Dict[str, QueryValidator] = {}

    # Query language constants
    SQL = "sql"
    MONGODB = "mongodb"
    CQL = "cql"
    PARTIQL = "partiql"

    # Database type to query language mapping
    DB_QUERY_LANGUAGES: Dict[str, str] = {
        # SQL databases
        "postgresql": SQL,
        "mysql": SQL,
        "mariadb": SQL,
        "sqlserver": SQL,
        "oracle": SQL,
        "sqlite": SQL,
        "duckdb": SQL,
        "snowflake": SQL,
        "redshift": SQL,
        "bigquery": SQL,
        "databricks": SQL,
        "clickhouse": SQL,
        "trino": SQL,
        "presto": SQL,
        "hive": SQL,
        "spark": SQL,
        "athena": SQL,
        # NoSQL databases
        "mongodb": MONGODB,
        "cassandra": CQL,
        "dynamodb": PARTIQL,
    }

    @classmethod
    def register(cls, language: str, validator: QueryValidator) -> None:
        """
        Register a validator for a query language.

        Args:
            language: Query language identifier (e.g., "sql", "mongodb")
            validator: QueryValidator instance
        """
        cls._validators[language] = validator

    @classmethod
    def get_validator(cls, language: str) -> Optional[QueryValidator]:
        """
        Get validator for a query language.

        Args:
            language: Query language identifier

        Returns:
            QueryValidator instance or None if not registered
        """
        return cls._validators.get(language)

    @classmethod
    def get_language(cls, db_type: str) -> str:
        """
        Get query language for a database type.

        Args:
            db_type: Database type (e.g., "postgresql", "mongodb")

        Returns:
            Query language identifier, defaults to SQL
        """
        return cls.DB_QUERY_LANGUAGES.get(db_type.lower(), cls.SQL)

    @classmethod
    def is_nosql(cls, db_type: str) -> bool:
        """Check if database type is NoSQL."""
        language = cls.get_language(db_type)
        return language in (cls.MONGODB, cls.CQL, cls.PARTIQL)

    @classmethod
    def is_mongodb(cls, db_type: str) -> bool:
        """Check if database type uses MongoDB query language."""
        return cls.get_language(db_type) == cls.MONGODB

    @classmethod
    def is_cassandra(cls, db_type: str) -> bool:
        """Check if database type uses CQL."""
        return cls.get_language(db_type) == cls.CQL

    @classmethod
    def is_dynamodb(cls, db_type: str) -> bool:
        """Check if database type uses PartiQL."""
        return cls.get_language(db_type) == cls.PARTIQL

    @classmethod
    def validate_query(
        cls, query: str, db_type: str
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Validate a query using the appropriate validator.

        Args:
            query: Query string to validate
            db_type: Database type (determines which validator to use)

        Returns:
            Tuple of (is_valid, cleaned_query, error_message)
        """
        language = cls.get_language(db_type)
        validator = cls.get_validator(language)

        if not validator:
            return False, query, f"No validator registered for language: {language}"

        return validator.validate(query)

    @classmethod
    def get_registered_languages(cls) -> list:
        """Get list of registered query languages."""
        return list(cls._validators.keys())
