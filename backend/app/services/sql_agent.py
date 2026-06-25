"""
QueryfyAI - Simple Self-Healing SQL Agent

A minimal LangGraph agent that:
1. Generates SQL from natural language
2. Validates and auto-fixes errors
3. Scales horizontally with PostgreSQL state

Complexity: LOW
Scalability: HIGH
Dependencies: langgraph, litellm (both as libraries)
"""

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

# LangGraph - as library, not service
from langgraph.graph import END, StateGraph

from app.api.metrics import record_agent_run
from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.telemetry import get_tracer
from app.models.schemas import DatabaseConfig, LLMConfig
from app.services.database_service import DatabaseService
from app.services.error_classifier import ErrorClassifier, RetryStrategy
from app.services.llm_service import (
    LLMService as SimpleLLMService,
)
from app.services.llm_service import (
    LLMUsageData,
)
from app.services.result_validator import ResultValidator
from app.services.session_store import session_store

logger = get_logger(__name__)

# Get tracer for this module
_tracer = get_tracer(__name__)


# ============================================================================
# STATE - What the agent tracks
# ============================================================================


class AgentState(TypedDict):
    """Simple state - just what we need, nothing more"""

    # Input
    question: str
    schema: str
    db_type: str

    # Processing
    sql: Optional[str]
    error: Optional[str]
    attempt: int

    # Error classification (adaptive retry)
    error_type: Optional[str]
    retry_strategy: Optional[str]
    retry_prompt_modifier: str

    # Result validation
    validation: Optional[Dict[str, Any]]
    validation_retry_count: int

    # Output
    result: Optional[Dict]
    explanation: Optional[str]
    status: str  # "success", "error", "max_retries"

    # Accumulator for messages (for debugging)
    messages: Annotated[List[str], operator.add]

    # Conversation context for follow-up queries
    conversation_history: List[Dict]

    # LLM usage tracking (aggregated across all calls)
    total_usage: Optional[Dict[str, Any]]


# ============================================================================
# AGENT NODES - Each does ONE thing
# ============================================================================


def _aggregate_usage(
    existing: Optional[Dict[str, Any]], new_usage: Optional[LLMUsageData]
) -> Dict[str, Any]:
    """Aggregate LLM usage data across multiple calls"""
    if not new_usage:
        return existing or {}

    new_dict = new_usage.to_dict() if hasattr(new_usage, "to_dict") else {}

    if not existing:
        return new_dict

    # Aggregate token counts and costs
    return {
        "prompt_tokens": existing.get("prompt_tokens", 0)
        + new_dict.get("prompt_tokens", 0),
        "completion_tokens": existing.get("completion_tokens", 0)
        + new_dict.get("completion_tokens", 0),
        "total_tokens": existing.get("total_tokens", 0)
        + new_dict.get("total_tokens", 0),
        "model": new_dict.get("model", existing.get("model", "")),
        "cost_usd": existing.get("cost_usd", 0.0) + new_dict.get("cost_usd", 0.0),
        "cached": existing.get("cached", False) and new_dict.get("cached", False),
        "calls": existing.get("calls", 1) + 1,
    }


