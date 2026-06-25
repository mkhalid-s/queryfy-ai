"""
QueryfyAI - Sensitive Field Detection Mixin

Mixin class providing sensitive field detection for schema extractors.
Follows DRY principle by centralizing sensitive field patterns.
"""

from typing import List


class SensitiveFieldMixin:
    """
    Mixin providing sensitive field detection for schema extractors.

    Follows DRY principle by centralizing sensitive field patterns
    used across MongoDB, DynamoDB, and Cassandra extractors.

    Usage:
        class MyExtractor(SchemaExtractor, SensitiveFieldMixin):
            def some_method(self):
                if self._is_sensitive_field("password_hash"):
                    # Skip sampling this field
                    pass
    """

    SENSITIVE_FIELD_PATTERNS: List[str] = [
        "password",
        "token",
        "secret",
        "email",
        "ssn",
        "phone",
        "address",
        "key",
        "hash",
        "credit",
        "card",
        "cvv",
        "pin",
        "auth",
        "credential",
    ]

    def _is_sensitive_field(self, field_name: str) -> bool:
        """
        Check if a field name matches sensitive patterns.

        Args:
            field_name: Name of the field to check

        Returns:
            True if field name contains any sensitive pattern
        """
        field_lower = field_name.lower()
        return any(pattern in field_lower for pattern in self.SENSITIVE_FIELD_PATTERNS)
