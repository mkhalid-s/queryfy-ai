"""
QueryfyAI - SQL Query Validator

Validates SQL queries for read-only operations and security.
"""

import re
from typing import List, Optional, Tuple

from .base import QueryValidator


class SQLQueryValidator(QueryValidator):
    """
    SQL query validator implementing the Strategy Pattern.

    Validates that SQL queries:
    - Start with SELECT or WITH (CTEs)
    - Don't contain write operations (INSERT, UPDATE, DELETE, etc.)
    - Don't contain SQL injection patterns
    - Don't contain multiple statements
    """

    LANGUAGE = "sql"

    # Dangerous SQL keywords that indicate write operations
    DANGEROUS_KEYWORDS: List[str] = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "MERGE",
        "CALL",
        "DECLARE",
        "SET",
    ]

    # SQL injection patterns
    # Note: SQL comments (-- and /* */) are intentionally NOT blocked.
    # Queries are LLM-generated (not raw user input), DANGEROUS_KEYWORDS
    # catches write ops, and sanitize_sql_for_execution strips comments.
    INJECTION_PATTERNS: List[str] = [
        r";\s*(drop|delete|truncate|alter|create|insert|update|grant|revoke)\s+",
        r"into\s+(out|dump)file",
        r"load_file\s*\(",
        r"exec\s*\(",
        r"execute\s*\(",
        r"xp_cmdshell",
        r"sp_executesql",
        r"benchmark\s*\(",
        r"sleep\s*\(",
        r"waitfor\s+delay",
        r"pg_sleep",
        r"0x[0-9a-fA-F]{8,}",
        r"char\s*\(\s*\d+\s*\)",
        r"concat\s*\([^)]*select",
        r"convert\s*\([^)]*select",
    ]

    def validate(self, query: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate SQL query is read-only.

        Returns:
            Tuple of (is_valid, cleaned_query, error_message)
        """
        query_cleaned = self._clean_query(query)
        query_upper = query_cleaned.upper()

        # Must start with SELECT or WITH (for CTEs)
        if not (query_upper.startswith("SELECT") or query_upper.startswith("WITH")):
            return False, query_cleaned, "Query must be a SELECT statement"

        # Check for dangerous keywords that indicate write operations
        for keyword in self.DANGEROUS_KEYWORDS:
            escaped_keyword = re.escape(keyword)
            pattern = rf"(^|\s|;|\()\s*{escaped_keyword}\s+"
            if re.search(pattern, query_upper):
                return (
                    False,
                    query_cleaned,
                    f"Blocked: {keyword} statements are not allowed",
                )

        # Check for SQL injection patterns
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, query_cleaned, re.IGNORECASE):
                return False, query_cleaned, "Query contains suspicious patterns"

        # Check for multiple statements (semicolon followed by keyword)
        if re.search(r";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE)", query_upper):
            return False, query_cleaned, "Multiple statements not allowed"

        return True, query_cleaned, None