class SQLAgentNodes:
    """
    Agent nodes - simple functions that transform state.
    No classes, no complexity - just functions.
    """

    def __init__(self, llm_config: LLMConfig, db_config: DatabaseConfig):
        self.llm_config = llm_config
        self.db_config = db_config

    async def generate_sql(self, state: AgentState) -> AgentState:
        """Generate SQL from question with conversation context"""
        logger.info(
            "Generating SQL",
            query_preview=state["question"][:50],
            attempt=state["attempt"] + 1,
        )

        try:
            # Use previous error as context if retrying
            question = state["question"]

            # Use adaptive retry prompt modifier if available (from error classifier)
            if state.get("retry_prompt_modifier") and state["attempt"] > 0:
                question = f"""{state['retry_prompt_modifier']}

Original question: {state['question']}

Please fix the SQL query."""
            elif state.get("error") and state["attempt"] > 0:
                # Fallback to basic error context
                question = f"""Previous SQL failed with error: {state['error']}

Original question: {state['question']}

Please fix the SQL query."""

            # Get conversation history for context continuity
            history = state.get("conversation_history", [])

            # Fetch few-shot examples for learning
            few_shot_examples = []
            negative_examples = []
            try:
                from app.services.vector_db import vector_db

                # Get successful examples
                few_shot_examples = vector_db.find_similar_queries(
                    self.db_config.connection_url, state["question"], n=3
                )

                # Get negative examples (failed queries) to avoid repeating mistakes
                negative_examples = vector_db.find_similar_failures(
                    self.db_config.connection_url, state["question"], limit=2
                )
            except Exception as e:
                logger.debug("Few-shot retrieval skipped in agent", error=str(e))

            # Add negative examples to question to avoid repeating mistakes
            if negative_examples:
                anti_patterns = "\n\nAVOID THESE MISTAKES:\n"
                for neg in negative_examples:
                    anti_patterns += f"- Question: {neg.get('question', '')[:100]}\n"
                    anti_patterns += (
                        f"  Failed SQL: {neg.get('failed_sql', '')[:200]}\n"
                    )
                    anti_patterns += (
                        f"  Error: {neg.get('error_message', '')[:100]}\n\n"
                    )
                question += anti_patterns

            # LLMService now returns (sql, usage) tuple
            sql, usage = await SimpleLLMService.generate_sql(
                config=self.llm_config,
                prompt=question,
                schema=state["schema"],
                history=history,  # Pass conversation history for context
                db_type=state["db_type"],
                few_shot_examples=few_shot_examples,
            )

            # Aggregate usage across retries
            total_usage = _aggregate_usage(state.get("total_usage"), usage)

            return {
                **state,
                "sql": sql,
                "error": None,
                "total_usage": total_usage,
                "messages": [f"Generated SQL (attempt {state['attempt'] + 1})"],
            }

        except Exception as e:
            logger.error(
                "SQL generation failed", error=str(e), attempt=state["attempt"] + 1
            )
            return {**state, "error": str(e), "messages": [f"Generation error: {e}"]}

    async def execute_sql(self, state: AgentState) -> AgentState:
        """Execute SQL and capture results or errors"""
        sql_val = state.get("sql")
        logger.info(
            "Executing SQL",
            sql_preview=sql_val[:100] if sql_val else "none",
        )

        if not state.get("sql"):
            return {
                **state,
                "error": "No SQL to execute",
                "status": "error",
                "error_type": None,
                "retry_strategy": None,
                "retry_prompt_modifier": "",
                "messages": ["No SQL generated"],
            }

        # At this point, sql is guaranteed to be non-None
        sql = state["sql"]
        assert sql is not None, "SQL must be non-None after check"

        try:
            result = await DatabaseService.execute_query(
                config=self.db_config, sql=sql, limit=500
            )

            row_count = len(result.get("rows", []))
            logger.info("SQL executed successfully", row_count=row_count)

            return {
                **state,
                "result": result,
                "error": None,
                "error_type": None,
                "retry_strategy": None,
                "retry_prompt_modifier": "",
                "status": "success",
                "messages": [f"Executed successfully, {row_count} rows"],
            }

        except Exception as e:
            error_msg = str(e)
            logger.warning(
                "SQL execution failed",
                error=error_msg[:200],
                attempt=state["attempt"] + 1,
            )

            # Classify the error for adaptive retry
            error_type, retry_strategy = ErrorClassifier.classify(error_msg)
            retry_prompt_modifier = ""

            if retry_strategy != RetryStrategy.NO_RETRY:
                retry_prompt_modifier = ErrorClassifier.get_retry_prompt_modifier(
                    retry_strategy, error_msg, sql
                )

            logger.info(
                "Error classified",
                error_type=error_type.value,
                retry_strategy=retry_strategy.value,
            )

            # Store as negative example for future learning
            try:
                from app.services.vector_db import vector_db

                vector_db.store_failed_query(
                    connection_url=self.db_config.connection_url,
                    question=state["question"],
                    failed_sql=sql,
                    error_message=error_msg,
                    error_type=error_type.value,
                )
            except Exception as store_err:
                logger.debug("Failed to store negative example", error=str(store_err))

            return {
                **state,
                "error": error_msg,
                "error_type": error_type.value,
                "retry_strategy": retry_strategy.value,
                "retry_prompt_modifier": retry_prompt_modifier,
                "result": None,
                "attempt": state["attempt"] + 1,
                "messages": [
                    f"Execution error ({error_type.value}): {error_msg[:100]}"
                ],
            }

    async def explain_result(self, state: AgentState) -> AgentState:
        """Generate explanation of the query"""

        if state.get("status") != "success":
            return state

        # At this point, sql must be present (status=success means we executed SQL)
        sql = state.get("sql")
        if not sql:
            logger.warning("explain_result called without sql")
            return state

        try:
            # LLMService now returns (explanation, usage) tuple
            explanation, usage = await SimpleLLMService.explain_sql(
                config=self.llm_config,
                sql=sql,
                schema=state["schema"][:2000],
                db_type=state.get("db_type", "postgresql"),
            )

            # Aggregate usage from explain call
            total_usage = _aggregate_usage(state.get("total_usage"), usage)

            logger.info("Generated explanation", has_usage=usage is not None)

            return {
                **state,
                "explanation": explanation,
                "total_usage": total_usage,
                "messages": ["Generated explanation"],
            }

        except Exception as e:
            # Non-critical, continue without explanation
            logger.warning("Explanation skipped", error=str(e))
            return {
                **state,
                "explanation": None,
                "messages": [f"Explanation skipped: {e}"],
            }

    async def validate_result(self, state: AgentState) -> AgentState:
        """Validate query results using LLM to ensure they answer the question"""

        # Skip validation if no results or already failed
        if state.get("status") != "success" or not state.get("result"):
            return {
                **state,
                "validation": None,
                "messages": ["Validation skipped - no results"],
            }

        # At this point, sql and result must be present (status=success)
        sql = state.get("sql")
        result = state.get("result")
        if not sql or not result:
            logger.warning("validate_result called without sql or result")
            return {
                **state,
                "validation": None,
                "messages": ["Validation skipped - missing data"],
            }

        try:
            validation = await ResultValidator.validate(
                llm_config=self.llm_config,
                question=state["question"],
                sql=sql,
                results=result,
                db_type=state["db_type"],
            )

            # Aggregate usage if validation made LLM call
            # Note: ResultValidator uses generate_sql internally which tracks usage

            logger.info(
                "Result validation complete",
                valid=validation.get("valid", True),
                confidence=validation.get("confidence", 0.5),
            )

            # Check if validation suggests regeneration
            validation_retry_count = state.get("validation_retry_count", 0)
            if ResultValidator.should_retry(validation, validation_retry_count):
                # Trigger regeneration due to invalid results
                retry_context = ResultValidator.get_retry_context(validation)
                return {
                    **state,
                    "validation": validation,
                    "validation_retry_count": validation_retry_count + 1,
                    "error": f"Result validation failed: {validation.get('issues', [])}",
                    "status": "validation_failed",
                    "retry_prompt_modifier": retry_context,
                    "messages": [
                        f"Validation failed - regenerating (confidence: {validation.get('confidence', 0)})"
                    ],
                }

            return {
                **state,
                "validation": validation,
                "messages": [
                    f"Validation passed (confidence: {validation.get('confidence', 0.5)})"
                ],
            }

        except Exception as e:
            # Non-critical, continue without validation
            logger.warning("Result validation skipped", error=str(e))
            return {
                **state,
                "validation": {"validated": False, "valid": True, "error": str(e)},
                "messages": [f"Validation skipped: {e}"],
            }


