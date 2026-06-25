"""
Execution Accuracy (EX) Metric

The primary NL-to-SQL benchmark metric.  Both the gold and predicted
queries are executed against the target database; the metric returns 1.0
when the unordered result multisets are equivalent.

Result set comparison:
- Rows are compared as multisets (Counter) of tuples (order-independent
  but duplicate-sensitive).
- Floats are rounded to 6 decimal places before comparison.
- Both-empty counts as a match.
- Either side being ``None`` (execution failure) counts as a mismatch.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, List, Optional, Tuple

from benchmarks.core.evaluator import EvaluationMetric
from benchmarks.core.types import BenchmarkCase, EvaluationScore, PredictionResult


def _make_hashable(value: Any) -> Any:
    """Recursively convert unhashable types (dict, list) to hashable equivalents.

    NoSQL results (MongoDB, DynamoDB) may contain nested dicts and lists
    that cannot be added to a set directly.
    """
    if isinstance(value, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_make_hashable(v) for v in value)
    if isinstance(value, float):
        return round(value, 6)
    return value


def normalise_result_set(result: Any) -> Optional[Counter]:
    """Convert an execution result to a multiset (Counter) of tuples.

    Uses ``Counter`` instead of ``set`` so that duplicate rows are
    preserved — a query returning ``[(1,), (1,)]`` is different from
    one returning ``[(1,)]``.

    Handles the standard executor format::

        {"success": True, "rows": [...], "columns": [...]}

    as well as a plain list of dicts or list of tuples.

    Values within rows are made hashable recursively so that nested
    dicts/lists (common in NoSQL results) do not cause ``TypeError``.
    """
    if result is None:
        return None

    rows: List = []

    if isinstance(result, dict):
        if not result.get("success", True):
            return None
        rows = result.get("rows", [])
    elif isinstance(result, list):
        rows = result
    else:
        return None

    normalised: list[Tuple] = []
    for row in rows:
        if isinstance(row, dict):
            values = tuple(row.values())
        elif isinstance(row, (list, tuple)):
            values = tuple(row)
        else:
            values = (row,)

        values = tuple(_make_hashable(v) for v in values)
        normalised.append(values)

    return Counter(normalised)


class ExecutionAccuracyMetric(EvaluationMetric):
    NAME = "execution_accuracy"
    DESCRIPTION = (
        "Result-set equivalence between predicted and gold query execution."
    )
    REQUIRES_EXECUTION = True

    def score(
        self,
        case: BenchmarkCase,
        prediction: PredictionResult,
    ) -> EvaluationScore:
        if prediction.error and prediction.predicted_result is None:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={"reason": "execution_failed", "error": prediction.error},
            )

        gold_multiset = normalise_result_set(prediction.gold_result)
        pred_multiset = normalise_result_set(prediction.predicted_result)

        if gold_multiset is None:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={"reason": "gold_execution_failed"},
            )

        if pred_multiset is None:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={"reason": "predicted_execution_failed"},
            )

        match = gold_multiset == pred_multiset
        return EvaluationScore(
            metric_name=self.NAME,
            score=1.0 if match else 0.0,
            details={
                "match": match,
                "gold_row_count": sum(gold_multiset.values()),
                "predicted_row_count": sum(pred_multiset.values()),
            },
        )
