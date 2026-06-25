"""
QueryfyAI - Query Validators Package

Strategy Pattern implementation for query validation.
Validators are automatically registered when this module is imported.
"""

from .base import QueryValidator
from .cql_validator import CQLQueryValidator
from .mongodb_validator import MongoDBQueryValidator
from .partiql_validator import PartiQLQueryValidator
from .registry import QueryValidatorRegistry
from .sql_validator import SQLQueryValidator


# Register validators at module load time
# This implements the Factory pattern - validators are created once and reused
def _register_validators():
    """Register all query validators with the registry."""
    QueryValidatorRegistry.register(QueryValidatorRegistry.SQL, SQLQueryValidator())
    QueryValidatorRegistry.register(
        QueryValidatorRegistry.MONGODB, MongoDBQueryValidator()
    )
    QueryValidatorRegistry.register(QueryValidatorRegistry.CQL, CQLQueryValidator())
    QueryValidatorRegistry.register(
        QueryValidatorRegistry.PARTIQL, PartiQLQueryValidator()
    )


_register_validators()


__all__ = [
    "QueryValidator",
    "QueryValidatorRegistry",
    "SQLQueryValidator",
    "MongoDBQueryValidator",
    "CQLQueryValidator",
    "PartiQLQueryValidator",
]
