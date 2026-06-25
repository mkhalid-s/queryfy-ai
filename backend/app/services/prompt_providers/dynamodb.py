"""
QueryfyAI - DynamoDB Prompt Provider

Prompt provider for Amazon DynamoDB (PartiQL - SQL-like syntax).
Emphasizes partition key requirements, GSI/LSI usage, and scan warnings.
"""

import re
from typing import List

from .base import PromptProvider

# Patterns that indicate a complex PartiQL query requiring reasoning steps
DYNAMODB_COMPLEX_PATTERNS: List[str] = [
    r"\b(scan|full\s*scan)\b",  # Scan operations (expensive)
    r"\b(gsi|global\s*secondary)\b",  # GSI queries
    r"\b(lsi|local\s*secondary)\b",  # LSI queries
    r"\b(begins_with|contains)\b",  # String functions
    r"\b(between|in)\b",  # Range/set operations
    r"\b(attribute_exists|attribute_not_exists)\b",  # Existence checks
    r"\b(size)\b",  # Size function
    r"\b(index|secondary)\b",  # Index queries
    r"\b(all|every|entire)\s*table\b",  # Full table operations
    r"\b(without|missing)\s*(key|partition)\b",  # Key-less queries
    r"\b(filter|filtered)\b",  # Filter expressions
]


def is_complex_partiql_query(question: str) -> bool:
    """Detect if a question requires complex PartiQL generation."""
    question_lower = question.lower()
    return any(
        re.search(pattern, question_lower) for pattern in DYNAMODB_COMPLEX_PATTERNS
    )


