"""
QueryfyAI - Base Prompt Provider

Abstract base class for database-specific prompt generation.
Follows the Strategy Pattern for extensibility.
"""

import re
from abc import ABC, abstractmethod


class PromptProvider(ABC):
    """
    Base class for database-specific prompt providers.

    Each database type can have its own prompt provider that knows:
    - How to format the system prompt
    - How to clean/validate LLM responses
    - Database-specific query syntax rules

    Usage:
        provider = get_prompt_provider("mongodb")
        prompt = provider.get_system_prompt(schema, history)
        cleaned = provider.clean_response(llm_output)
    """

    # Override in subclasses
    DB_TYPE: str = "base"
    QUERY_LANGUAGE: str = "SQL"  # SQL, MQL, CQL, etc.

    @classmethod
    @abstractmethod
    def get_system_prompt(cls, schema: str, history: str, **kwargs) -> str:
        """
        Generate the system prompt for this database type.

        Args:
            schema: Database schema description
            history: Conversation history
            **kwargs: Additional database-specific parameters

        Returns:
            Formatted system prompt string
        """
        pass

    @classmethod
    @abstractmethod
    def clean_response(cls, response: str) -> str:
        """
        Clean and validate the LLM response for this database type.

        Args:
            response: Raw LLM response

        Returns:
            Cleaned query string
        """
        pass

    @classmethod
    def get_explain_prompt(cls, query: str, schema: str) -> str:
        """
        Generate prompt for explaining a query.
        Override in subclasses for database-specific explanations.
        """
        return f"""Explain this {cls.QUERY_LANGUAGE} query in plain English for a business user. Be concise and clear.

Query:
```
{query}
```

Schema:
{schema}

Format your response with:
**Summary:** [One sentence description]
**How it works:** [Bullet points of key steps]
**Results:** [What the output columns mean]"""

    @classmethod
    def _remove_markdown_blocks(cls, text: str) -> str:
        """Remove markdown code blocks from response."""
        # Try various code block formats
        for lang in ["sql", "mongodb", "javascript", "js", "mql", "cypher", "cql", ""]:
            pattern = rf"```{lang}\s*([\s\S]*?)```"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return text.strip()