# ============================================================================
# ROUTING - Simple decisions
# ============================================================================


def should_retry(state: AgentState) -> str:
    """Decide: retry, give up, or succeed based on error classification"""

    # Success - proceed to validation
    if state.get("status") == "success":
        return "validate"

    # Validation failed - retry with validation context
    if state.get("status") == "validation_failed":
        validation_retries = state.get("validation_retry_count", 0)
        if validation_retries < 1 and state.get("attempt", 0) < 3:
            return "retry"
        return "explain"  # Give up on validation retries, explain what we have

    # Check retry strategy from error classifier
    retry_strategy = state.get("retry_strategy")
    if retry_strategy == "no_retry":
        logger.info("No retry - error type does not warrant retry")
        return "give_up"

    # Max retries reached
    if state["attempt"] >= 3:
        return "give_up"

    # Has error - retry with classified strategy
    if state.get("error"):
        return "retry"

    return "give_up"


def should_continue_after_validation(state: AgentState) -> str:
    """Decide whether to continue to explain or retry after validation"""

    # If validation failed and triggered retry
    if state.get("status") == "validation_failed":
        if state.get("validation_retry_count", 0) < 1 and state.get("attempt", 0) < 3:
            return "retry"

    # Normal flow - proceed to explain
    return "explain"


