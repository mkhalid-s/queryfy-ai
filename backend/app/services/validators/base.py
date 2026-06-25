"""
QueryfyAI - Base Validator

Chain of Responsibility Pattern for input validation.
Each validator in the chain processes the input and optionally
passes it to the next validator.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validation chain processing."""

    text: str
    warnings: List[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None

    def add_warning(self, warning: str):
        """Add a warning to the result."""
        self.warnings.append(warning)

    def block(self, reason: str):
        """Block the input with a reason."""
        self.blocked = True
        self.block_reason = reason


class Validator(ABC):
    """
    Abstract base class for validators in the chain.

    Each validator:
    1. Processes the input
    2. May modify the text
    3. May add warnings
    4. May block the input entirely
    5. Passes to the next validator in chain (unless blocked)
    """

    def __init__(self) -> None:
        self._next: Optional["Validator"] = None

    def set_next(self, validator: "Validator") -> "Validator":
        """
        Set the next validator in the chain.

        Returns the next validator for fluent chaining:
            chain = v1.set_next(v2).set_next(v3)
        """
        self._next = validator
        return validator

    def validate(
        self, text: str, warnings: Optional[List[str]] = None
    ) -> ValidationResult:
        """
        Process input through this validator and the chain.

        Args:
            text: Input text to validate
            warnings: Existing warnings from previous validators

        Returns:
            ValidationResult with processed text, warnings, and block status
        """
        if warnings is None:
            warnings = []

        # Create result object
        result = ValidationResult(text=text, warnings=warnings.copy())

        # Apply this validator's logic
        self._do_validate(result)

        # If blocked or no next validator, return
        if result.blocked or self._next is None:
            return result

        # Pass to next validator in chain
        return self._next.validate(result.text, result.warnings)

    @abstractmethod
    def _do_validate(self, result: ValidationResult) -> None:
        """
        Implement validation logic.

        Modify the result object:
        - result.text: the cleaned/sanitized text
        - result.add_warning(): add warnings
        - result.block(): block the input entirely
        """
        pass


class ValidatorChain:
    """
    Factory for creating and managing validation chains.

    Usage:
        chain = ValidatorChain()
        chain.add(PromptInjectionValidator())
        chain.add(SQLInjectionValidator())
        result = chain.validate(user_input)
    """

    def __init__(self) -> None:
        self._head: Optional[Validator] = None
        self._tail: Optional[Validator] = None

    def add(self, validator: Validator) -> "ValidatorChain":
        """Add a validator to the chain."""
        if self._head is None:
            self._head = validator
            self._tail = validator
        else:
            if self._tail is not None:
                self._tail.set_next(validator)
            self._tail = validator
        return self

    def validate(self, text: str) -> ValidationResult:
        """Run the validation chain."""
        if self._head is None:
            return ValidationResult(text=text)
        return self._head.validate(text)

    def __len__(self) -> int:
        """Count validators in chain."""
        count = 0
        current = self._head
        while current is not None:
            count += 1
            current = current._next
        return count
