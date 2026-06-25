"""
QueryfyAI - Query Validators

Strategy Pattern implementation for query validation.
Each query language has its own validator that implements
the QueryValidator interface.

Also provides input sanitization using Chain of Responsibility pattern.
"""

from typing import List, Tuple

from .base import ValidatorChain
from .prompt_injection import PromptInjectionValidator
from .query_validators import (
    CQLQueryValidator,
    MongoDBQueryValidator,
    PartiQLQueryValidator,
    QueryValidator,
    QueryValidatorRegistry,
    SQLQueryValidator,
)
from .sql_injection import SQLInjectionValidator
from .suspicious_chars import SuspiciousCharValidator


def sanitize_input(text: str) -> Tuple[str, List[str]]:
    """
    Sanitize user input through the validation chain.

    Uses Chain of Responsibility pattern with:
    1. Prompt injection detection
    2. SQL injection detection
    3. Suspicious character sanitization

    Args:
        text: Raw user input

    Returns:
        Tuple of (sanitized_text, list_of_warnings)
    """
    # Build the validation chain
    chain = ValidatorChain()
    chain.add(PromptInjectionValidator())
    chain.add(SQLInjectionValidator())
    chain.add(SuspiciousCharValidator(sanitize=True, block_on_dangerous=False))

    # Run validation
    result = chain.validate(text)

    # Return in expected format (text, warnings)
    return result.text, result.warnings


__all__ = [
    # Query validators
    "QueryValidator",
    "QueryValidatorRegistry",
    "SQLQueryValidator",
    "MongoDBQueryValidator",
    "CQLQueryValidator",
    "PartiQLQueryValidator",
    # Input sanitization
    "sanitize_input",
]
