"""
QueryfyAI - Business Tools

Tools for understanding domain context:
- lookup_business_term: Look up business term definitions and SQL expressions
"""

import logging

from app.services.security import ErrorSanitizer
from app.services.tools.registry import ToolContext

logger = logging.getLogger(__name__)


async def lookup_business_term(
    context: ToolContext,
    term: str
) -> str:
    """
    Look up a business term's definition and SQL expression.

    Wraps: data_dictionary.get_relevant_terms()

    Args:
        context: Tool execution context with connection info
        term: Business term to look up (e.g., 'revenue', 'churn', 'ARR')

    Returns:
        Formatted string with term definition and SQL expression
    """
    from app.services.data_dictionary import data_dictionary

    if not context.connection_hash:
        return "Error: No database connection. Please connect to a database first."

    try:
        # Get relevant terms from data dictionary
        terms = await data_dictionary.get_relevant_terms(
            query=term,
            connection_hash=context.connection_hash,
            tenant_id=context.tenant_id,
            session_id=context.session_id,
            limit=3
        )

        if not terms:
            return f"""No definition found for '{term}'.

This term might not be in the business dictionary yet. You can:
1. Ask the user what they mean by '{term}'
2. Infer the meaning from common business terminology
3. Look at the database schema to understand the data model

Common interpretations:
- 'revenue' typically means total sales or gross income
- 'customer' usually refers to people or companies who buy products/services
- 'active' often means engaged within a recent time period (e.g., last 30 days)"""

        # Format the output
        output_lines = [f"Business terms matching '{term}':", ""]

        for t in terms:
            output_lines.append(f"Term: {t.get('term', 'Unknown')}")

            if t.get('definition'):
                output_lines.append(f"Definition: {t['definition']}")

            if t.get('sql_expression'):
                output_lines.append(f"SQL Expression: {t['sql_expression']}")

            if t.get('scope_type'):
                output_lines.append(f"Scope: {t['scope_type']}")

            if t.get('examples'):
                output_lines.append("Examples:")
                for ex in t['examples'][:2]:
                    output_lines.append(f"  - {ex}")

            output_lines.append("")  # Blank line between terms

        return "\n".join(output_lines)

    except Exception as e:
        logger.error(f"lookup_business_term error: {e}", exc_info=True)
        return f"Error looking up term '{term}': {ErrorSanitizer.sanitize_error(e)}"
