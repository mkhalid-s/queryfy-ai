"""
QueryfyAI - PartiQL Query Validator

Validates DynamoDB PartiQL queries for read-only operations and security.
"""

import logging
import re
from typing import List, Optional, Tuple

from .base import QueryValidator

logger = logging.getLogger(__name__)


class PartiQLQueryValidator(QueryValidator):
    """
    DynamoDB PartiQL query validator implementing the Strategy Pattern.

    Validates that PartiQL queries:
    - Start with SELECT
    - Don't contain write operations (INSERT, UPDATE, DELETE)
    - Don't contain multiple statements

    Also warns about:
    - Queries without WHERE clause (causes expensive SCAN operations)
    """

    LANGUAGE = "partiql"

    # PartiQL keywords that should be blocked
    BLOCKED_KEYWORDS: List[str] = [
        "INSERT",
        "UPDATE",
        "DELETE",
    ]

    def validate(self, query: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate PartiQL query is read-only.

        Returns:
            Tuple of (is_valid, cleaned_query, error_message)
        """
        query_cleaned = self._clean_query(query)
        query_upper = query_cleaned.upper().strip()

        # Must start with SELECT
        if not query_upper.startswith("SELECT"):
            return False, query_cleaned, "PartiQL query must be a SELECT statement"

        # Block write operations
        for keyword in self.BLOCKED_KEYWORDS:
            escaped_keyword = re.escape(keyword)
            pattern = rf"(^|\s|;)\s*{escaped_keyword}\s+"
            if re.search(pattern, query_upper):
                return (
                    False,
                    query_cleaned,
                    f"Blocked: {keyword} operations are not allowed in PartiQL",
                )

        # Check for multiple statements
        if re.search(r";\s*\w", query_cleaned):
            return False, query_cleaned, "Multiple PartiQL statements not allowed"

        # Warn about queries without WHERE clause (causes expensive SCAN)
        if "WHERE" not in query_upper:
            logger.warning(
                "PartiQL query without WHERE clause will perform expensive SCAN operation"
            )

        return True, query_cleaned, None
