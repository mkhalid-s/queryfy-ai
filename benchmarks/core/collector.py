"""
QueryfyAI Benchmarks - Result Collector

Aggregates benchmark results with breakdowns by difficulty, database,
and metric.  Produces summary dictionaries suitable for JSON serialisation
and report generation.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from benchmarks.core.evaluator import EvaluationMetric
from benchmarks.core.types import BenchmarkRunResult, CaseResult

logger = logging.getLogger(__name__)


class ResultCollector:
    """Aggregates, persists, and reports benchmark results.

    Breakdowns produced:
    - Overall accuracy / latency / cost
    - Per-difficulty
    - Per-database
    - Per-metric
    - Error listing
    """

    def summarize(
        self,
        run_result: BenchmarkRunResult,
        metrics: List[EvaluationMetric],
    ) -> Dict[str, Any]:
        """Produce a complete summary of a benchmark run.

        Returns:
            Dictionary with ``overall``, ``by_difficulty``, ``by_database``,
            ``by_metric``, and ``errors`` keys.
        """
        return {
            "run_id": run_result.run_id,
            "benchmark": run_result.benchmark_name,
            "db_type": run_result.db_type,
            "llm": f"{run_result.llm_provider}/{run_result.llm_model}",
            "started_at": (
                run_result.started_at.isoformat() if run_result.started_at else None
            ),
            "completed_at": (
                run_result.completed_at.isoformat()
                if run_result.completed_at
                else None
            ),
            "overall": self._overall_stats(run_result),
            "by_difficulty": self._by_difficulty(run_result),
            "by_database": self._by_database(run_result),
            "by_metric": self._by_metric(run_result, metrics),
            "errors": self._collect_errors(run_result),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(
        self,
        run_result: BenchmarkRunResult,
        summary: Dict[str, Any],
        output_dir: Path,
    ) -> Path:
        """Write summary and per-case details to *output_dir*.

        Returns:
            Path to the created run directory.
        """
        run_dir = output_dir / run_result.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Summary JSON
        with open(run_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2, default=str)

        # Per-case JSONL (streaming-safe)
        with open(run_dir / "cases.jsonl", "w") as f:
            for cr in run_result.case_results:
                entry = {
                    "case_id": cr.case.case_id,
                    "db_name": cr.case.db_name,
                    "difficulty": cr.case.difficulty.value,
                    "predicted_query": cr.prediction.predicted_query,
                    "gold_query": cr.case.gold_query,
                    "latency_ms": round(cr.prediction.latency_ms, 1),
                    "tokens_used": cr.prediction.tokens_used,
                    "error": cr.prediction.error,
                    "scores": {
                        s.metric_name: s.score for s in cr.scores
                    },
                    "is_correct": cr.is_correct,
                }
                f.write(json.dumps(entry, default=str) + "\n")

        # Config snapshot
        with open(run_dir / "config.json", "w") as f:
            json.dump(run_result.config, f, indent=2, default=str)

        logger.info("Results saved to %s", run_dir)
        return run_dir

    # ------------------------------------------------------------------
    # Breakdown helpers
    # ------------------------------------------------------------------

    def _overall_stats(self, run: BenchmarkRunResult) -> Dict[str, Any]:
        total = run.total_cases
        correct = run.correct_cases
        latencies = [cr.prediction.latency_ms for cr in run.case_results]
        costs = [cr.prediction.cost_usd for cr in run.case_results]
        errors = sum(1 for cr in run.case_results if cr.prediction.error)

        return {
            "total": total,
            "correct": correct,
            "accuracy": round(run.accuracy, 4),
            "accuracy_pct": round(run.accuracy * 100, 2),
            "avg_latency_ms": round(run.avg_latency_ms, 1),
            "p95_latency_ms": round(
                sorted(latencies)[min(int(len(latencies) * 0.95), len(latencies) - 1)] if latencies else 0, 1
            ),
            "total_cost_usd": round(sum(costs), 4),
            "error_count": errors,
        }

    def _by_difficulty(self, run: BenchmarkRunResult) -> Dict[str, Any]:
        groups: Dict[str, List[CaseResult]] = defaultdict(list)
        for cr in run.case_results:
            groups[cr.case.difficulty.value].append(cr)

        return {
            diff: self._group_stats(cases)
            for diff, cases in sorted(groups.items())
        }

    def _by_database(self, run: BenchmarkRunResult) -> Dict[str, Any]:
        groups: Dict[str, List[CaseResult]] = defaultdict(list)
        for cr in run.case_results:
            groups[cr.case.db_name].append(cr)

        return {
            db: self._group_stats(cases) for db, cases in sorted(groups.items())
        }

    def _by_metric(
        self,
        run: BenchmarkRunResult,
        metrics: List[EvaluationMetric],
    ) -> Dict[str, Any]:
        result = {}
        for metric in metrics:
            scores = []
            for cr in run.case_results:
                for s in cr.scores:
                    if s.metric_name == metric.NAME:
                        scores.append(s)
            result[metric.NAME] = metric.aggregate(scores)
        return result

    def _collect_errors(self, run: BenchmarkRunResult) -> List[Dict[str, Any]]:
        errors = []
        for cr in run.case_results:
            if cr.prediction.error:
                errors.append(
                    {
                        "case_id": cr.case.case_id,
                        "db_name": cr.case.db_name,
                        "error": cr.prediction.error,
                    }
                )
        return errors

    @staticmethod
    def _group_stats(cases: List[CaseResult]) -> Dict[str, Any]:
        total = len(cases)
        correct = sum(1 for c in cases if c.is_correct)
        return {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / max(total, 1), 4),
            "accuracy_pct": round((correct / max(total, 1)) * 100, 2),
        }
