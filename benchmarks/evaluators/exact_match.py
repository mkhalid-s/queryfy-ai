"""
Exact Match Metric

Compares the predicted query string against the gold query string.
For SQL queries, normalises whitespace and casing (SQL keywords are
case-insensitive). For NoSQL queries (MongoDB, Cassandra, DynamoDB),
only normalises whitespace to preserve case-sensitive identifiers.
"""

from __future__ import annotations

import re

from benchmarks.core.evaluator import EvaluationMetric
from benchmarks.core.types import BenchmarkCase, DatabaseCategory, EvaluationScore, PredictionResult

# Database categories where identifiers are case-sensitive
_CASE_SENSITIVE_CATEGORIES = {
    DatabaseCategory.NOSQL_DOCUMENT,
    DatabaseCategory.NOSQL_WIDE_COLUMN,
    DatabaseCategory.NOSQL_KEY_VALUE,
}


def _normalise_query(query: str, case_sensitive: bool = False) -> str:
    """Normalise a query string for comparison.

    Args:
        query: Raw query string.
        case_sensitive: When ``True``, preserve casing (used for NoSQL
            queries where collection names and field names are
            case-sensitive).  When ``False``, lowercase everything
            (safe for SQL where keywords and identifiers are
            case-insensitive).
    """
    normalised = re.sub(r"\s+", " ", query.strip())
    if not case_sensitive:
        normalised = normalised.lower()
    return normalised


class ExactMatchMetric(EvaluationMetric):
    NAME = "exact_match"
    DESCRIPTION = "Normalised string equality between predicted and gold queries."
    REQUIRES_EXECUTION = False

    def score(
        self,
        case: BenchmarkCase,
        prediction: PredictionResult,
    ) -> EvaluationScore:
        if not prediction.predicted_query:
            return EvaluationScore(
                metric_name=self.NAME,
                score=0.0,
                details={"reason": "no_prediction"},
            )

        case_sensitive = case.db_type in _CASE_SENSITIVE_CATEGORIES
        pred_norm = _normalise_query(prediction.predicted_query, case_sensitive)
        gold_norm = _normalise_query(case.gold_query, case_sensitive)
        match = pred_norm == gold_norm

        return EvaluationScore(
            metric_name=self.NAME,
            score=1.0 if match else 0.0,
            details={"match": match},
        )