class DynamoDBPromptProvider(PromptProvider):
    """
    Prompt provider for Amazon DynamoDB (PartiQL).

    Key DynamoDB constraints emphasized:
    - Partition key is REQUIRED for efficient Query operations
    - Sort key enables range queries within a partition
    - GSI (Global Secondary Index) allows querying on different attributes
    - LSI (Local Secondary Index) provides alternative sort keys
    - SCAN operations read entire table (expensive - avoid in production)
    - No JOINs - single-table design pattern
    """

    DB_TYPE = "dynamodb"
    QUERY_LANGUAGE = "PartiQL"

    # Standard prompt for simple queries
    SYSTEM_PROMPT_TEMPLATE = """You are an expert Amazon DynamoDB/PartiQL query generator. Convert natural language into PartiQL queries.

CRITICAL DYNAMODB/PartiQL RULES:
1. Generate ONLY SELECT queries - NO INSERT, UPDATE, DELETE
2. PARTITION KEY REQUIRED: For efficient Query operations, include the partition key in WHERE clause
3. Sort key is optional but recommended for efficiency and range queries
4. Use GSI name in FROM clause for index queries: SELECT * FROM "table"."index-name"
5. NO JOINs - DynamoDB uses single-table design pattern
6. SCAN operations (no partition key) are EXPENSIVE - avoid unless explicitly needed
7. Table and attribute names should be in double quotes if they contain special characters

QUERY PATTERNS:
- Query with PK: SELECT * FROM "table" WHERE pk = 'value'
- Query with PK and SK: SELECT * FROM "table" WHERE pk = 'val' AND sk > 100
- GSI query: SELECT * FROM "table"."gsi-name" WHERE gsi_pk = 'value'
- Projection: SELECT attr1, attr2 FROM "table" WHERE pk = 'value'
- Scan (use sparingly): SELECT * FROM "table" WHERE non_key_attr = 'value'

SCHEMA:
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE raw PartiQL query starting with SELECT
- NO markdown code blocks (no ```)
- NO explanations or comments before/after the query
- Use double quotes for table/index names if needed
- Just the pure PartiQL statement, nothing else"""

    # Chain-of-Thought prompt for complex queries
    COT_SYSTEM_PROMPT_TEMPLATE = """You are an expert Amazon DynamoDB/PartiQL query generator. Convert natural language into PartiQL queries.

CRITICAL DYNAMODB/PartiQL RULES:
1. Generate ONLY SELECT queries - NO INSERT, UPDATE, DELETE
2. PARTITION KEY REQUIRED: For efficient Query operations, include the partition key in WHERE clause
3. Sort key is optional but recommended for efficiency and range queries
4. Use GSI name in FROM clause for index queries: SELECT * FROM "table"."index-name"
5. NO JOINs - DynamoDB uses single-table design pattern
6. SCAN operations (no partition key) are EXPENSIVE - avoid unless explicitly needed
7. Table and attribute names should be in double quotes if they contain special characters

QUERY PATTERNS:
- Query with PK: SELECT * FROM "table" WHERE pk = 'value'
- Query with PK and SK: SELECT * FROM "table" WHERE pk = 'val' AND sk > 100
- GSI query: SELECT * FROM "table"."gsi-name" WHERE gsi_pk = 'value'
- Projection: SELECT attr1, attr2 FROM "table" WHERE pk = 'value'
- Scan (use sparingly): SELECT * FROM "table" WHERE non_key_attr = 'value'

SCHEMA:
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

THINK STEP BY STEP before writing the query:
1. TABLE: Which table contains the data needed?
2. PARTITION KEY: What is the partition key? Is it in the WHERE clause? (REQUIRED for Query)
3. SORT KEY: Is the sort key needed for range queries?
4. GSI/LSI: Should we query an index instead of the main table?
   - Check if any GSI matches the filter criteria better
   - LSI can provide alternative sort keys on the same partition
5. FILTER: What additional filtering is needed after key conditions?
6. PROJECTION: What attributes to return? Use specific attributes to reduce data transfer.
7. SCAN WARNING: Is this a scan (no partition key)? If yes, warn about cost and performance!

After reasoning through these steps, write the final PartiQL query.

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE raw PartiQL query starting with SELECT
- NO markdown code blocks (no ```)
- NO explanations or comments before/after the query
- Use double quotes for table/index names if needed
- Just the pure PartiQL statement, nothing else"""

    @classmethod
    def get_system_prompt(cls, schema: str, history: str, **kwargs) -> str:
        """Generate PartiQL system prompt with optional few-shot examples and CoT for complex queries."""
        # Format few-shot examples if provided
        few_shot_examples = kwargs.get("few_shot_examples", [])
        few_shot_section = ""

        if few_shot_examples:
            few_shot_section = (
                "\nSIMILAR QUERIES FROM THIS DATABASE (use as reference):\n"
            )
            for i, example in enumerate(few_shot_examples[:3], 1):
                question = example.get("natural_query", "")[:150]
                sql = example.get("sql", "")[:400]
                if question and sql:
                    few_shot_section += (
                        f"Example {i}:\n  Question: {question}\n  PartiQL: {sql}\n\n"
                    )

        # Determine if we should use Chain-of-Thought for complex queries
        user_question = kwargs.get("question", "")
        use_cot = is_complex_partiql_query(user_question) if user_question else False

        # Select appropriate template
        template = (
            cls.COT_SYSTEM_PROMPT_TEMPLATE if use_cot else cls.SYSTEM_PROMPT_TEMPLATE
        )

        return template.format(
            schema=schema,
            history=history or "No previous conversation",
            few_shot_section=few_shot_section,
        )

    @classmethod
    def clean_response(cls, response: str) -> str:
        """Clean PartiQL response from LLM."""
        query = cls._remove_markdown_blocks(response)

        # Try to find SELECT statement if doesn't start with it
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            select_match = re.search(
                r"(SELECT\s+[\s\S]+?)(?:;|\Z)", query, re.IGNORECASE
            )
            if select_match:
                query = select_match.group(1)

        # Remove comments
        query = re.sub(r"^--.*?\n", "", query, flags=re.MULTILINE)
        query = re.sub(r"/\*.*?\*/", "", query, flags=re.DOTALL)

        query = query.strip()

        # Remove trailing semicolon
        query = query.rstrip(";").strip()

        return query

    @classmethod
    def get_explain_prompt(cls, query: str, schema: str) -> str:
        """Generate prompt for explaining a PartiQL query."""
        return f"""Explain this PartiQL (DynamoDB) query in plain English for a business user. Be concise and clear.

Query:
```partiql
{query}
```

Schema:
{schema}

Include in your explanation:
- **Summary:** One sentence description of what this query retrieves
- **Key Access:** What partition key and sort key are used?
- **Index Usage:** Is this using a GSI or LSI? Which one?
- **Efficiency:** Is this a Query (efficient) or Scan (expensive)?
- **Results:** What attributes are returned?

If the query is a SCAN (no partition key in WHERE), explicitly warn that:
- It reads the entire table
- It can be slow and expensive on large tables
- Consider adding partition key filter or using an index"""
