"""
QueryfyAI - MongoDB Prompt Provider

Prompt provider for MongoDB (MQL - MongoDB Query Language)
"""

import re
from typing import List

from .base import PromptProvider

# Patterns that indicate a complex MongoDB query requiring reasoning steps
MONGODB_COMPLEX_PATTERNS: List[str] = [
    r"\b(aggregate|aggregation|pipeline)\b",  # Aggregation queries
    r"\b(join|lookup|combine|merge)\b",  # $lookup operations
    r"\b(group|grouped|grouping)\b",  # $group operations
    r"\b(compare|versus|vs\.?|difference)\b",  # Comparison queries
    r"\b(trend|growth|change|over time)\b",  # Time-series analysis
    r"\b(top|bottom|rank|best|worst)\s+\d+",  # Ranked results
    r"\b(ratio|percentage|percent|proportion)\b",  # Calculated metrics
    r"\b(average|sum|count|total)\s+.*(by|per|for each)\b",  # Grouped aggregates
    r"\b(unwind|flatten|expand)\b",  # Array operations
    r"\b(bucket|facet|partition)\b",  # Advanced aggregation
]


def is_complex_mongodb_query(question: str) -> bool:
    """Detect if a question requires complex MongoDB aggregation."""
    question_lower = question.lower()
    return any(
        re.search(pattern, question_lower) for pattern in MONGODB_COMPLEX_PATTERNS
    )


