"""
QueryfyAI - Prompt Injection Validator

Detects and blocks prompt injection attempts in user input.
"""

import logging
import re

from .base import ValidationResult, Validator

logger = logging.getLogger(__name__)


class PromptInjectionValidator(Validator):
    """
    Validator for detecting prompt injection attempts.

    Looks for patterns that could manipulate LLM behavior:
    - "Ignore previous instructions"
    - "You are now..."
    - System prompt manipulations
    - Role-playing attempts
    """

    # Patterns that indicate prompt injection attempts
    INJECTION_PATTERNS = [
        # Instruction overrides
        r"ignore\s+(all\s+)?previous\s+instructions?",
        r"ignore\s+(all\s+)?above\s+instructions?",
        r"forget\s+(all\s+)?previous\s+instructions?",
        r"disregard\s+(all\s+)?previous\s+instructions?",
        r"override\s+(all\s+)?previous\s+instructions?",
        # Role manipulation
        r"you\s+are\s+now\s+a?",
        r"act\s+as\s+(?:if|a)",
        r"pretend\s+(?:to\s+be|you\s+are)",
        r"roleplay\s+as",
        r"simulate\s+(?:being\s+)?a?",
        # System prompt access
        r"what\s+(?:is|are)\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
        r"show\s+(?:me\s+)?your\s+(?:system\s+)?(?:instructions?|prompt)",
        r"reveal\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
        r"print\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
        # Delimiter injection
        r"```\s*(?:system|user|assistant)",
        r"\[\[(?:system|user|assistant)\]\]",
        r"<\s*(?:system|user|assistant)\s*>",
        # Jailbreak patterns
        r"jailbreak",
        r"dan\s+mode",
        r"developer\s+mode",
        r"bypass\s+(?:filters?|safety|restrictions?)",
    ]

    def __init__(self, block_on_detection: bool = True):
        """
        Initialize the validator.

        Args:
            block_on_detection: If True, block input on detection.
                               If False, add warning but allow through.
        """
        super().__init__()
        self.block_on_detection = block_on_detection
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.INJECTION_PATTERNS
        ]

    def _do_validate(self, result: ValidationResult) -> None:
        """Check for prompt injection patterns."""
        text_lower = result.text.lower()

        for pattern in self._compiled_patterns:
            match = pattern.search(text_lower)
            if match:
                matched_text = match.group(0)
                logger.warning(f"Prompt injection detected: '{matched_text}'")

                if self.block_on_detection:
                    result.block(f"Prompt injection attempt detected: {matched_text}")
                    return
                else:
                    result.add_warning(f"Suspicious pattern detected: {matched_text}")
