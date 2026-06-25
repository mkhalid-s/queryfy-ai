"""
QueryfyAI - Suspicious Characters Validator

Detects and sanitizes suspicious or potentially harmful characters.
"""

import logging
import re
import unicodedata

from .base import ValidationResult, Validator

logger = logging.getLogger(__name__)


class SuspiciousCharValidator(Validator):
    """
    Validator for detecting and cleaning suspicious characters.

    Handles:
    - Null bytes and control characters
    - Unicode homoglyphs
    - Invisible characters
    - Excessive whitespace
    """

    # Characters to remove entirely
    DANGEROUS_CHARS = [
        "\x00",  # Null byte
        "\x0b",  # Vertical tab
        "\x0c",  # Form feed
        "\x1a",  # Ctrl+Z (EOF on Windows)
        "\x7f",  # DEL character
    ]

    # Unicode categories to flag
    SUSPICIOUS_CATEGORIES = {
        "Cf": "Format character",  # Invisible format characters
        "Co": "Private use",  # Private use characters
        "Cs": "Surrogate",  # Surrogate characters
    }

    def __init__(self, sanitize: bool = True, block_on_dangerous: bool = False):
        """
        Initialize the validator.

        Args:
            sanitize: If True, remove/replace suspicious characters.
            block_on_dangerous: If True, block input with dangerous chars.
        """
        super().__init__()
        self.sanitize = sanitize
        self.block_on_dangerous = block_on_dangerous

    def _do_validate(self, result: ValidationResult) -> None:
        """Check for and clean suspicious characters."""
        text = result.text
        cleaned = text
        found_dangerous = False

        # Remove dangerous characters
        for char in self.DANGEROUS_CHARS:
            if char in text:
                found_dangerous = True
                logger.warning(f"Dangerous character found: {repr(char)}")
                if self.sanitize:
                    cleaned = cleaned.replace(char, "")
                result.add_warning(f"Removed dangerous character: {repr(char)}")

        # Check for suspicious Unicode categories
        suspicious_found = []
        for i, char in enumerate(text):
            category = unicodedata.category(char)
            if category in self.SUSPICIOUS_CATEGORIES:
                suspicious_found.append((char, self.SUSPICIOUS_CATEGORIES[category]))

        if suspicious_found:
            logger.warning(
                f"Suspicious Unicode characters found: {len(suspicious_found)}"
            )
            if self.sanitize:
                # Remove suspicious characters
                cleaned = "".join(
                    c
                    for c in cleaned
                    if unicodedata.category(c) not in self.SUSPICIOUS_CATEGORIES
                )
            result.add_warning(
                f"Found {len(suspicious_found)} suspicious Unicode characters"
            )

        # Normalize excessive whitespace
        if self.sanitize:
            # Replace multiple spaces with single space
            cleaned = re.sub(r" {2,}", " ", cleaned)
            # Replace multiple newlines with double newline
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            # Trim
            cleaned = cleaned.strip()

        # Check for homoglyph attacks (characters that look like ASCII but aren't)
        homoglyphs = self._detect_homoglyphs(text)
        if homoglyphs:
            logger.warning(
                f"Potential homoglyph attack detected: {len(homoglyphs)} characters"
            )
            result.add_warning(
                f"Detected {len(homoglyphs)} look-alike Unicode characters"
            )

        # Block if dangerous and configured to do so
        if found_dangerous and self.block_on_dangerous:
            result.block("Input contains dangerous characters")
            return

        # Update text with cleaned version
        result.text = cleaned

    def _detect_homoglyphs(self, text: str) -> list:
        """
        Detect characters that look like ASCII but aren't.

        Returns list of (position, char, looks_like) tuples.
        """
        # Common homoglyphs - characters that look like ASCII letters
        homoglyph_map = {
            "\u0430": "a",  # Cyrillic а
            "\u0435": "e",  # Cyrillic е
            "\u043e": "o",  # Cyrillic о
            "\u0440": "p",  # Cyrillic р
            "\u0441": "c",  # Cyrillic с
            "\u0443": "y",  # Cyrillic у
            "\u0445": "x",  # Cyrillic х
            "\u0391": "A",  # Greek Α
            "\u0392": "B",  # Greek Β
            "\u0395": "E",  # Greek Ε
            "\u0397": "H",  # Greek Η
            "\u0399": "I",  # Greek Ι
            "\u039a": "K",  # Greek Κ
            "\u039c": "M",  # Greek Μ
            "\u039d": "N",  # Greek Ν
            "\u039f": "O",  # Greek Ο
            "\u03a1": "P",  # Greek Ρ
            "\u03a4": "T",  # Greek Τ
            "\u03a7": "X",  # Greek Χ
            "\u03a5": "Y",  # Greek Υ
            "\u0417": "Z",  # Cyrillic З
        }

        found = []
        for i, char in enumerate(text):
            if char in homoglyph_map:
                found.append((i, char, homoglyph_map[char]))

        return found


class LengthValidator(Validator):
    """
    Validator for input length limits.
    """

    def __init__(self, max_length: int = 5000, truncate: bool = False):
        """
        Initialize the validator.

        Args:
            max_length: Maximum allowed input length.
            truncate: If True, truncate input. If False, block.
        """
        super().__init__()
        self.max_length = max_length
        self.truncate = truncate

    def _do_validate(self, result: ValidationResult) -> None:
        """Check input length."""
        if len(result.text) > self.max_length:
            if self.truncate:
                result.text = result.text[: self.max_length]
                result.add_warning(f"Input truncated to {self.max_length} characters")
            else:
                result.block(f"Input exceeds maximum length of {self.max_length}")
