#!/usr/bin/env python3
"""
Benchmark Results Comparison & Regression Detection

Compares the latest benchmark run against previous runs in the results
directory. Detects accuracy regressions and reports trends.

Usage:
    python benchmarks/scripts/compare-results.py --results-dir benchmarks/results
    python benchmarks/scripts/compare-results.py --results-dir benchmarks/results --format github
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("compare-results")

# Regression threshold: flag if accuracy drops by more than this
REGRESSION_THRESHOLD_PCT = 5.0


def _load_summaries(results_dir: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    """Load all summary.json files from the results directory, sorted by date.

    Sorts by the ``started_at`` timestamp inside summary.json when
    available, falling back to the file modification time.  This
    ensures correct chronological ordering even when run directories
    use UUID names that don't sort chronologically.
    """
    summaries = []
    if not results_dir.exists():
        return summaries

    for run_dir in results_dir.iterdir():
        if not run_dir.is_dir():
            continue
        summary_file = run_dir / "summary.json"
        if summary_file.exists():
            try:
                with open(summary_file) as f:
                    data = json.load(f)
                summaries.append((run_dir, data))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping %s: %s", summary_file, exc)

    # Sort chronologically: prefer started_at from summary, fall back to mtime.
    # Both are normalised to float (epoch seconds) so that the sort key type
    # is consistent regardless of which source is used.
    def _sort_key(item: Tuple[Path, Dict[str, Any]]) -> float:
        started = item[1].get("started_at", "")
        if started:
            try:
                from datetime import datetime, timezone
                # Handle ISO 8601 timestamps (with or without timezone)
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        # Fall back to file modification time
        summary_path = item[0] / "summary.json"
        try:
            return summary_path.stat().st_mtime
        except OSError:
            return 0.0

    summaries.sort(key=_sort_key)
    return summaries


def _compare(
    current: Dict[str, Any],
    previous: Optional[Dict[str, Any]],
    threshold: float = REGRESSION_THRESHOLD_PCT,
) -> Dict[str, Any]:
    """Compare current run against previous run."""
    curr_overall = current.get("overall", {})
    result = {
        "benchmark": current.get("benchmark", "?"),
        "llm": current.get("llm", "?"),
        "run_id": current.get("run_id", "?"),
        "accuracy_pct": curr_overall.get("accuracy_pct", 0.0),
        "total": curr_overall.get("total", 0),
        "correct": curr_overall.get("correct", 0),
        "avg_latency_ms": curr_overall.get("avg_latency_ms", 0),
        "errors": curr_overall.get("error_count", 0),
    }

    if previous is not None:
        prev_overall = previous.get("overall", {})
        prev_acc = prev_overall.get("accuracy_pct", 0.0)
        curr_acc = curr_overall.get("accuracy_pct", 0.0)
        delta = curr_acc - prev_acc

        result["previous_accuracy_pct"] = prev_acc
        result["delta_pct"] = round(delta, 2)
        result["regression"] = delta < -threshold
        result["previous_run_id"] = previous.get("run_id", "?")
    else:
        result["previous_accuracy_pct"] = None
        result["delta_pct"] = None
        result["regression"] = False
        result["previous_run_id"] = None

    return result


def _print_console(comparisons: List[Dict[str, Any]]) -> None:
    """Print comparison results to console."""
    print()
    print("=" * 72)
    print("  Benchmark Comparison Report")
    print("=" * 72)

    has_regression = False
    for comp in comparisons:
        print(f"\n  Benchmark: {comp['benchmark']}")
        print(f"  LLM:       {comp['llm']}")
        print(f"  Run ID:    {comp['run_id']}")
        print(f"  Accuracy:  {comp['accuracy_pct']:.1f}% ({comp['correct']}/{comp['total']})")
        print(f"  Latency:   {comp['avg_latency_ms']:.0f}ms avg")
        print(f"  Errors:    {comp['errors']}")

        if comp["delta_pct"] is not None:
            direction = "+" if comp["delta_pct"] >= 0 else ""
            print(f"  Delta:     {direction}{comp['delta_pct']:.1f}% vs {comp['previous_run_id']}")
            if comp["regression"]:
                print(f"  *** REGRESSION DETECTED: accuracy dropped by {abs(comp['delta_pct']):.1f}% ***")
                has_regression = True

    print()
    print("=" * 72)

    if has_regression:
        print("  WARNING: One or more benchmarks show accuracy regression!")
        print("=" * 72)


def _write_github_summary(comparisons: List[Dict[str, Any]]) -> None:
    """Write comparison results as markdown to $GITHUB_STEP_SUMMARY."""
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_file:
        logger.info("GITHUB_STEP_SUMMARY not set, skipping GitHub output")
        return

    lines = [
        "## Benchmark Comparison Report",
        "",
        "| Benchmark | LLM | Accuracy | Delta | Latency | Errors | Status |",
        "|-----------|-----|----------|-------|---------|--------|--------|",
    ]

    has_regression = False
    for comp in comparisons:
        delta_str = "—"
        status = "baseline"
        if comp["delta_pct"] is not None:
            direction = "+" if comp["delta_pct"] >= 0 else ""
            delta_str = f"{direction}{comp['delta_pct']:.1f}%"
            if comp["regression"]:
                status = "regression"
                has_regression = True
            elif comp["delta_pct"] > 0:
                status = "improved"
            else:
                status = "stable"

        lines.append(
            f"| {comp['benchmark']} "
            f"| {comp['llm']} "
            f"| **{comp['accuracy_pct']:.1f}%** ({comp['correct']}/{comp['total']}) "
            f"| {delta_str} "
            f"| {comp['avg_latency_ms']:.0f}ms "
            f"| {comp['errors']} "
            f"| {'**REGRESSION**' if comp['regression'] else status} |"
        )

    lines.append("")

    if has_regression:
        lines.extend([
            f"> **Warning:** Accuracy regression detected (>{REGRESSION_THRESHOLD_PCT}% drop).",
            "> Review benchmark results and recent changes.",
            "",
        ])

    with open(summary_file, "a") as f:
        f.write("\n".join(lines) + "\n")

    logger.info("Comparison report written to GITHUB_STEP_SUMMARY")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare benchmark results and detect regressions"
    )
    parser.add_argument(
        "--results-dir",
        default="benchmarks/results",
        help="Directory containing benchmark run results",
    )
    parser.add_argument(
        "--format",
        choices=["console", "github"],
        default="console",
        help="Output format",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=REGRESSION_THRESHOLD_PCT,
        help=f"Regression threshold in percent (default: {REGRESSION_THRESHOLD_PCT})",
    )

    args = parser.parse_args()
    results_dir = Path(args.results_dir)
    threshold = args.threshold

    summaries = _load_summaries(results_dir)
    if not summaries:
        logger.info("No benchmark results found in %s", results_dir)
        sys.exit(0)

    if len(summaries) < 2:
        logger.info("Only one run found — no comparison possible, reporting baseline")
        comparisons = [_compare(summaries[-1][1], None, threshold)]
    else:
        # Compare the latest run against the second-to-latest
        current = summaries[-1][1]
        previous = summaries[-2][1]
        comparisons = [_compare(current, previous, threshold)]

    _print_console(comparisons)

    if args.format == "github":
        _write_github_summary(comparisons)

    # Exit with error if regression detected
    if any(c["regression"] for c in comparisons):
        sys.exit(1)


if __name__ == "__main__":
    main()
