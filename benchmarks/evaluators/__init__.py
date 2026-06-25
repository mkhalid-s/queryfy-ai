"""
QueryfyAI Benchmarks - Evaluator Registry

Maps metric names to concrete EvaluationMetric implementations.
"""

from __future__ import annotations

from typing import Dict, Type

from benchmarks.core.evaluator import EvaluationMetric
from benchmarks.evaluators.exact_match import ExactMatchMetric
from benchmarks.evaluators.execution_accuracy import ExecutionAccuracyMetric
from benchmarks.evaluators.dialect_accuracy import DialectAccuracyMetric

METRICS: Dict[str, Type[EvaluationMetric]] = {
    "exact_match": ExactMatchMetric,
    "execution_accuracy": ExecutionAccuracyMetric,
    "dialect_accuracy": DialectAccuracyMetric,
}


def get_metric(name: str, **kwargs) -> EvaluationMetric:
    """Instantiate a metric by name.

    Keyword arguments are passed to the metric constructor (e.g.,
    ``source_dialect`` and ``target_dialect`` for ``DialectAccuracyMetric``).
    """
    cls = METRICS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown metric: {name!r}. Available: {sorted(METRICS)}"
        )
    return cls(**kwargs)


__all__ = ["METRICS", "get_metric"]
