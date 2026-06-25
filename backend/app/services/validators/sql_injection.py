"""
QueryfyAI - SQL Injection Validator

Detects and warns about potential SQL injection patterns in user input.
"""

import logging
import re

from .base import ValidationResult, Validator

logger = logging.getLogger(__name__)


class SQLInjectionValidator(Validator):
    """
    Validator for detecting SQL injection patterns in natural language input.

    Note: This validates the natural language input to the LLM, not the generated SQL.
    Generated SQL has separate validation in SecurityService.
    """

    # Patterns that look like SQL injection attempts
    INJECTION_PATTERNS = [
        # Classic SQL injection patterns
        r"'\s*(?:or|and)\s*'?\d*'?\s*=\s*'?\d*'?",  # ' or '1'='1
        r"--\s*$",  # SQL comment at end
        r";\s*(?:drop|delete|truncate|insert|update)",  # Chained dangerous commands
        r"union\s+(?:all\s+)?select",  # UNION SELECT
        # Command injection attempts
        r";\s*exec\s+",
        r";\s*execute\s+",
        r"xp_cmdshell",
        r"sp_executesql",
        # Dangerous SQL keywords in suspicious contexts
        r"'\s*;\s*drop\s+(?:table|database)",
        r"'\s*;\s*delete\s+from",
        r"'\s*;\s*truncate\s+",
        r"'\s*;\s*insert\s+into",
        # Encoded injection attempts
        r"%27\s*(?:or|and)",  # URL-encoded single quote
        r"0x[0-9a-f]+",  # Hex encoded strings
    ]

    # Keywords that are dangerous in certain contexts
    DANGEROUS_KEYWORDS = [
        "drop table",
        "drop database",
        "truncate table",
        "delete from",
        "insert into",
        "update set",
        "grant all",
        "revoke all",
        "alter table",
        "create user",
        "drop user",
    ]

    def __init__(self, warn_only: bool = True):
        """
        Initialize the validator.

        Args:
            warn_only: If True, add warning but don't block.
                      If False, block on detection.
        """
        super().__init__()
        self.warn_only = warn_only
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.INJECTION_PATTERNS
        ]

    def _do_validate(self, result: ValidationResult) -> None:
        """Check for SQL injection patterns."""
        text_lower = result.text.lower()

        # Check regex patterns
        for pattern in self._compiled_patterns:
            match = pattern.search(text_lower)
            if match:
                matched_text = match.group(0)
                logger.warning(f"SQL injection pattern detected: '{matched_text}'")

                if self.warn_only:
                    result.add_warning(f"SQL-like pattern detected: {matched_text}")
                else:
                    result.block(f"SQL injection attempt detected: {matched_text}")
                    return

        # Check for dangerous keywords
        for keyword in self.DANGEROUS_KEYWORDS:
            if keyword in text_lower:
                logger.warning(f"Dangerous SQL keyword detected: '{keyword}'")
                result.add_warning(f"Dangerous SQL keyword detected: {keyword}")
                # Don't block for keywords as they might be legitimate questions
                # e.g., "How do I delete from a table?"
