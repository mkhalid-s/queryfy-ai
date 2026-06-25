"""
QueryfyAI - Answer Generator Service

Transforms SQL query results into insight-rich natural language answers.
This is the core differentiator of the AI Data Analyst feature.

The goal is to shift from:
  "The query returned 10 rows with customer names and revenue"
To:
  "Your top 10 customers generated $15.2M in revenue, with Acme Corp leading
   at $2.4M. Key insight: Top 3 customers account for 60% of total revenue."
"""

# Disable LiteLLM telemetry before import
import os

os.environ.setdefault("LITELLM_TELEMETRY", "False")

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from litellm import acompletion

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.telemetry import get_tracer
from app.models.analyst_models import ChartSpec, ChartType
from app.models.schemas import LLMConfig
from app.services.llm_service import LLMService, LLMUsageData

logger = get_logger(__name__)
_tracer = get_tracer(__name__)


@dataclass
class AnswerResult:
    """Result from answer generation."""
    answer: str
    key_findings: List[str]
    confidence: float
    chart: Optional[ChartSpec]
    reasoning: Optional[str]
    usage: Optional[Dict[str, Any]]


class AnswerGenerator:
    """
    Transforms SQL results into insight-rich answers.

    Key capabilities:
    1. Synthesizes natural language answers from query results
    2. Extracts key findings as bullet points
    3. Detects opportunities for visualization
    4. Provides confidence scores
    """

    SYSTEM_PROMPT = """You are an AI Data Analyst providing insights from data.

Your task is to analyze query results and provide a clear, insightful answer to the user's question.

## Output Format

Provide your response in the following JSON format:
```json
{
  "answer": "A direct, concise answer to the question (2-4 sentences). Be specific with numbers and percentages.",
  "key_findings": [
    "First key insight or finding",
    "Second key insight",
    "Third key insight (3-5 findings total)"
  ],
  "confidence": 0.85,
  "chart_recommendation": {
    "should_chart": true,
    "chart_type": "bar",
    "x_column": "customer_name",
    "y_column": "revenue",
    "reason": "Bar chart best shows comparison of revenue across customers"
  }
}
```

## Guidelines

1. **Answer**: Lead with the direct answer. Be specific with numbers, percentages, and comparisons.
   - Good: "Your top 10 customers generated $15.2M in revenue, representing 42% of total sales."
   - Bad: "The query returned 10 rows showing customer data."

2. **Key Findings**: Extract 3-5 actionable insights:
   - Identify patterns, anomalies, or trends
   - Note concentration risks or outliers
   - Provide business context where possible
   - Include specific numbers

3. **Confidence**: Rate 0.0-1.0 based on:
   - 0.9-1.0: Complete data, clear answer
   - 0.7-0.9: Good data, some assumptions
   - 0.5-0.7: Partial data or ambiguous results
   - Below 0.5: Incomplete or uncertain

4. **Chart Recommendation**: Suggest visualization when appropriate:
   - "bar": Comparing categories (top N, by group)
   - "line": Time series or trends
   - "pie": Composition/percentages (limited categories)
   - "scatter": Correlation between two metrics
   - Set should_chart=false if data isn't suitable for visualization

## Examples

### Example 1: Top Customers Query
Question: "Who are my top 10 customers?"
Results: 10 rows with customer_name, total_revenue columns

Good Response:
```json
{
  "answer": "Your top 10 customers generated $15.2M in total revenue. Acme Corp leads with $2.4M (15.8% of top 10), followed by GlobalTech at $1.8M. The top 3 customers alone account for 40% of this revenue.",
  "key_findings": [
    "Acme Corp is your largest customer at $2.4M revenue",
    "Top 3 customers represent 40% of top-10 revenue (concentration risk)",
    "Average revenue per top-10 customer is $1.52M",
    "7 of 10 are enterprise-segment customers"
  ],
  "confidence": 0.95,
  "chart_recommendation": {
    "should_chart": true,
    "chart_type": "bar",
    "x_column": "customer_name",
    "y_column": "total_revenue",
    "reason": "Bar chart clearly shows revenue comparison across customers"
  }
}
```

### Example 2: Trend Query
Question: "How have sales changed over the last 6 months?"
Results: 6 rows with month, total_sales columns

Good Response:
```json
{
  "answer": "Sales have grown 23% over the last 6 months, from $1.2M in July to $1.48M in December. Growth has been steady with an average monthly increase of 4.2%.",
  "key_findings": [
    "Overall growth of 23% ($280K increase)",
    "Strongest month: October with 8% growth",
    "Slight dip in September (-2%) before recovery",
    "Q4 outperformed Q3 by 15%"
  ],
  "confidence": 0.92,
  "chart_recommendation": {
    "should_chart": true,
    "chart_type": "line",
    "x_column": "month",
    "y_column": "total_sales",
    "reason": "Line chart shows trend progression over time"
  }
}
```

Remember: Your answer should provide value beyond what's obvious from the raw data. Don't just describe the data - interpret it."""

    @classmethod
    async def generate(
        cls,
        llm_config: LLMConfig,
        question: str,
        sql: str,
        result: Dict[str, Any],
        db_type: str = "postgresql",
        include_reasoning: bool = False,
    ) -> AnswerResult:
        """
        Generate an analyst answer from query results.

        Args:
            llm_config: LLM configuration
            question: Original natural language question
            sql: Generated SQL query
            result: Query results (columns, rows, row_count)
            db_type: Database type for context
            include_reasoning: Include LLM reasoning in output

        Returns:
            AnswerResult with answer, findings, confidence, and optional chart
        """
        span = _tracer.start_span("answer_generator.generate")
        span.set_attribute("question_length", len(question))
        span.set_attribute("row_count", result.get("row_count", 0))

        try:
            # Build the prompt with result summary
            result_summary = cls._summarize_result(result)
            prompt = cls._build_prompt(question, sql, result_summary)

            # Call LLM
            messages = [
                {"role": "system", "content": cls.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            response_text, usage = await cls._call_llm(llm_config, messages)

            # Parse the response
            parsed = cls._parse_response(response_text, result)

            # Build chart spec if recommended
            chart = None
            if parsed.get("chart_recommendation", {}).get("should_chart"):
                chart = cls._build_chart_spec(
                    parsed["chart_recommendation"],
                    result
                )

            span.set_attribute("confidence", parsed.get("confidence", 0.8))
            span.set_attribute("has_chart", chart is not None)
            span.set_attribute("findings_count", len(parsed.get("key_findings", [])))

            logger.info(
                "Answer generated",
                confidence=parsed.get("confidence", 0.8),
                findings_count=len(parsed.get("key_findings", [])),
                has_chart=chart is not None,
            )

            return AnswerResult(
                answer=parsed.get("answer", "Unable to generate answer from results."),
                key_findings=parsed.get("key_findings", []),
                confidence=parsed.get("confidence", 0.8),
                chart=chart,
                reasoning=response_text if include_reasoning else None,
                usage=usage.to_dict() if usage else None,
            )

        except Exception as e:
            span.record_exception(e)
            logger.error("Answer generation failed", error=str(e))

            # Return fallback answer
            return AnswerResult(
                answer=cls._generate_fallback_answer(question, result),
                key_findings=[],
                confidence=0.5,
                chart=None,
                reasoning=None,
                usage=None,
            )
        finally:
            span.end()

    @classmethod
    def _summarize_result(cls, result: Dict[str, Any], max_rows: int = 30) -> str:
        """
        Summarize query results for the prompt.

        Keeps the summary concise to avoid overwhelming the LLM
        while providing enough data for meaningful insights.
        """
        columns = result.get("columns", [])
        rows = result.get("rows", [])
        total_rows = result.get("row_count", len(rows))

        summary_parts = []

        # Column info
        summary_parts.append(f"Columns: {', '.join(columns)}")
        summary_parts.append(f"Total rows: {total_rows}")

        # Sample data (limit to max_rows)
        if rows:
            sample_rows = rows[:max_rows]
            summary_parts.append(f"\nData ({len(sample_rows)} of {total_rows} rows):")

            # Format as a simple table
            for i, row in enumerate(sample_rows):
                if isinstance(row, dict):
                    row_values = [str(row.get(col, "")) for col in columns]
                elif isinstance(row, (list, tuple)):
                    row_values = [str(v) for v in row]
                else:
                    row_values = [str(row)]

                # Truncate long values
                row_values = [v[:50] + "..." if len(v) > 50 else v for v in row_values]
                summary_parts.append(f"  {i+1}. {' | '.join(row_values)}")

            if total_rows > max_rows:
                summary_parts.append(f"  ... and {total_rows - max_rows} more rows")

        # Add basic statistics for numeric columns if possible
        stats = cls._compute_basic_stats(columns, rows)
        if stats:
            summary_parts.append(f"\nBasic Statistics:\n{stats}")

        return "\n".join(summary_parts)

    @classmethod
    def _compute_basic_stats(cls, columns: List[str], rows: List[Any]) -> str:
        """Compute basic statistics for numeric columns."""
        if not rows:
            return ""

        stats_parts = []

        for i, col in enumerate(columns):
            # Try to extract numeric values
            values = []
            for row in rows[:100]:  # Sample first 100 rows
                try:
                    if isinstance(row, dict):
                        val = row.get(col)
                    elif isinstance(row, (list, tuple)):
                        val = row[i] if i < len(row) else None
                    else:
                        continue

                    if val is not None and isinstance(val, (int, float)):
                        values.append(float(val))
                    elif val is not None:
                        # Try to parse string as number
                        parsed = float(str(val).replace(",", "").replace("$", ""))
                        values.append(parsed)
                except (ValueError, TypeError, IndexError):
                    continue

            if len(values) >= 3:  # Only show stats if we have enough values
                total = sum(values)
                avg = total / len(values)
                min_val = min(values)
                max_val = max(values)
                stats_parts.append(
                    f"  {col}: sum={total:,.2f}, avg={avg:,.2f}, min={min_val:,.2f}, max={max_val:,.2f}"
                )

        return "\n".join(stats_parts) if stats_parts else ""

    @classmethod
    def _build_prompt(cls, question: str, sql: str, result_summary: str) -> str:
        """Build the prompt for answer generation."""
        return f"""## User Question
{question}

## SQL Query Executed
```sql
{sql}
```

## Query Results
{result_summary}

## Your Task
Analyze these results and provide an insightful answer to the user's question.
Respond with the JSON format specified in the system prompt."""

    @classmethod
    async def _call_llm(
        cls,
        config: LLMConfig,
        messages: List[Dict],
    ) -> Tuple[str, Optional[LLMUsageData]]:
        """
        Call the LLM using LiteLLM or OAuth Gateway.

        Routes OAuth Gateway provider calls through the proper OAuth handler
        since LiteLLM doesn't support OAuth natively.
        """
        try:
            # Route OAuth Gateway calls through LLMService
            if config.provider == "oauth_gateway":
                content, usage = await LLMService._call_oauth_gateway(
                    config,
                    messages,
                    temperature=0.3,
                    max_tokens=1500,
                    stream=False,
                )
                return content, usage

            # Standard LiteLLM call for other providers
            model = LLMService._get_model_string(config)
            api_config = LLMService._get_api_config(config)

            response = await acompletion(
                model=model,
                messages=messages,
                temperature=0.3,  # Slightly higher for more varied insights
                max_tokens=1500,
                num_retries=2,
                request_timeout=settings.AGENT_TIMEOUT_SECONDS,
                **api_config,
            )

            content = response.choices[0].message.content

            # Build usage data
            usage = None
            if hasattr(response, "usage") and response.usage:
                usage = LLMUsageData(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    model=model,
                    cost_usd=cls._calculate_cost(response.usage, model),
                    cached=False,
                )

            return content, usage

        except Exception as e:
            logger.error("LLM call failed in answer generator", error=str(e))
            raise

    @classmethod
    def _calculate_cost(cls, usage, model: str) -> float:
        """Estimate cost based on token usage."""
        # Rough cost estimates per 1K tokens
        cost_per_1k = {
            "gpt-4": (0.03, 0.06),
            "gpt-4o": (0.005, 0.015),
            "gpt-4o-mini": (0.00015, 0.0006),
            "claude-3-opus": (0.015, 0.075),
            "claude-3-sonnet": (0.003, 0.015),
            "claude-3-haiku": (0.00025, 0.00125),
        }

        # Default costs
        input_cost_per_1k = 0.01
        output_cost_per_1k = 0.03

        for model_prefix, (input_c, output_c) in cost_per_1k.items():
            if model_prefix in model.lower():
                input_cost_per_1k = input_c
                output_cost_per_1k = output_c
                break

        input_cost = (usage.prompt_tokens / 1000) * input_cost_per_1k
        output_cost = (usage.completion_tokens / 1000) * output_cost_per_1k

        return round(input_cost + output_cost, 6)

    @classmethod
    def _parse_response(cls, response_text: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse LLM response into structured format.

        Handles both clean JSON and mixed text responses.
        """
        # Try to extract JSON from response
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try direct JSON parse
        try:
            # Find JSON object in response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response_text[json_start:json_end])
        except json.JSONDecodeError:
            pass

        # Fallback: extract content manually
        return cls._extract_manually(response_text)

    @classmethod
    def _extract_manually(cls, response_text: str) -> Dict[str, Any]:
        """
        Manually extract answer and findings from non-JSON response.
        """
        lines = response_text.strip().split("\n")
        answer = ""
        findings = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if it's a bullet point (finding)
            if line.startswith(("-", "*", "•")) or re.match(r"^\d+\.", line):
                finding = re.sub(r"^[-*•\d.]+\s*", "", line)
                if finding and len(finding) > 10:
                    findings.append(finding)
            elif not findings and line:
                # Still in answer section
                answer += line + " "

        return {
            "answer": answer.strip() or "Analysis complete. See the data for details.",
            "key_findings": findings[:5],
            "confidence": 0.7,
            "chart_recommendation": {"should_chart": False},
        }

    @classmethod
    def _build_chart_spec(
        cls,
        recommendation: Dict[str, Any],
        result: Dict[str, Any]
    ) -> Optional[ChartSpec]:
        """Build ChartSpec from recommendation and result data."""
        try:
            chart_type_str = recommendation.get("chart_type", "bar")
            x_column = recommendation.get("x_column")
            y_column = recommendation.get("y_column")

            if not x_column or not y_column:
                return None

            # Map string to ChartType enum
            chart_type_map = {
                "bar": ChartType.BAR,
                "line": ChartType.LINE,
                "pie": ChartType.PIE,
                "scatter": ChartType.SCATTER,
                "area": ChartType.AREA,
                "horizontal_bar": ChartType.HORIZONTAL_BAR,
            }
            chart_type = chart_type_map.get(chart_type_str, ChartType.BAR)

            # Extract data for chart
            columns = result.get("columns", [])
            rows = result.get("rows", [])

            # Find column indices
            x_idx = columns.index(x_column) if x_column in columns else None
            y_idx = columns.index(y_column) if y_column in columns else None

            if x_idx is None or y_idx is None:
                return None

            # Build chart data
            chart_data = []
            for row in rows[:50]:  # Limit to 50 data points
                if isinstance(row, dict):
                    x_val = row.get(x_column)
                    y_val = row.get(y_column)
                elif isinstance(row, (list, tuple)):
                    x_val = row[x_idx] if x_idx < len(row) else None
                    y_val = row[y_idx] if y_idx < len(row) else None
                else:
                    continue

                if x_val is not None and y_val is not None:
                    chart_data.append({x_column: x_val, y_column: y_val})

            if not chart_data:
                return None

            return ChartSpec(
                chart_type=chart_type,
                x_axis=x_column,
                y_axis=y_column,
                data=chart_data,
                title=recommendation.get("reason"),
            )

        except Exception as e:
            logger.warning("Failed to build chart spec", error=str(e))
            return None

    @classmethod
    def _generate_fallback_answer(cls, question: str, result: Dict[str, Any]) -> str:
        """Generate a basic fallback answer when LLM fails."""
        row_count = result.get("row_count", 0)
        columns = result.get("columns", [])

        if row_count == 0:
            return "The query returned no results. You may want to adjust your criteria or verify the data exists."

        if row_count == 1:
            return f"Found 1 result with the following data: {', '.join(columns)}. See the data tab for details."

        return f"Found {row_count} results across {len(columns)} columns ({', '.join(columns[:3])}{'...' if len(columns) > 3 else ''}). Review the data tab for the complete results."
