"""
QueryfyAI - MongoDB Query Validator

Validates MongoDB queries for read-only operations and security.
"""

import re
from typing import List, Optional, Tuple

from .base import QueryValidator


class MongoDBQueryValidator(QueryValidator):
    """
    MongoDB query validator implementing the Strategy Pattern.

    Validates that MongoDB queries:
    - Use only read operations (find, aggregate, count, distinct)
    - Don't contain write operations (insert, update, delete, drop, etc.)
    - Don't contain JavaScript injection patterns ($where, eval, function)
    - Don't contain dangerous method chaining
    """

    LANGUAGE = "mongodb"

    # MongoDB write operations that should be blocked
    WRITE_OPERATIONS: List[str] = [
        "insertOne",
        "insertMany",
        "insert",
        "updateOne",
        "updateMany",
        "update",
        "replaceOne",
        "deleteOne",
        "deleteMany",
        "delete",
        "remove",
        "drop",
        "createCollection",
        "createIndex",
        "dropIndex",
        "renameCollection",
        "bulkWrite",
        "findOneAndDelete",
        "findOneAndReplace",
        "findOneAndUpdate",
    ]

    # MongoDB read-only operations that are allowed
    READ_OPERATIONS: List[str] = [
        "find",
        "findOne",
        "aggregate",
        "count",
        "countDocuments",
        "estimatedDocumentCount",
        "distinct",
        "explain",
    ]

    # Safe methods for method chaining
    SAFE_METHODS: List[str] = [
        "find",
        "findone",
        "aggregate",
        "count",
        "countdocuments",
        "distinct",
        "explain",
        "limit",
        "skip",
        "sort",
        "project",
        "match",
        "group",
        "lookup",
        "unwind",
        "toarray",
    ]

    # Dangerous patterns (JavaScript injection, etc.)
    DANGEROUS_PATTERNS: List[Tuple[str, str]] = [
        (r"\$where", "$where can execute arbitrary JavaScript"),
        (r"function\s*\(", "JavaScript functions not allowed"),
        (r"eval\s*\(", "eval() not allowed"),
        (r"this\.", "this. reference not allowed"),
        # Note: Method chaining is allowed for safe operations (limit, skip, sort, etc.)
        # Write operations are explicitly checked elsewhere, and dangerous chaining
        # (forEach, map with functions) is caught by DANGEROUS_CHAINING patterns
        (r";\s*db\.", "Multiple statements detected"),
    ]

    # Dangerous chaining patterns
    DANGEROUS_CHAINING: List[str] = [
        r"\.foreach\s*\(",  # forEach can execute arbitrary code
        r"\.map\s*\(\s*function",  # map with function
        r"\.toarray\s*\(\s*\)\s*\.",  # toArray().someMethod()
    ]

    def validate(self, query: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate MongoDB query is read-only.

        Returns:
            Tuple of (is_valid, cleaned_query, error_message)
        """
        query_cleaned = self._clean_query(query)
        query_lower = query_cleaned.lower()

        # Check for write operations ANYWHERE in the query
        # This catches chained operations like find().deleteMany()
        for write_op in self.WRITE_OPERATIONS:
            escaped_op = re.escape(write_op.lower())
            pattern = rf"\.{escaped_op}\s*\("
            if re.search(pattern, query_lower):
                return False, query_cleaned, f"Blocked: {write_op} is a write operation"

            # Also check for operations in strings (potential injection)
            pattern_in_string = rf'["\']\.{escaped_op}\s*\('
            if re.search(pattern_in_string, query_lower):
                return (
                    False,
                    query_cleaned,
                    f"Blocked: {write_op} detected in query string",
                )

        # Check for dangerous method chaining
        for pattern in self.DANGEROUS_CHAINING:
            if re.search(pattern, query_lower):
                return (
                    False,
                    query_cleaned,
                    "Blocked: Query contains potentially dangerous method chaining",
                )

        # Must contain at least one read operation
        has_read_op = False
        for read_op in self.READ_OPERATIONS:
            escaped_op = re.escape(read_op.lower())
            pattern = rf"\.{escaped_op}\s*\("
            if re.search(pattern, query_lower):
                has_read_op = True
                break

        # Also check for aggregation pipeline format (array starting with $)
        if not has_read_op and "[" in query_cleaned and "$" in query_cleaned:
            has_read_op = True

        if not has_read_op:
            return (
                False,
                query_cleaned,
                "Query must use a read operation (find, aggregate, etc.)",
            )

        # Check for dangerous patterns (JavaScript injection, etc.)
        for pattern, message in self.DANGEROUS_PATTERNS:
            if re.search(pattern, query_lower):
                return False, query_cleaned, f"Blocked: {message}"

        # Check method calls count - if more than 5, verify all are safe
        method_calls = re.findall(r"\.\w+\s*\(", query_lower)
        if len(method_calls) > 5:
            for call in method_calls:
                method_name = call.replace(".", "").replace("(", "").strip()
                if method_name and method_name not in self.SAFE_METHODS:
                    if any(w.lower() in method_name for w in self.WRITE_OPERATIONS):
                        return (
                            False,
                            query_cleaned,
                            f"Blocked: Suspicious method {method_name} detected",
                        )

        return True, query_cleaned, None
