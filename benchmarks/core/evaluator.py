"""
QueryfyAI Benchmarks - Evaluation Metric Abstract Base Class

Defines the contract for evaluation metrics.  Concrete implementations
(e.g., exact-match, execution-accuracy, cosine similarity) inherit from
``EvaluationMetric`` and implement :meth:`score`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from benchmarks.core.types import (
    BenchmarkCase,
    EvaluationScore,
    PredictionResult,
)

logger = logging.getLogger(__name__)


class EvaluationMetric(ABC):
    """Abstract interface for a single evaluation metric.

    Class Attributes:
        NAME: Machine-readable identifier (e.g., ``"exact_match"``).
        DESCRIPTION: Human-readable explanation for reports.
        REQUIRES_EXECUTION: ``True`` when the metric needs query execution
            results (both predicted and gold) rather than only comparing
            query strings.
    """

    NAME: str = ""
    DESCRIPTION: str = ""
    REQUIRES_EXECUTION: bool = False

    # ------------------------------------------------------------------
    # Abstract method
    # ------------------------------------------------------------------

    @abstractmethod
    def score(
        self,
        case: BenchmarkCase,
        prediction: PredictionResult,
    ) -> EvaluationScore:
        """Score a single prediction against its benchmark case.

        Args:
            case: The benchmark case with the gold query/result.
            prediction: The system-generated prediction to evaluate.

        Returns:
            An :class:`EvaluationScore` with ``score`` in [0, 1].
        """

    # ------------------------------------------------------------------
    # Batch & aggregation helpers
    # ------------------------------------------------------------------

    def score_batch(
        self,
        cases: List[BenchmarkCase],
        predictions: List[PredictionResult],
    ) -> List[EvaluationScore]:
        """Score a batch of predictions.

        Cases and predictions are matched by index (i.e., ``cases[i]`` is
        evaluated against ``predictions[i]``).

        Args:
            cases: Benchmark cases.
            predictions: Corresponding predictions (same length).

        Returns:
            List of evaluation scores, one per case.

        Raises:
            ValueError: When the two lists differ in length.
        """
        if len(cases) != len(predictions):
            raise ValueError(
                f"Length mismatch: {len(cases)} cases vs "
                f"{len(predictions)} predictions"
            )

        scores: List[EvaluationScore] = []
        for case, pred in zip(cases, predictions):
            try:
                scores.append(self.score(case, pred))
            except Exception:
                logger.exception(
                    "Scoring failed for case %s with metric %s",
                    case.case_id,
                    self.NAME,
                )
                scores.append(
                    EvaluationScore(
                        metric_name=self.NAME,
                        score=0.0,
                        details={"error": "scoring_exception"},
                    )
                )
        return scores

    def aggregate(self, scores: List[EvaluationScore]) -> Dict[str, Any]:
        """Compute summary statistics over a list of scores.

        Args:
            scores: Evaluation scores produced by this metric.

        Returns:
            Dictionary with ``mean``, ``count``, ``correct`` (score == 1.0),
            and ``accuracy_pct`` keys.
        """
        if not scores:
            return {
                "metric": self.NAME,
                "mean": 0.0,
                "count": 0,
                "correct": 0,
                "accuracy_pct": 0.0,
            }

        total = len(scores)
        correct = sum(1 for s in scores if s.score >= 1.0)
        mean = sum(s.score for s in scores) / total

        return {
            "metric": self.NAME,
            "mean": round(mean, 4),
            "count": total,
            "correct": correct,
            "accuracy_pct": round((correct / total) * 100, 2),
        }