class MongoDBPromptProvider(PromptProvider):
    """
    Prompt provider for MongoDB.

    Handles MongoDB Query Language (MQL) with find(), findOne(), aggregate().
    """

    DB_TYPE = "mongodb"
    QUERY_LANGUAGE = "MongoDB"

    # Standard prompt for simple MongoDB queries
    SYSTEM_PROMPT_TEMPLATE = """You are an expert MongoDB query generator. Convert natural language into MongoDB queries.

CRITICAL RULES:
1. Generate ONLY ONE query - never multiple queries
2. Use ONLY read operations: find(), findOne(), aggregate()
3. NO insert, update, delete, drop, createIndex operations
4. Use exact collection and field names from the schema below
5. For complex analytics, use aggregate() with pipeline stages

QUERY FORMATS:
- Simple query: db.collection.find({{filter}})
- With projection: db.collection.find({{filter}}, {{field: 1, _id: 0}})
- Single document: db.collection.findOne({{filter}})
- Aggregation: db.collection.aggregate([{{$match: {{...}}}}, {{$group: {{...}}}}])

AGGREGATION STAGES:
- $match: Filter documents
- $group: Group and aggregate (see $group RULES below)
- $sort: Sort results
- $limit: Limit results
- $project: Shape output fields
- $lookup: Join collections

$group STAGE RULES (CRITICAL - follow exactly):
- _id: The field(s) to group by (required)
- EVERY other field MUST use an accumulator operator - NEVER just a field reference
- Accumulators: $sum, $avg, $min, $max, $first, $last, $push, $addToSet, $count
- To include a non-aggregated field, use $first or $last

CORRECT $group example:
{{$group: {{_id: "$region", total_sales: {{$sum: "$amount"}}, rep_name: {{$first: "$salesperson_name"}}}}}}

WRONG (will error - field without accumulator):
{{$group: {{_id: "$region", salesperson_name: "$salesperson_name"}}}}

SCHEMA (Collections and Fields):
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE MongoDB query starting with db.
- NO markdown code blocks (no ```)
- NO explanations or comments
- NO multiple queries on separate lines
- NO semicolons at the end
- If user asks about "all data" or "everything", pick the most relevant collection
- Just the single pure MongoDB query, nothing else

EXAMPLE OUTPUT:
db.users.find({{"status": "active"}}, {{"name": 1, "email": 1}})"""

    # Chain-of-Thought prompt for complex MongoDB aggregation queries
    COT_SYSTEM_PROMPT_TEMPLATE = """You are an expert MongoDB query generator. Convert natural language into MongoDB queries.

CRITICAL RULES:
1. Generate ONLY ONE query - never multiple queries
2. Use ONLY read operations: find(), findOne(), aggregate()
3. NO insert, update, delete, drop, createIndex operations
4. Use exact collection and field names from the schema below
5. For complex analytics, use aggregate() with pipeline stages

QUERY FORMATS:
- Simple query: db.collection.find({{filter}})
- With projection: db.collection.find({{filter}}, {{field: 1, _id: 0}})
- Single document: db.collection.findOne({{filter}})
- Aggregation: db.collection.aggregate([{{$match: {{...}}}}, {{$group: {{...}}}}])

AGGREGATION STAGES REFERENCE:
- $match: Filter documents (like WHERE in SQL)
- $group: Group by _id field and aggregate (see CRITICAL $group RULES below)
- $sort: Sort results (1 = ascending, -1 = descending)
- $limit: Limit number of results
- $skip: Skip N documents
- $project: Shape output fields (1 = include, 0 = exclude)
- $lookup: Join with another collection (like LEFT JOIN)
- $unwind: Flatten arrays into separate documents
- $addFields: Add computed fields
- $bucket: Group into ranges/buckets
- $facet: Multiple aggregation pipelines in parallel

CRITICAL $group STAGE RULES (MUST follow - MongoDB will error otherwise):
1. _id field: Specifies what to group by (required). Use null for single-group aggregation.
2. ALL other fields MUST be accumulator objects - NEVER just a field reference like "$fieldname"
3. Available accumulators:
   - $sum: Sum values (use {{$sum: 1}} to count)
   - $avg: Average of values
   - $min / $max: Minimum / maximum value
   - $first / $last: First or last value in the group (USE THIS to preserve non-aggregated fields)
   - $push: Collect all values into an array
   - $addToSet: Collect unique values into an array
   - $count: Count documents (MongoDB 5.0+)

CORRECT $group examples:
  {{$group: {{_id: "$category", total: {{$sum: "$price"}}, count: {{$sum: 1}}}}}}
  {{$group: {{_id: "$region", sales: {{$sum: "$amount"}}, rep: {{$first: "$salesperson_name"}}}}}}
  {{$group: {{_id: null, grand_total: {{$sum: "$revenue"}}}}}}

WRONG $group (MongoDB error: "field must be an accumulator object"):
  {{$group: {{_id: "$region", salesperson_name: "$salesperson_name"}}}}  ← WRONG: missing accumulator
  Fix: {{$group: {{_id: "$region", salesperson_name: {{$first: "$salesperson_name"}}}}}}  ← CORRECT

SCHEMA (Collections and Fields):
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

THINK STEP BY STEP before writing the query:
1. COLLECTION: Which collection contains the main data needed?
2. OPERATION: Is this a simple find() or does it need aggregate()?
3. FILTER ($match): What conditions filter the documents?
4. JOINS ($lookup): Do we need data from other collections?
5. GROUPING ($group): How should data be grouped? What aggregations?
6. PROJECTION ($project): What fields should be in the output?
7. SORTING ($sort): How should results be ordered?
8. LIMITING ($limit): How many results to return?

After reasoning through these steps, write the final MongoDB query.

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE MongoDB query starting with db.
- NO markdown code blocks (no ```)
- NO explanations or comments
- NO multiple queries on separate lines
- NO semicolons at the end
- Just the single pure MongoDB query, nothing else"""

    @classmethod
    def get_system_prompt(cls, schema: str, history: str, **kwargs) -> str:
        """Generate MongoDB system prompt with optional few-shot examples and CoT for complex queries."""
        # Format few-shot examples if provided
        few_shot_examples = kwargs.get("few_shot_examples", [])
        few_shot_section = ""

        if few_shot_examples:
            few_shot_section = (
                "\nSIMILAR QUERIES FROM THIS DATABASE (use as reference):\n"
            )
            for i, example in enumerate(
                few_shot_examples[:3], 1
            ):  # Limit to 3 examples
                question = example.get("natural_query", "")[:150]
                query = example.get("sql", "")[
                    :400
                ]  # 'sql' field stores MongoDB queries too
                if question and query:
                    few_shot_section += (
                        f"Example {i}:\n  Question: {question}\n  Query: {query}\n\n"
                    )

        # Determine if we should use Chain-of-Thought for complex queries
        user_question = kwargs.get("question", "")
        use_cot = is_complex_mongodb_query(user_question) if user_question else False

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
        """Clean MongoDB response from LLM."""
        query = cls._remove_markdown_blocks(response)

        # Handle multiple queries - take only the first one
        if "\ndb." in query or ";\ndb." in query or ";\n" in query:
            lines = [line.strip() for line in query.split("\n") if line.strip()]
            for line in lines:
                if line.startswith("db."):
                    query = line.rstrip(";")
                    break

        # Try to extract the MongoDB query pattern
        mongo_match = re.search(
            r"(db\.\w+\.(find|findOne|aggregate)\s*\([\s\S]*?\))\s*;?\s*$",
            query,
            re.IGNORECASE,
        )
        if mongo_match:
            query = mongo_match.group(1)
        elif query.startswith("db."):
            # Already starts with db., take first complete query
            # Handle nested parentheses
            query = cls._extract_first_query(query)

        # Remove trailing semicolon
        query = query.rstrip(";").strip()

        return query

    @classmethod
    def _extract_first_query(cls, text: str) -> str:
        """Extract first complete MongoDB query handling nested parentheses."""
        if not text.startswith("db."):
            return text

        depth = 0
        in_string = False
        string_char = None
        end_pos = len(text)

        for i, char in enumerate(text):
            # Track string boundaries
            if char in "\"'":
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char and (i == 0 or text[i - 1] != "\\"):
                    in_string = False

            if not in_string:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end_pos = i + 1
                        break

        return text[:end_pos]

    @classmethod
    def get_explain_prompt(cls, query: str, schema: str) -> str:
        """MongoDB-specific explanation prompt."""
        return f"""Explain this MongoDB query in plain English for a business user. Be concise and clear.

MongoDB Query:
```
{query}
```

Collections Schema:
{schema}

Format your response with:
**Summary:** [One sentence describing what data this query retrieves]
**How it works:**
- [What collection is being queried]
- [What filters are applied]
- [What fields are returned or how data is aggregated]
**Results:** [Description of the output]"""
