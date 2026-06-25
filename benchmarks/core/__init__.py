"""
QueryfyAI Benchmarks - Core Framework

Contains shared types, abstract interfaces, configuration models,
the benchmark runner, and result collection/aggregation.
"""

from benchmarks.core.collector import ResultCollector
from benchmarks.core.config import BenchmarkConfig, LLMBenchmarkConfig, SuiteConfig
from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.core.evaluator import EvaluationMetric
from benchmarks.core.runner import BenchmarkRunner
from benchmarks.core.types import (
    BenchmarkCase,
    BenchmarkRunResult,
    CaseResult,
    DatabaseCategory,
    Difficulty,
    EvaluationScore,
    PredictionResult,
)

__all__ = [
    "BenchmarkCase",
    "BenchmarkConfig",
    "BenchmarkDataset",
    "BenchmarkRunResult",
    "BenchmarkRunner",
    "CaseResult",
    "DatabaseCategory",
    "Difficulty",
    "EvaluationMetric",
    "EvaluationScore",
    "LLMBenchmarkConfig",
    "PredictionResult",
    "ResultCollector",
    "SuiteConfig",
]
