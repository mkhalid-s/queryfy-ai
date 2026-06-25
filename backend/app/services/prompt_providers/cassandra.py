"""
QueryfyAI - Cassandra Prompt Provider

Prompt provider for Apache Cassandra (CQL - Cassandra Query Language).
Emphasizes partition key requirements and Cassandra-specific constraints.
"""

import re
from typing import List

from .base import PromptProvider

# Patterns that indicate a complex CQL query requiring reasoning steps
CASSANDRA_COMPLEX_PATTERNS: List[str] = [
    r"\b(aggregate|aggregation)\b",  # Aggregation (limited in Cassandra)
    r"\b(group\s+by|grouped)\b",  # GROUP BY queries
    r"\b(count|sum|avg|min|max)\b",  # Aggregate functions
    r"\b(token|partition)\b",  # Token-based queries
    r"\b(allow\s+filtering)\b",  # Full scan queries
    r"\b(secondary\s+index|index)\b",  # Index-based queries
    r"\b(time\s*series|timeseries)\b",  # Time-series patterns
    r"\b(clustering|order\s+by)\b",  # Clustering key queries
    r"\b(range|between|from\s+\w+\s+to)\b",  # Range queries on clustering key
    r"\b(latest|recent|newest|oldest)\b",  # Time-based ordering
    r"\b(multiple|several|all)\s+(partition|key)",  # Multi-partition queries
]


def is_complex_cql_query(question: str) -> bool:
    """Detect if a question requires complex CQL generation."""
    question_lower = question.lower()
    return any(
        re.search(pattern, question_lower) for pattern in CASSANDRA_COMPLEX_PATTERNS
    )


class CassandraPromptProvider(PromptProvider):
    """
    Prompt provider for Apache Cassandra (CQL).

    Key Cassandra constraints emphasized:
    - Partition key MUST be in WHERE clause for efficient queries
    - Clustering keys determine sort order within partition
    - No JOINs - data model is denormalized
    - ALLOW FILTERING should be avoided in production
    - ORDER BY only works on clustering columns
    """

    DB_TYPE = "cassandra"
    QUERY_LANGUAGE = "CQL"

    # Standard prompt for simple queries
    SYSTEM_PROMPT_TEMPLATE = """You are an expert Cassandra/CQL query generator. Convert natural language into CQL queries.

CRITICAL CQL RULES:
1. Generate ONLY SELECT queries - NO INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE
2. PARTITION KEY REQUIRED: Every WHERE clause MUST include ALL partition key columns
3. Clustering keys determine sort order - use for range queries
4. NO JOINs - Cassandra uses denormalized data model
5. ALLOW FILTERING should be AVOIDED unless explicitly requested (causes full scan)
6. ORDER BY only works on clustering columns and must match table's clustering order

QUERY PATTERNS:
- Simple lookup: SELECT * FROM keyspace.table WHERE partition_key = 'value'
- Range query: SELECT * FROM ks.table WHERE pk = 'val' AND ck > start AND ck < end
- With limit: SELECT * FROM ks.table WHERE pk = 'val' LIMIT 100
- Multi-column PK: SELECT * FROM ks.table WHERE pk1 = 'v1' AND pk2 = 'v2'

SCHEMA:
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE raw CQL query starting with SELECT
- NO markdown code blocks (no ```)
- NO explanations or comments before/after the query
- Include keyspace.table format if the question references a specific keyspace
- Just the pure CQL statement, nothing else"""

    # Chain-of-Thought prompt for complex queries
    COT_SYSTEM_PROMPT_TEMPLATE = """You are an expert Cassandra/CQL query generator. Convert natural language into CQL queries.

CRITICAL CQL RULES:
1. Generate ONLY SELECT queries - NO INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE
2. PARTITION KEY REQUIRED: Every WHERE clause MUST include ALL partition key columns
3. Clustering keys determine sort order - use for range queries
4. NO JOINs - Cassandra uses denormalized data model
5. ALLOW FILTERING should be AVOIDED unless explicitly requested (causes full scan)
6. ORDER BY only works on clustering columns and must match table's clustering order

QUERY PATTERNS:
- Simple lookup: SELECT * FROM keyspace.table WHERE partition_key = 'value'
- Range query: SELECT * FROM ks.table WHERE pk = 'val' AND ck > start AND ck < end
- With limit: SELECT * FROM ks.table WHERE pk = 'val' LIMIT 100
- Multi-column PK: SELECT * FROM ks.table WHERE pk1 = 'v1' AND pk2 = 'v2'

SCHEMA:
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

THINK STEP BY STEP before writing the query:
1. KEYSPACE/TABLE: Which keyspace and table contain the data needed?
2. PARTITION KEY: What are the partition key columns? They MUST ALL be in WHERE clause.
3. CLUSTERING KEYS: Are range queries needed on clustering columns?
4. FILTERS: What additional filtering is needed after partition key?
5. ALLOW FILTERING: Is it required? Only if filtering on non-key columns. WARN about full table scan!
6. COLUMNS: What columns to SELECT? Use specific columns or * for all.
7. ORDERING: Is ORDER BY needed? Remember: only works on clustering columns!
8. LIMITING: How many results? Always consider adding LIMIT for safety.

After reasoning through these steps, write the final CQL query.

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE raw CQL query starting with SELECT
- NO markdown code blocks (no ```)
- NO explanations or comments before/after the query
- Include keyspace.table format if the question references a specific keyspace
- Just the pure CQL statement, nothing else"""

    @classmethod
    def get_system_prompt(cls, schema: str, history: str, **kwargs) -> str:
        """Generate CQL system prompt with optional few-shot examples and CoT for complex queries."""
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
                        f"Example {i}:\n  Question: {question}\n  CQL: {sql}\n\n"
                    )

        # Determine if we should use Chain-of-Thought for complex queries
        user_question = kwargs.get("question", "")
        use_cot = is_complex_cql_query(user_question) if user_question else False

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
        """Clean CQL response from LLM."""
        query = cls._remove_markdown_blocks(response)

        # If doesn't start with SELECT, try to find it
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            # Try to find SELECT statement
            select_match = re.search(
                r"(SELECT\s+[\s\S]+?)(?:;|\Z)", query, re.IGNORECASE
            )
            if select_match:
                query = select_match.group(1)

        # Remove CQL comments (-- style)
        query = re.sub(r"^--.*?\n", "", query, flags=re.MULTILINE)

        # Remove /* */ style comments
        query = re.sub(r"/\*.*?\*/", "", query, flags=re.DOTALL)

        query = query.strip()

        # Remove trailing semicolon (we add it when needed)
        query = query.rstrip(";").strip()

        return query

    @classmethod
    def get_explain_prompt(cls, query: str, schema: str) -> str:
        """Generate prompt for explaining a CQL query."""
        return f"""Explain this CQL (Cassandra Query Language) query in plain English for a business user. Be concise and clear.

Query:
```cql
{query}
```

Schema:
{schema}

Include in your explanation:
- **Summary:** One sentence description of what this query retrieves
- **Partition Key:** Which partition(s) this query accesses
- **Efficiency:** Is this an efficient query? Does it use partition key properly?
- **Results:** What the output columns represent

If the query uses ALLOW FILTERING, warn that it performs a full table scan and may be slow on large datasets."""
