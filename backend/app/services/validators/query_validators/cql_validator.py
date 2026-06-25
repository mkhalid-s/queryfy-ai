"""
QueryfyAI - CQL Query Validator

Validates Cassandra CQL queries for read-only operations and security.
"""

import logging
import re
from typing import List, Optional, Tuple

from .base import QueryValidator

logger = logging.getLogger(__name__)


class CQLQueryValidator(QueryValidator):
    """
    Cassandra CQL query validator implementing the Strategy Pattern.

    Validates that CQL queries:
    - Start with SELECT
    - Don't contain write/DDL operations (INSERT, UPDATE, DELETE, DROP, etc.)
    - Don't contain EXECUTE or APPLY (arbitrary CQL, conditional batch writes)
    - Don't contain multiple statements

    Also warns about:
    - ALLOW FILTERING (performance concern)
    """

    LANGUAGE = "cql"

    # CQL keywords that should be blocked
    BLOCKED_KEYWORDS: List[str] = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "TRUNCATE",
        "CREATE",
        "ALTER",
        "GRANT",
        "REVOKE",
        "BATCH",
        "EXECUTE",  # Arbitrary CQL execution
        "APPLY",  # Conditional batch writes
    ]

    def validate(self, query: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate CQL query is read-only.

        Returns:
            Tuple of (is_valid, cleaned_query, error_message)
        """
        query_cleaned = self._clean_query(query)
        query_upper = query_cleaned.upper().strip()

        # Must start with SELECT
        if not query_upper.startswith("SELECT"):
            return False, query_cleaned, "CQL query must be a SELECT statement"

        # Block write/DDL operations
        for keyword in self.BLOCKED_KEYWORDS:
            escaped_keyword = re.escape(keyword)
            pattern = rf"(^|\s|;)\s*{escaped_keyword}\s+"
            if re.search(pattern, query_upper):
                return (
                    False,
                    query_cleaned,
                    f"Blocked: {keyword} operations are not allowed in CQL",
                )

        # Check for multiple statements
        if re.search(r";\s*\w", query_cleaned):
            return False, query_cleaned, "Multiple CQL statements not allowed"

        # Warn about ALLOW FILTERING (performance concern, not security)
        if "ALLOW FILTERING" in query_upper:
            logger.warning("CQL query uses ALLOW FILTERING - may cause full table scan")

        return True, query_cleaned, None
