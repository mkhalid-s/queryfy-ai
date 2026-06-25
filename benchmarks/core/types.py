"""
QueryfyAI Benchmarks - Shared Types

Dataclasses and enums used across the benchmarking framework.
All benchmark data flows through these types: cases are loaded,
predictions are generated, scores are computed, and results are aggregated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Difficulty(str, Enum):
    """Difficulty level for a benchmark case.

    Aligns with standard NL2SQL benchmark conventions (e.g., Spider, BIRD).
    """

    SIMPLE = "simple"
    MODERATE = "moderate"
    CHALLENGING = "challenging"
    EXTRA_HARD = "extra_hard"


class DatabaseCategory(str, Enum):
    """Broad database category a benchmark targets.

    Allows the framework to route cases to the correct executor
    and select appropriate evaluation metrics.
    """

    SQL = "sql"
    NOSQL_DOCUMENT = "nosql_document"
    NOSQL_WIDE_COLUMN = "nosql_wide_column"
    NOSQL_KEY_VALUE = "nosql_key_value"


# ---------------------------------------------------------------------------
# Core data-flow types
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkCase:
    """A single benchmark question with its gold-standard answer.

    Attributes:
        case_id: Unique identifier for this case.
        natural_language: The natural-language question posed to the system.
        gold_query: The reference (gold) query expected as output.
        db_name: Name of the database the query targets.
        db_type: Category of the target database.
        difficulty: Human-assigned difficulty rating.
        evidence: Optional hints or context provided alongside the question
                  (e.g., BIRD benchmark evidence strings).
        schema_context: Optional pre-extracted schema text for the target DB.
        collection_name: For document-store benchmarks, the target collection.
        operators: List of query operators / clauses exercised by this case
                   (e.g., ["JOIN", "GROUP BY"]).
        tags: Arbitrary tags for filtering and reporting.
    """

    case_id: str
    natural_language: str
    gold_query: str
    db_name: str
    db_type: DatabaseCategory = DatabaseCategory.SQL
    difficulty: Difficulty = Difficulty.SIMPLE
    evidence: Optional[str] = None
    schema_context: Optional[str] = None
    collection_name: Optional[str] = None
    operators: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class PredictionResult:
    """Output produced by the system under test for a single case.

    Captures the generated query, execution artefacts, and cost metrics.
    """

    case_id: str
    predicted_query: Optional[str] = None
    predicted_result: Optional[Any] = None
    gold_result: Optional[Any] = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    retries: int = 0
    tools_used: List[str] = field(default_factory=list)


@dataclass
class EvaluationScore:
    """Result of a single evaluation metric applied to one case.

    Attributes:
        metric_name: Identifier matching the ``EvaluationMetric.NAME``.
        score: Numeric score in [0, 1] where 1 is a perfect match.
        details: Metric-specific diagnostic information.
    """

    metric_name: str
    score: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseResult:
    """Combines a benchmark case with its prediction and evaluation scores.

    Acts as the atomic unit for per-case reporting and aggregation.
    """

    case: BenchmarkCase
    prediction: PredictionResult
    scores: List[EvaluationScore] = field(default_factory=list)

    @property
    def is_correct(self) -> bool:
        """A case is correct when *every* scored metric returns 1.0.

        If no scores have been computed yet the case is considered incorrect.
        """
        if not self.scores:
            return False
        return all(s.score >= 1.0 for s in self.scores)


@dataclass
class BenchmarkRunResult:
    """Aggregated result of a complete benchmark run.

    Collects all per-case results together with metadata about the run
    environment so that results are fully reproducible and comparable.
    """

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    benchmark_name: str = ""
    db_type: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    case_results: List[CaseResult] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    # -- Computed properties --------------------------------------------------

    @property
    def total_cases(self) -> int:
        """Total number of cases that were evaluated."""
        return len(self.case_results)

    @property
    def correct_cases(self) -> int:
        """Number of cases where all metrics scored 1.0."""
        return sum(1 for cr in self.case_results if cr.is_correct)

    @property
    def accuracy(self) -> float:
        """Overall accuracy as a fraction in [0, 1].

        Returns 0.0 when there are no cases to avoid division by zero.
        """
        if self.total_cases == 0:
            return 0.0
        return self.correct_cases / self.total_cases

    @property
    def avg_latency_ms(self) -> float:
        """Mean prediction latency across all cases in milliseconds.

        Returns 0.0 when there are no cases.
        """
        if self.total_cases == 0:
            return 0.0
        return sum(cr.prediction.latency_ms for cr in self.case_results) / self.total_cases