def format_final_state(state: AgentState) -> str:
    """Set final status"""
    if state["attempt"] >= 3 and state.get("error"):
        return "max_retries"
    return state.get("status", "error")


# ============================================================================
# AGENT GRAPH - Wire it together
# ============================================================================


def create_sql_agent(
    llm_config: LLMConfig, db_config: DatabaseConfig, use_postgres: bool = False
) -> Any:
    """
    Create a self-healing SQL agent.

    Args:
        llm_config: LLM configuration
        db_config: Database configuration
        use_postgres: Use PostgreSQL for state (for horizontal scaling)

    Returns:
        Compiled LangGraph
    """

    nodes = SQLAgentNodes(llm_config, db_config)

    # Build graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("generate", nodes.generate_sql)
    workflow.add_node("execute", nodes.execute_sql)
    workflow.add_node("validate", nodes.validate_result)
    workflow.add_node("explain", nodes.explain_result)

    # Add edges
    workflow.set_entry_point("generate")
    workflow.add_edge("generate", "execute")

    # Conditional: retry, validate, or give up
    workflow.add_conditional_edges(
        "execute",
        should_retry,
        {
            "retry": "generate",  # Error → try again
            "validate": "validate",  # Success → validate results
            "give_up": END,  # Max retries → stop
        },
    )

    # After validation: explain or retry
    workflow.add_conditional_edges(
        "validate",
        should_continue_after_validation,
        {
            "explain": "explain",  # Valid → explain
            "retry": "generate",  # Invalid → regenerate
        },
    )

    workflow.add_edge("explain", END)

    # Choose checkpointer based on environment
    checkpointer: BaseCheckpointSaver
    if use_postgres and hasattr(settings, "DATABASE_URL") and settings.DATABASE_URL:
        try:
            with PostgresSaver.from_conn_string(settings.DATABASE_URL) as postgres_saver:
                checkpointer = postgres_saver
            logger.info("SQL Agent using PostgreSQL state", mode="scalable")
        except Exception as e:
            logger.warning("PostgreSQL state failed, using memory", error=str(e))
            checkpointer = MemorySaver()
    else:
        checkpointer = MemorySaver()
        logger.debug("SQL Agent using in-memory state", mode="dev")

    return workflow.compile(checkpointer=checkpointer)


# ============================================================================
# SIMPLE API - One function to rule them all
# ============================================================================


