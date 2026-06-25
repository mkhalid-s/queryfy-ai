"""
Dialect Accuracy Metric

Evaluates whether a predicted query produces correct results when executed
against a different dialect than the original benchmark target.

This enables multi-dialect benchmarking:
  - BIRD gold queries are written for SQLite
  - We transpile them to PostgreSQL / MySQL using sqlglot
  - The LLM generates queries directly in the target dialect
  - We compare execution results between transpiled-gold and predicted

The metric reports:
  - ``dialect_match``: result-set equivalence (0 or 1)
  - ``transpile_success``: whether sqlglot could transpile the gold query
  - ``gold_dialect``: source dialect
  - ``target_dialect``: target dialect
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from benchmarks.core.evaluator import EvaluationMetric
from benchmarks.core.types import BenchmarkCase, EvaluationScore, PredictionResult
from benchmarks.evaluators.execution_accuracy import normalise_result_set

logger = logging.getLogger(__name__)


def transpile_query(sql: str, source: str, target: str) -> Optional[str]:
    """Transpile SQL from *source* dialect to *target* using sqlglot.

    Returns ``None`` if transpilation fails.
    """
    try:
        import sqlglot

        results = sqlglot.transpile(sql, read=source, write=target)
        return results[0] if results else None
    except Exception as exc:
        logger.debug("sqlglot transpile failed (%s→%s): %s", source, target, exc)
        return None


class DialectAccuracyMetric(EvaluationMetric):
    """Cross-dialect execution accuracy.

    Requires that the runner has already:
    1. Transpiled the gold query to the target dialect and executed it.
    2. Executed the predicted query against the target database.

    The ``PredictionResult.gold_result`` and ``predicted_result`` fields
    should be populated by the executor running against the *target*
    dialect database (PostgreSQL/MySQL), not the source (SQLite).

    Configuration:
        Set ``transpile_from`` on the suite config to enable automatic
        gold-query transpilation in the runner.
    """

    NAME = "dialect_accuracy"
    DESCRIPTION = "Cross-dialect execution accuracy (result-set equivalence)"
    REQUIRES_EXECUTION = True

    def __init__(
        self,
        source_dialect: str = "sqlite",
        target_dialect: str = "postgres",
    ) -> None:
        self.source_dialect = source_dialect
        self.target_dialect = target_dialect

    def score(
        self,
        case: BenchmarkCase,
        prediction: PredictionResult,
    ) -> EvaluationScore:
        details: Dict[str, Any] = {
            "source_dialect": self.source_dialect,
            "target_dialect": self.target_dialect,
        }

        # Check if gold query can be transpiled
        transpiled_gold = transpile_query(
            case.gold_query, self.source_dialect, self.target_dialect
        )
        details["transpile_success"] = transpiled_gold is not None
        details["transpiled_gold"] = transpiled_gold

        if transpiled_gold is None:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={**details, "reason": "gold_transpile_failed"},
            )

        # Execution error
        if prediction.error and prediction.predicted_result is None:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={**details, "reason": "execution_failed", "error": prediction.error},
            )

        gold_multiset = normalise_result_set(prediction.gold_result)
        pred_multiset = normalise_result_set(prediction.predicted_result)

        if gold_multiset is None:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={**details, "reason": "gold_execution_failed"},
            )

        if pred_multiset is None:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={**details, "reason": "predicted_execution_failed"},
            )

        match = gold_multiset == pred_multiset
        return EvaluationScore(
            metric_name=self.NAME,
            score=1.0 if match else 0.0,
            details={
                **details,
                "match": match,
                "gold_row_count": sum(gold_multiset.values()),
                "predicted_row_count": sum(pred_multiset.values()),
            },
        )
