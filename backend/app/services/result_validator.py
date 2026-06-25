"""
QueryfyAI - Result Validator

LLM-based validation of query results to ensure they correctly answer
the user's question before returning them.
"""

import json
import logging
from typing import Any, Dict, Optional

from app.models.schemas import LLMConfig
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class ResultValidator:
    """
    LLM-based validation of query results.

    Uses the LLM to analyze whether query results correctly answer
    the user's question, checking for semantic correctness.
    """

    VALIDATION_PROMPT = """You are a SQL result validator. Analyze whether the query results correctly answer the user's question.

User Question: {question}
Generated SQL: {sql}
Result Summary:
- Row count: {row_count}
- Columns: {columns}
- Sample data (first 5 rows): {sample_data}

Evaluate:
1. Does the data structure match what the question asks for?
2. Are the column names semantically correct for the question?
3. Does the row count make sense (not suspiciously empty or too large)?
4. Do the sample values look reasonable?

Respond ONLY with a JSON object (no markdown, no explanation):
{{
    "valid": true/false,
    "confidence": 0.0-1.0,
    "issues": ["list of concerns if any"],
    "suggestion": "how to improve the query if invalid, or null if valid"
}}
"""

    @classmethod
    async def validate(
        cls,
        llm_config: LLMConfig,
        question: str,
        sql: str,
        results: Dict[str, Any],
        db_type: str = "postgresql",
    ) -> Dict[str, Any]:
        """
        Validate query results using LLM.

        Args:
            llm_config: LLM configuration
            question: The original natural language question
            sql: The generated SQL query
            results: Query results with columns, rows, row_count
            db_type: Database type for context

        Returns:
            Validation result dict with:
            - validated: bool - whether validation was performed
            - valid: bool - whether results are valid
            - confidence: float - confidence score 0-1
            - issues: list - any concerns found
            - suggestion: str - improvement suggestion if invalid
        """
        try:
            # Prepare sample data
            rows = results.get("rows", [])
            sample_data = json.dumps(rows[:5], default=str, indent=2)

            # Build validation prompt
            prompt = cls.VALIDATION_PROMPT.format(
                question=question,
                sql=sql,
                row_count=results.get("row_count", 0),
                columns=", ".join(results.get("columns", [])),
                sample_data=sample_data,
            )

            # Call LLM for validation
            response, _ = await LLMService.generate_sql(
                llm_config,
                prompt,
                "Validate the SQL results",
                [],  # No few-shot examples for validation
                db_type,
            )

            # Parse JSON response
            # Try to extract JSON from the response
            validation = cls._parse_json_response(response)

            if validation is None:
                logger.warning(f"Failed to parse validation response: {response[:200]}")
                return cls._default_valid_response()

            return {
                "validated": True,
                "valid": validation.get("valid", True),
                "confidence": validation.get("confidence", 0.5),
                "issues": validation.get("issues", []),
                "suggestion": validation.get("suggestion"),
            }

        except Exception as e:
            # On validation failure, assume valid (don't block user)
            logger.error(f"Result validation error: {e}")
            return {
                "validated": False,
                "valid": True,
                "confidence": 0.5,
                "issues": [f"Validation error: {str(e)}"],
                "suggestion": None,
            }

    @classmethod
    def _parse_json_response(cls, response: str) -> Optional[Dict]:
        """
        Parse JSON from LLM response, handling various formats.

        Args:
            response: Raw LLM response

        Returns:
            Parsed JSON dict or None if parsing fails
        """
        # Try direct JSON parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        import re

        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        json_match = re.search(r'\{[^{}]*"valid"[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    @classmethod
    def _default_valid_response(cls) -> Dict[str, Any]:
        """Return default valid response when parsing fails."""
        return {
            "validated": False,
            "valid": True,
            "confidence": 0.5,
            "issues": ["Could not parse validation response"],
            "suggestion": None,
        }

    @classmethod
    def should_retry(
        cls, validation: Dict[str, Any], retry_count: int, max_retries: int = 1
    ) -> bool:
        """
        Determine if we should retry based on validation results.

        Only retries if validation indicates invalid results with high confidence.

        Args:
            validation: Validation result dict
            retry_count: Current retry count for validation
            max_retries: Maximum validation retries

        Returns:
            True if should regenerate query, False otherwise
        """
        if not validation.get("validated", False):
            return False

        if validation.get("valid", True):
            return False

        if retry_count >= max_retries:
            return False

        # Only retry if confidence is high enough
        confidence = validation.get("confidence", 0.5)
        return confidence >= 0.8

    @classmethod
    def get_retry_context(cls, validation: Dict[str, Any]) -> str:
        """
        Get context for retry prompt based on validation issues.

        Args:
            validation: Validation result dict

        Returns:
            Additional context for the LLM prompt
        """
        issues = validation.get("issues", [])
        suggestion = validation.get("suggestion")

        context = "\nRESULT VALIDATION FAILED:\n"

        if issues:
            context += "Issues found:\n"
            for issue in issues:
                context += f"- {issue}\n"

        if suggestion:
            context += f"\nSuggestion: {suggestion}\n"

        context += "\nPlease regenerate the query to address these issues."

        return context
