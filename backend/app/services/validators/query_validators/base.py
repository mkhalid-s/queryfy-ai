"""
QueryfyAI - Base Query Validator

Abstract base class for query validators implementing the Strategy Pattern.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple


class QueryValidator(ABC):
    """
    Abstract base class for query validators (Strategy Pattern).

    Each query language (SQL, MongoDB, CQL, PartiQL) has its own
    validator that implements this interface.

    The validate() method returns a tuple of:
    - is_valid: Whether the query passed validation
    - cleaned_query: The cleaned/sanitized query
    - error_message: Error description if validation failed, None otherwise
    """

    LANGUAGE: str = ""

    @abstractmethod
    def validate(self, query: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate a query.

        Args:
            query: The query string to validate

        Returns:
            Tuple of (is_valid, cleaned_query, error_message)
            - is_valid: True if query passed validation
            - cleaned_query: Sanitized query string
            - error_message: Error description or None if valid
        """
        pass

    def _clean_query(self, query: str) -> str:
        """
        Common query cleaning logic.

        Strips whitespace and trailing semicolons.
        """
        return query.strip().rstrip(";")
