"""
QueryfyAI - SQL Generation Helper Service

Consolidates common SQL generation patterns used across multiple endpoints:
- Input sanitization and validation
- LLM-based SQL generation with self-correction
- SQL cleaning and validation
- History and integrity registration

This eliminates ~150 lines of duplicated code between queries.py and consolidated.py.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging_config import get_logger
from app.models.schemas import DatabaseConfig, LLMConfig
from app.services.database_service import DatabaseService
from app.services.llm_service import LLMService, LLMUsageData
from app.services.query_history_service import query_history_service
from app.services.security import (
    AuditLogger,
    ErrorSanitizer,
    SecurityService,
    sql_integrity,
)
from app.services.session_store import session_store
from app.services.vector_db import vector_db

logger = get_logger(__name__)

# Flag to enable/disable data dictionary integration
# Set to False if database tables don't exist yet
DATA_DICTIONARY_ENABLED = True

# Maximum retry attempts for self-correction
MAX_RETRY_ATTEMPTS = 2  # Total 3 attempts (1 initial + 2 retries)


@dataclass
class SQLGenerationResult:
    """Result of SQL generation process."""

    success: bool
    sql: Optional[str] = None
    query_id: Optional[str] = None
    sql_hash: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    warnings: Optional[List[str]] = None
    usage: Optional[Dict[str, Any]] = None  # LLM token usage and cost data
    attempts: int = 1  # Number of generation attempts (for self-correction)


@dataclass
class GenerationContext:
    """Context for SQL generation containing all required configuration."""

    session_id: str
    session: dict
    llm_config: LLMConfig
    db_config: DatabaseConfig
    natural_language: str
    sanitized_query: str
    relevant_schema: str
    conversation_history: List[Dict[str, str]]
    # Data dictionary context (optional)
    business_terms_context: Optional[str] = None
    column_context: Optional[str] = None
    connection_hash: Optional[str] = None
    # Conversation support
    last_query_context: Optional[Dict[str, Any]] = None
    is_follow_up: bool = False


class SQLGenerationService:
    """
    Service for generating SQL from natural language.

    Provides a unified interface for SQL generation with:
    - Input sanitization
    - Schema retrieval
    - LLM-based generation
    - Validation and cleaning
    - History and integrity registration
    - Data dictionary context (business terms, column descriptions)
    """

    # Patterns that indicate prompt injection in dictionary content.
    # Reuses the same patterns as PromptInjectionValidator for consistency.
    _INJECTION_PATTERNS = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            # Instruction overrides
            r"ignore\s+(all\s+)?previous\s+instructions?",
            r"ignore\s+(all\s+)?above\s+instructions?",
            r"forget\s+(all\s+)?previous\s+instructions?",
            r"disregard\s+(all\s+)?previous\s+instructions?",
            r"override\s+(all\s+)?previous\s+instructions?",
            # Role manipulation
            r"you\s+are\s+now\s+a?",
            r"act\s+as\s+(?:if|a)",
            r"pretend\s+(?:to\s+be|you\s+are)",
            r"roleplay\s+as",
            r"simulate\s+(?:being\s+)?a?",
            # System prompt access
            r"what\s+(?:is|are)\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
            r"show\s+(?:me\s+)?your\s+(?:system\s+)?(?:instructions?|prompt)",
            r"reveal\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
            r"print\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
            # Delimiter injection
            r"```\s*(?:system|user|assistant)",
            r"\[\[(?:system|user|assistant)\]\]",
            r"<\s*(?:system|user|assistant)\s*>",
            # Jailbreak patterns
            r"jailbreak",
            r"dan\s+mode",
            r"developer\s+mode",
            r"bypass\s+(?:filters?|safety|restrictions?)",
        ]
    ]

    @classmethod
    def _sanitize_dictionary_value(cls, text: str) -> Optional[str]:
        """
        Check a dictionary content value for prompt injection patterns.

        Returns the original text if clean, or None if suspicious content is detected.
        """
        if not text:
            return text
        for pattern in cls._INJECTION_PATTERNS:
            if pattern.search(text):
                return None
        return text

    @classmethod
    async def _get_data_dictionary_context(
        cls, connection_hash: str, query: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Fetch relevant business terms and column descriptions from data dictionary.

        Sanitizes dictionary content before including it in LLM prompts to
        prevent prompt injection via stored dictionary entries.

        Returns:
            Tuple of (business_terms_context, column_context)
        """
        if not DATA_DICTIONARY_ENABLED:
            return None, None

        business_terms_context = None
        column_context = None

        try:
            from app.services.data_dictionary import data_dictionary

            # Fetch relevant business terms
            terms = await data_dictionary.get_relevant_terms(
                query=query, connection_hash=connection_hash, limit=5
            )

            if terms:
                terms_text = "## Business Terms\n"
                included_count = 0
                for term in terms:
                    # Sanitize definition and sql_expression before injection
                    safe_definition = cls._sanitize_dictionary_value(
                        term.get("definition", "")
                    )
                    safe_sql = cls._sanitize_dictionary_value(
                        term.get("sql_expression", "")
                    )

                    if safe_definition is None or safe_sql is None:
                        logger.warning(
                            "Skipping business term with suspicious content",
                            term=term.get("term", "unknown"),
                            term_id=term.get("id", "unknown"),
                        )
                        continue

                    terms_text += f"- **{term['term']}**: {safe_definition}\n"
                    terms_text += f"  SQL: `{safe_sql}`\n"
                    included_count += 1

                if included_count > 0:
                    business_terms_context = terms_text

            # Fetch column descriptions (sanitized)
            raw_column_context = await data_dictionary.get_column_context(
                query=query, connection_hash=connection_hash
            )
            if raw_column_context:
                # Sanitize the entire column context block
                safe_col_context = cls._sanitize_dictionary_value(raw_column_context)
                if safe_col_context is None:
                    logger.warning(
                        "Column context contained suspicious content, skipping"
                    )
                else:
                    column_context = safe_col_context

        except Exception as e:
            # Data dictionary tables may not exist yet
            logger.debug("Data dictionary context fetch skipped", error=str(e))

        return business_terms_context, column_context

    @classmethod
    async def _store_successful_pattern(
        cls,
        connection_hash: str,
        natural_query: str,
        sql: str,
        execution_time_ms: Optional[int] = None,
    ):
        """
        Store successful query pattern in data dictionary for learning.
        """
        if not DATA_DICTIONARY_ENABLED:
            return

        try:
            from app.services.data_dictionary import data_dictionary

            await data_dictionary.add_query_pattern(
                connection_hash=connection_hash,
                natural_query=natural_query,
                sql=sql,
                execution_time_ms=execution_time_ms,
                is_curated=False,  # Auto-captured
            )
        except Exception as e:
            # Data dictionary tables may not exist yet
            logger.debug("Query pattern storage skipped", error=str(e))

    @classmethod
    async def prepare_context(
        cls,
        session_id: str,
        session: dict,
        natural_language: str,
        continue_conversation: bool = True,
    ) -> Tuple[Optional[GenerationContext], Optional[SQLGenerationResult]]:
        """
        Prepare generation context with sanitized input and configs.

        Args:
            session_id: Session identifier
            session: Session data dict
            natural_language: User's natural language query
            continue_conversation: Whether to include conversation context

        Returns:
            Tuple of (context, error_result):
            - If successful: (GenerationContext, None)
            - If failed: (None, SQLGenerationResult with error)
        """
        # Sanitize input
        sanitized, warnings = SecurityService.sanitize_input(natural_language)

        if warnings:
            AuditLogger.log_security_event(
                session_id,
                "INPUT_SANITIZED",
                f"Warnings: {warnings}, Original: {natural_language[:100]}...",
            )
            return None, SQLGenerationResult(
                success=False,
                error="Security warning",
                warnings=warnings,
                message="Query contains potentially harmful content",
            )

        # Extract configs
        llm_config = LLMConfig(**session["llm_config"])
        db_config = DatabaseConfig(**session["db_config"])

        # Get connection hash for data dictionary
        connection_hash = vector_db._hash_connection(db_config.connection_url)

        # Get relevant schema
        relevant_schema = vector_db.get_relevant_schema(
            db_config.connection_url, sanitized
        )

        # Get conversation history
        conversation_history = [
            {"user": h["query"], "sql": h["sql"]}
            for h in session.get("context_window", [])
            if h.get("sql")
        ]

        # Fetch data dictionary context (business terms, column descriptions)
        business_terms_context, column_context = await cls._get_data_dictionary_context(
            connection_hash=connection_hash, query=sanitized
        )

        # Enhance schema with data dictionary context
        enhanced_schema = relevant_schema
        if business_terms_context:
            enhanced_schema = f"{business_terms_context}\n\n{enhanced_schema}"
        if column_context:
            enhanced_schema = f"{enhanced_schema}\n\n{column_context}"

        # Get conversation context if continuing conversation
        last_query_context = None
        is_follow_up = False
        if continue_conversation:
            # Import inside function to avoid circular dependency
            from app.api.chat import _detect_follow_up

            last_query_context = session.get("last_query_context")
            is_follow_up = _detect_follow_up(natural_language, last_query_context)

        context = GenerationContext(
            session_id=session_id,
            session=session,
            llm_config=llm_config,
            db_config=db_config,
            natural_language=natural_language,
            sanitized_query=sanitized,
            relevant_schema=enhanced_schema,
            conversation_history=conversation_history,
            business_terms_context=business_terms_context,
            column_context=column_context,
            connection_hash=connection_hash,
            last_query_context=last_query_context,
            is_follow_up=is_follow_up,
        )

        return context, None

    @classmethod
    async def generate_sql(
        cls,
        ctx: GenerationContext,
        additional_history_data: Optional[Dict[str, Any]] = None,
        validate_sql: bool = True,
    ) -> SQLGenerationResult:
        """
        Generate SQL from natural language using LLM with self-correction.

        Implements a self-healing pattern:
        1. Generate SQL from natural language
        2. Validate by attempting to execute (optional)
        3. If validation fails, retry with error context
        4. Up to MAX_RETRY_ATTEMPTS retries

        Args:
            ctx: Generation context with all required configuration
            additional_history_data: Extra data to store in history entry
            validate_sql: If True, validate SQL by executing and retry on error

        Returns:
            SQLGenerationResult with generated SQL or error details
        """
        # Fetch similar queries for few-shot learning (once, reuse across attempts)
        few_shot_examples = []
        try:
            few_shot_examples = vector_db.find_similar_queries(
                ctx.db_config.connection_url, ctx.sanitized_query, n=3
            )
            if few_shot_examples:
                logger.debug(
                    "Few-shot examples found",
                    count=len(few_shot_examples),
                    session_id=ctx.session_id[:8],
                )
        except Exception as e:
            logger.debug("Few-shot retrieval skipped", error=str(e))

        # Track state across retries
        attempt = 0
        last_error: Optional[str] = None
        total_usage: Dict[str, Any] = {}
        generated_sql: Optional[str] = None

        while attempt <= MAX_RETRY_ATTEMPTS:
            attempt += 1

            try:
                # Build prompt - include error context for retries
                prompt = ctx.sanitized_query
                if last_error and attempt > 1:
                    prompt = f"""Previous SQL query failed with error: {last_error}

Original question: {ctx.sanitized_query}

Please generate a corrected SQL query that fixes this error."""
                    logger.info(
                        "Retrying SQL generation with error context",
                        attempt=attempt,
                        error_preview=last_error[:100] if last_error else None,
                    )

                # Build conversation context section for follow-up queries
                enhanced_schema = ctx.relevant_schema
                if ctx.is_follow_up and ctx.last_query_context:
                    conversation_context_section = f"""
## Previous Query Context

You are answering a follow-up question. The user's previous query was:
- Question: {ctx.last_query_context.get('question', 'N/A')}
- SQL: {ctx.last_query_context.get('sql', 'N/A')}

Build upon this context when generating the new SQL query.
"""
                    enhanced_schema = f"{enhanced_schema}\n\n{conversation_context_section}"
                    logger.debug(
                        "Added conversation context for follow-up query",
                        session_id=ctx.session_id[:8],
                    )

                # Generate SQL via LLM (use enhanced_schema with conversation context)
                raw_response, usage = await LLMService.generate_sql(
                    ctx.llm_config,
                    prompt,
                    enhanced_schema,
                    ctx.conversation_history,
                    ctx.db_config.db_type,
                    few_shot_examples=few_shot_examples,
                )

                # Aggregate usage across attempts
                total_usage = cls._aggregate_usage(total_usage, usage)

                # Check for error responses from LLM
                if (
                    raw_response.strip().startswith("-- ERROR:")
                    or "cannot generate" in raw_response.lower()
                ):
                    return SQLGenerationResult(
                        success=False,
                        error="Unable to generate SQL",
                        message=raw_response.replace("-- ERROR:", "").strip(),
                        usage=total_usage,
                        attempts=attempt,
                    )

                # Clean response
                generated_sql = LLMService.clean_sql_response(raw_response)

                # Check if cleaning resulted in empty SQL
                if not generated_sql or len(generated_sql) < 10:
                    last_error = "Generated SQL was empty or too short"
                    if attempt <= MAX_RETRY_ATTEMPTS:
                        continue
                    return SQLGenerationResult(
                        success=False,
                        error="Unable to generate SQL",
                        message="The LLM did not return a valid SQL query. Please try rephrasing your question.",
                        usage=total_usage,
                        attempts=attempt,
                    )

                # Validate query safety
                is_safe, validation_message = SecurityService.validate_generated_sql(
                    generated_sql, ctx.db_config.db_type
                )
                if not is_safe:
                    AuditLogger.log_security_event(
                        ctx.session_id,
                        "UNSAFE_SQL_GENERATED",
                        f"Validation: {validation_message}, SQL: {generated_sql[:100]}...",
                    )
                    return SQLGenerationResult(
                        success=False,
                        error="Generated SQL failed validation",
                        message=f"{validation_message}. Raw response started with: {raw_response[:100]}...",
                        usage=total_usage,
                        attempts=attempt,
                    )

                # Optionally validate SQL by executing (self-correction)
                if validate_sql:
                    validation_error = await cls._validate_sql_execution(
                        ctx, generated_sql
                    )
                    if validation_error:
                        last_error = validation_error
                        if attempt <= MAX_RETRY_ATTEMPTS:
                            logger.warning(
                                "SQL validation failed, retrying",
                                attempt=attempt,
                                error=validation_error[:200],
                            )
                            continue
                        # Max retries reached, return with error
                        return SQLGenerationResult(
                            success=False,
                            sql=generated_sql,
                            error="SQL execution failed after retries",
                            message=f"The generated SQL could not be validated: {validation_error}",
                            usage=total_usage,
                            attempts=attempt,
                        )

                # Success - register and return
                result = await cls._register_successful_generation(
                    ctx, generated_sql, additional_history_data, total_usage
                )
                result.attempts = attempt
                return result

            except Exception as e:
                logger.error(
                    "SQL generation attempt failed",
                    error=ErrorSanitizer.safe_log_error(e),
                    attempt=attempt,
                )
                last_error = str(e)
                if attempt > MAX_RETRY_ATTEMPTS:
                    return SQLGenerationResult(
                        success=False,
                        error="Generation failed",
                        message=ErrorSanitizer.sanitize_error(e),
                        usage=total_usage,
                        attempts=attempt,
                    )

        # Should not reach here, but safety fallback
        return SQLGenerationResult(
            success=False,
            error="Max retries exceeded",
            message="Could not generate valid SQL after multiple attempts",
            usage=total_usage,
            attempts=attempt,
        )

    @classmethod
    async def _validate_sql_execution(
        cls, ctx: GenerationContext, sql: str
    ) -> Optional[str]:
        """
        Validate SQL by attempting execution.

        For SQL databases: Uses EXPLAIN or LIMIT 0 to validate without returning data.
        For MongoDB: Skips execution validation (relies on syntax checking).

        Returns:
            Error message if validation failed, None if successful
        """
        db_type = ctx.db_config.db_type.lower()

        # Skip execution validation for NoSQL databases (syntax-only validation)
        # These databases use different query languages (MQL, PartiQL, CQL) that
        # don't support SQL-style LIMIT 0 validation
        if db_type in ("mongodb", "dynamodb", "cassandra"):
            return None

        try:
            # For SQL databases, try to execute with LIMIT 0 to validate
            # This validates syntax and table/column existence without returning data
            test_sql = sql.rstrip(";").strip()

            # Wrap with LIMIT 0 for validation (if not already limited)
            if "limit" not in test_sql.lower():
                test_sql = f"{test_sql} LIMIT 0"

            await DatabaseService.execute_query(
                config=ctx.db_config, sql=test_sql, limit=0
            )
            return None  # Validation successful

        except Exception as e:
            error_msg = str(e)
            # Extract meaningful error message
            if "syntax error" in error_msg.lower():
                return f"Syntax error: {error_msg}"
            elif "does not exist" in error_msg.lower():
                return f"Invalid table or column: {error_msg}"
            elif "permission denied" in error_msg.lower():
                return None  # Permission issues are not SQL generation errors
            else:
                return f"Execution error: {error_msg[:300]}"

    @classmethod
    def _aggregate_usage(
        cls, existing: Dict[str, Any], new_usage: Optional[LLMUsageData]
    ) -> Dict[str, Any]:
        """Aggregate LLM usage data across multiple attempts."""
        if not new_usage:
            return existing

        new_dict = new_usage.to_dict() if hasattr(new_usage, "to_dict") else {}

        if not existing:
            return new_dict

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

    @classmethod
    async def _register_successful_generation(
        cls,
        ctx: GenerationContext,
        generated_sql: str,
        additional_history_data: Optional[Dict[str, Any]] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> SQLGenerationResult:
        """
        Register a successful SQL generation in history and integrity service.

        Args:
            ctx: Generation context
            generated_sql: The generated SQL query
            additional_history_data: Extra data to store in history
            usage: LLM usage data (tokens, cost)

        Returns:
            SQLGenerationResult with query_id and sql_hash
        """
        # Build history entry with extended fields for re-execution support
        history_entry = {
            "query": ctx.natural_language,
            "sanitized_query": ctx.sanitized_query,
            "sql": generated_sql,
            # New fields for history improvements
            "db_type": ctx.db_config.db_type if ctx.db_config else None,
            "connection_id": ctx.connection_hash,  # Use connection_hash as connection_id
        }

        # Merge additional data if provided
        if additional_history_data:
            history_entry.update(additional_history_data)

        # Store in history
        entry_id = session_store.add_history(ctx.session_id, history_entry)

        # Register SQL with integrity service
        sql_hash = sql_integrity.register_sql(ctx.session_id, entry_id, generated_sql)

        # Update history entry with sql_hash for re-execution support
        session_store.update_history_entry(
            ctx.session_id, entry_id, {"sql_hash": sql_hash}
        )

        # Persist to PostgreSQL for long-term storage (cross-session re-execution)
        if ctx.connection_hash and ctx.db_config:
            # Calculate conversation turn from session context
            conversation_turn = len(ctx.session.get("context_window", [])) + 1

            await query_history_service.save_query(
                query_id=entry_id,
                connection_hash=ctx.connection_hash,
                db_type=ctx.db_config.db_type,
                natural_query=ctx.natural_language,
                sql=generated_sql,
                sanitized_query=ctx.sanitized_query,
                sql_hash=sql_hash,
                # Conversation fields for full persistence
                mode="standard",
                is_follow_up=ctx.is_follow_up,
                conversation_turn=conversation_turn,
                session_id=ctx.session_id,
            )

        # Store for learning (vector DB)
        vector_db.store_successful_query(
            ctx.db_config.connection_url, ctx.sanitized_query, generated_sql
        )

        # Store for learning (data dictionary patterns)
        if ctx.connection_hash:
            await cls._store_successful_pattern(
                connection_hash=ctx.connection_hash,
                natural_query=ctx.sanitized_query,
                sql=generated_sql,
            )

        logger.info(
            "SQL generated",
            session_id=ctx.session_id[:8],
            query_id=entry_id[:8],
            has_usage=usage is not None,
        )

        return SQLGenerationResult(
            success=True,
            sql=generated_sql,
            query_id=entry_id,
            sql_hash=sql_hash,
            usage=usage,
        )

    @classmethod
    async def register_agent_result(
        cls,
        ctx: GenerationContext,
        generated_sql: str,
        agent_attempts: int = 1,
        agent_explanation: Optional[str] = None,
    ) -> SQLGenerationResult:
        """
        Register SQL generated by the SQL agent.

        Args:
            ctx: Generation context
            generated_sql: SQL generated by agent
            agent_attempts: Number of agent retry attempts
            agent_explanation: Optional explanation from agent

        Returns:
            SQLGenerationResult with query_id and sql_hash
        """
        additional_data = {
            "agent_attempts": agent_attempts,
            "explanation": agent_explanation,  # Use 'explanation' for consistency with HistoryEntry
        }

        return await cls._register_successful_generation(
            ctx, generated_sql, additional_data
        )
