"""
QueryfyAI Benchmarks - Benchmark Runner

Orchestrates a full benchmark run: iterates over cases, invokes the
query generator, optionally executes queries, scores predictions via
the configured metrics, and collects results.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol

from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.core.evaluator import EvaluationMetric
from benchmarks.core.types import (
    BenchmarkCase,
    BenchmarkRunResult,
    CaseResult,
    EvaluationScore,
    PredictionResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols for pluggable components
# ---------------------------------------------------------------------------


class QueryGenerator(Protocol):
    """Protocol for the query generation callable.

    Implementations receive a benchmark case and return the predicted
    query string together with optional metadata.
    """

    async def generate(
        self,
        case: BenchmarkCase,
    ) -> Dict[str, Any]:
        """Generate a query for *case*.

        Returns:
            Dictionary with at least ``"query"`` (str | None).  May also
            include ``"tokens_used"``, ``"cost_usd"``, ``"tools_used"``,
            ``"error"``, and ``"retries"`` keys.
        """
        ...


class QueryExecutor(Protocol):
    """Protocol for the optional query execution callable."""

    async def execute(
        self,
        query: str,
        db_name: str,
        connection_url: str,
    ) -> Any:
        """Execute *query* against the target database.

        Returns:
            Query result in a format suitable for the evaluation metric
            (typically a list of row-dicts).
        """
        ...


# Type alias for the progress callback
ProgressCallback = Callable[[int, int, Optional[CaseResult]], Coroutine[Any, Any, None]]


class BenchmarkRunner:
    """Runs benchmark cases with concurrency control and progress reporting.

    Args:
        config: Top-level benchmark configuration.
        dataset: Loaded benchmark dataset adapter.
        metrics: Evaluation metrics to apply to each case.
        query_generator: Async callable that produces a query for a case.
        query_executor: Optional async callable that executes queries.
            Required when any metric has ``REQUIRES_EXECUTION = True``.
        progress_callback: Optional async callback invoked after each case.
            Signature: ``(completed: int, total: int, result: CaseResult | None) -> None``.
    """

    def __init__(
        self,
        config: BenchmarkConfig,
        dataset: BenchmarkDataset,
        metrics: List[EvaluationMetric],
        query_generator: QueryGenerator,
        query_executor: Optional[QueryExecutor] = None,
        progress_callback: Optional[ProgressCallback] = None,
        transpile_from: Optional[str] = None,
        target_dialect: Optional[str] = None,
    ) -> None:
        self._config = config
        self._dataset = dataset
        self._metrics = metrics
        self._generator = query_generator
        self._executor = query_executor
        self._progress_callback = progress_callback
        self._transpile_from = transpile_from
        self._target_dialect = target_dialect

        # Validate that an executor is present when needed
        needs_execution = any(m.REQUIRES_EXECUTION for m in metrics)
        if needs_execution and query_executor is None:
            raise ValueError(
                "One or more metrics require query execution but no "
                "query_executor was provided. Metrics requiring execution: "
                + ", ".join(m.NAME for m in metrics if m.REQUIRES_EXECUTION)
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self, cases: List[BenchmarkCase]) -> BenchmarkRunResult:
        """Execute the benchmark over *cases* and return aggregated results.

        Concurrency is bounded by ``config.max_concurrent``.

        Args:
            cases: The benchmark cases to evaluate.

        Returns:
            A :class:`BenchmarkRunResult` with all per-case results and
            run metadata.
        """
        result = BenchmarkRunResult(
            benchmark_name=self._config.name,
            db_type=self._dataset.DB_TYPE.value,
            llm_provider=self._config.llm.provider,
            llm_model=self._config.llm.model,
            started_at=datetime.now(timezone.utc),
            config={
                "generator_mode": self._config.generator_mode,
                "max_concurrent": self._config.max_concurrent,
                "metrics": [m.NAME for m in self._metrics],
                "temperature": self._config.llm.temperature,
            },
        )

        total = len(cases)
        if total == 0:
            logger.warning("No cases to run")
            result.completed_at = datetime.now(timezone.utc)
            return result

        logger.info(
            "Starting benchmark run '%s': %d cases, concurrency=%d",
            self._config.name,
            total,
            self._config.max_concurrent,
        )

        semaphore = asyncio.Semaphore(self._config.max_concurrent)
        completed = 0
        lock = asyncio.Lock()

        async def _run_with_semaphore(case: BenchmarkCase) -> CaseResult:
            nonlocal completed
            async with semaphore:
                case_result = await self._run_single_case(case)
            async with lock:
                completed += 1
                if self._progress_callback is not None:
                    await self._progress_callback(completed, total, case_result)
            return case_result

        tasks = [asyncio.create_task(_run_with_semaphore(c)) for c in cases]
        case_results = await asyncio.gather(*tasks, return_exceptions=False)

        result.case_results = list(case_results)
        result.completed_at = datetime.now(timezone.utc)

        logger.info(
            "Benchmark run '%s' complete: %d/%d correct (%.1f%%)",
            self._config.name,
            result.correct_cases,
            result.total_cases,
            result.accuracy * 100,
        )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_single_case(self, case: BenchmarkCase) -> CaseResult:
        """Generate, optionally execute, and score a single case.

        Errors during generation or execution are captured in the
        :class:`PredictionResult` rather than propagated, so that the
        remaining cases in a run are not affected.
        """
        start_ms = time.monotonic() * 1000
        prediction = PredictionResult(case_id=case.case_id)

        # --- Generation ------------------------------------------------
        try:
            gen_result = await self._generator.generate(case)
            prediction.predicted_query = gen_result.get("query")
            prediction.tokens_used = gen_result.get("tokens_used", 0)
            prediction.cost_usd = gen_result.get("cost_usd", 0.0)
            prediction.tools_used = gen_result.get("tools_used", [])
            prediction.retries = gen_result.get("retries", 0)

            if gen_result.get("error"):
                prediction.error = gen_result["error"]
        except Exception as exc:
            logger.error("Generation failed for case %s: %s", case.case_id, exc)
            prediction.error = f"generation_error: {exc}"

        # --- Execution (optional) --------------------------------------
        if self._executor is not None and prediction.predicted_query:
            connection_url = self._resolve_connection_url(case)
            try:
                prediction.predicted_result = await self._executor.execute(
                    prediction.predicted_query,
                    case.db_name,
                    connection_url,
                )
            except Exception as exc:
                logger.error("Execution failed for case %s: %s", case.case_id, exc)
                prediction.error = (prediction.error or "") + f" | execution_error: {exc}"

            # Execute gold query for comparison if needed.
            # When transpile_from is set, transpile the gold query to the
            # target dialect before execution.
            gold_query = case.gold_query
            if self._transpile_from and self._target_dialect:
                gold_query = self._transpile_gold(gold_query) or gold_query

            try:
                prediction.gold_result = await self._executor.execute(
                    gold_query,
                    case.db_name,
                    connection_url,
                )
            except Exception as exc:
                logger.error(
                    "Gold execution failed for case %s: %s", case.case_id, exc
                )

        prediction.latency_ms = time.monotonic() * 1000 - start_ms

        # --- Scoring ---------------------------------------------------
        scores = []
        for metric in self._metrics:
            try:
                scores.append(metric.score(case, prediction))
            except Exception as exc:
                logger.error(
                    "Metric %s failed for case %s: %s",
                    metric.NAME,
                    case.case_id,
                    exc,
                )
                scores.append(
                    EvaluationScore(
                        metric_name=metric.NAME,
                        score=0.0,
                        details={"error": str(exc)},
                    )
                )

        return CaseResult(case=case, prediction=prediction, scores=scores)

    def _transpile_gold(self, sql: str) -> Optional[str]:
        """Transpile a gold query from the source dialect to the target.

        Returns ``None`` if transpilation fails.
        """
        try:
            import sqlglot

            results = sqlglot.transpile(
                sql, read=self._transpile_from, write=self._target_dialect
            )
            return results[0] if results else None
        except Exception as exc:
            logger.debug("Gold query transpile failed: %s", exc)
            return None

    def _resolve_connection_url(self, case: BenchmarkCase) -> str:
        """Determine the connection URL for a case.

        Priority:
        1. Suite-level ``connection_url`` (first suite whose tags match).
        2. Fall back to empty string (executor must handle default).
        """
        for suite in self._config.suites:
            if suite.connection_url:
                return suite.connection_url
        return ""