class SQLAgent:
    """
    Simple SQL Agent interface.

    Usage:
        agent = SQLAgent(llm_config, db_config)
        result = await agent.query("Show me top customers")
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        db_config: DatabaseConfig,
        schema: str,
        scalable: bool = False,  # Set True in production
    ):
        self.llm_config = llm_config
        self.db_config = db_config
        self.schema = schema
        self.graph = create_sql_agent(llm_config, db_config, use_postgres=scalable)

    async def query(
        self, question: str, session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Answer a natural language question with SQL.

        Returns:
            {
                "success": bool,
                "sql": str,
                "result": {"columns": [...], "rows": [...]},
                "explanation": str,
                "attempts": int,
                "error": str or None
            }
        """
        # Start tracing span for agent query
        span = _tracer.start_span("agent.query")
        span.set_attribute("agent.question_length", len(question))
        span.set_attribute("agent.db_type", self.db_config.db_type)
        span.set_attribute("agent.has_session", session_id is not None)

        import time

        start_time = time.time()

        try:
            # Load conversation history from session for context continuity
            conversation_history = []
            if session_id:
                session = session_store.get(session_id)
                if session:
                    conversation_history = [
                        {"user": h["query"], "sql": h["sql"]}
                        for h in session.get("context_window", [])
                        if h.get("sql")
                    ]

            # Initial state with conversation context
            initial_state = AgentState(
                question=question,
                schema=self.schema,
                db_type=self.db_config.db_type,
                sql=None,
                error=None,
                attempt=0,
                # Error classification (adaptive retry)
                error_type=None,
                retry_strategy=None,
                retry_prompt_modifier="",
                # Result validation
                validation=None,
                validation_retry_count=0,
                # Output
                result=None,
                explanation=None,
                status="pending",
                messages=[],
                conversation_history=conversation_history,
                total_usage=None,  # Will be populated as LLM calls are made
            )

            # Config for state persistence
            config = {}
            if session_id:
                config = {"configurable": {"thread_id": session_id}}

            # Run agent
            final_state = await self.graph.ainvoke(initial_state, config)

            success = final_state.get("status") == "success"
            attempts = final_state.get("attempt", 0) + 1
            usage = final_state.get("total_usage")

            # Record span attributes
            span.set_attribute("agent.success", success)
            span.set_attribute("agent.attempts", attempts)
            if usage:
                span.set_attribute("agent.total_tokens", usage.get("total_tokens", 0))
                span.set_attribute("agent.cost_usd", usage.get("cost_usd", 0))

            logger.info(
                "Agent completed",
                success=success,
                attempts=attempts,
                has_usage=usage is not None,
                total_cost=usage.get("cost_usd", 0) if usage else 0,
            )

            # Record Prometheus metrics
            duration_seconds = time.time() - start_time
            record_agent_run(
                status="success" if success else "failure",
                duration_seconds=duration_seconds,
                attempts=attempts,
            )

            return {
                "success": success,
                "sql": final_state.get("sql"),
                "result": final_state.get("result"),
                "explanation": final_state.get("explanation"),
                "attempts": attempts,
                "error": final_state.get("error") if not success else None,
                "error_type": final_state.get("error_type"),
                "messages": final_state.get("messages", []),
                "usage": usage,  # Aggregated usage across all LLM calls
                "validation": final_state.get("validation"),  # Result validation info
            }

        except Exception as e:
            span.record_exception(e)
            logger.error("Agent error", error=str(e), question_preview=question[:50])

            # Record Prometheus error metric
            duration_seconds = time.time() - start_time
            record_agent_run(
                status="error", duration_seconds=duration_seconds, attempts=1
            )

            return {
                "success": False,
                "sql": None,
                "result": None,
                "explanation": None,
                "attempts": 1,
                "error": str(e),
                "messages": [f"Agent error: {e}"],
                "usage": None,
            }
        finally:
            span.end()


# ============================================================================
# EVEN SIMPLER - One-liner function
# ============================================================================


async def run_sql_agent(
    question: str,
    llm_config: LLMConfig,
    db_config: DatabaseConfig,
    schema: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    One-liner SQL agent.

    Usage:
        result = await run_sql_agent(
            "Show top 10 customers",
            llm_config,
            db_config,
            schema
        )
    """
    agent = SQLAgent(llm_config, db_config, schema)
    return await agent.query(question, session_id)
