"""
QueryfyAI Benchmark CLI

Entry point for downloading data, running benchmarks, and generating
reports from the command line.

Usage::

    python -m benchmarks.cli download --dataset bird-mini-dev
    python -m benchmarks.cli run --config benchmarks/configs/smoke.yaml
    python -m benchmarks.cli run --config benchmarks/configs/smoke.yaml --suite bird-smoke
    python -m benchmarks.cli report --run-dir benchmarks/results/<run_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

# Map config db_type / transpile_from values to sqlglot dialect names
_DIALECT_MAP = {
    "sql": "sqlite", "sqlite": "sqlite",
    "postgresql": "postgres", "postgres": "postgres",
    "mysql": "mysql",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmarks.cli")


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------


def cmd_download(args: argparse.Namespace) -> None:
    """Download a benchmark dataset."""
    from benchmarks.datasets import get_dataset

    dataset = get_dataset(args.dataset)
    data_dir = Path(args.data_dir)
    logger.info("Downloading %s to %s", args.dataset, data_dir)
    dataset.download(data_dir)
    logger.info("Download complete for %s", args.dataset)


def _resolve_env_vars(obj):
    """Recursively resolve ``${VAR:-default}`` patterns in config values."""
    if isinstance(obj, str):
        def _replace(m):
            var = m.group(1)
            default = m.group(2) if m.group(2) is not None else ""
            return os.getenv(var, default)
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}", _replace, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def cmd_run(args: argparse.Namespace) -> None:
    """Run one or more benchmark suites defined in a YAML config."""
    from benchmarks.core.collector import ResultCollector
    from benchmarks.core.config import BenchmarkConfig
    from benchmarks.core.runner import BenchmarkRunner
    from benchmarks.datasets import get_dataset
    from benchmarks.evaluators import get_metric
    from benchmarks.harness.query_executor import BenchmarkQueryExecutor
    from benchmarks.harness.query_generator import DirectQueryGenerator

    # Load config with env-var resolution
    config_path = Path(args.config)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    raw = _resolve_env_vars(raw)
    config = BenchmarkConfig(**raw)

    # CLI overrides for LLM provider/model
    if args.provider:
        config.llm.provider = args.provider
    if args.model:
        config.llm.model = args.model

    # Filter to a single suite if requested
    suites = config.suites
    if args.suite:
        suites = [s for s in suites if s.name == args.suite]
        if not suites:
            logger.error("Suite %r not found in config", args.suite)
            sys.exit(1)

    collector = ResultCollector()

    for suite in suites:
        logger.info("Running suite: %s", suite.name)

        # Load dataset
        ds = get_dataset(suite.dataset)
        cases = ds.load(config.data_dir)

        # Apply filters
        if suite.max_cases:
            cases = cases[: suite.max_cases]
        if args.max_cases:
            cases = cases[: args.max_cases]

        # Resolve metrics — pass dialect kwargs for dialect_accuracy
        metrics = []
        for m in suite.metrics:
            if m == "dialect_accuracy" and suite.transpile_from:
                source = _DIALECT_MAP.get(suite.transpile_from, suite.transpile_from)
                target = _DIALECT_MAP.get(suite.db_type, suite.db_type)
                metrics.append(get_metric(m, source_dialect=source, target_dialect=target))
            else:
                metrics.append(get_metric(m))

        # Build generator — supports all 15 LLM providers
        api_key = os.getenv(config.llm.api_key_env, "")

        # Resolve client_secret from env var (oauth_gateway provider)
        client_secret = None
        if config.llm.client_secret_env:
            client_secret = os.getenv(config.llm.client_secret_env, "")

        generator = DirectQueryGenerator(
            provider=config.llm.provider,
            model=config.llm.model,
            api_key=api_key,
            temperature=config.llm.temperature,
            base_url=config.llm.base_url,
            token_url=config.llm.token_url,
            client_id=config.llm.client_id,
            client_secret=client_secret,
            auth_scope=config.llm.auth_scope,
            auth_type=config.llm.auth_type,
            tenant=config.llm.tenant,
            star=config.llm.star,
            chat_endpoint=config.llm.chat_endpoint,
            fast_model=config.llm.fast_model,
            enable_complexity_routing=config.llm.enable_complexity_routing,
        )

        # Build executor (only for execution-based metrics)
        executor = None
        needs_exec = any(m.REQUIRES_EXECUTION for m in metrics)
        if needs_exec:
            conn_map = {}

            # For multi-dialect suites with transpile_from, build connection
            # map from the suite's connection_url (target DB, not source)
            if suite.transpile_from and suite.connection_url:
                # All cases connect to the same target database
                for c in cases:
                    conn_map[c.db_name] = suite.connection_url
            else:
                # Standard: use dataset's own connection map
                if hasattr(ds, "get_connection_map"):
                    conn_map = ds.get_connection_map(config.data_dir)
                if suite.connection_url:
                    for c in cases:
                        conn_map.setdefault(c.db_name, suite.connection_url)

            # Determine executor db_type
            _exec_type_map = {
                "sql": "sqlite", "nosql_document": "mongodb",
                "nosql_wide_column": "cassandra", "nosql_key_value": "dynamodb",
            }
            db_type = _exec_type_map.get(suite.db_type, suite.db_type)
            executor = BenchmarkQueryExecutor(
                connection_map=conn_map,
                db_type=db_type,
            )

        # Progress callback
        async def on_progress(
            completed: int,
            total: int,
            result: Optional[object],
        ) -> None:
            if completed % 10 == 0 or completed == total:
                logger.info("Progress: %d/%d", completed, total)

        # Dialect transpilation for cross-dialect suites
        transpile_from = None
        target_dialect = None
        if suite.transpile_from:
            transpile_from = _DIALECT_MAP.get(suite.transpile_from, suite.transpile_from)
            target_dialect = _DIALECT_MAP.get(suite.db_type, suite.db_type)
            logger.info("  Cross-dialect: %s -> %s", transpile_from, target_dialect)

        runner = BenchmarkRunner(
            config=config,
            dataset=ds,
            metrics=metrics,
            query_generator=generator,
            query_executor=executor,
            progress_callback=on_progress,
            transpile_from=transpile_from,
            target_dialect=target_dialect,
        )

        # Run
        run_result = asyncio.run(runner.run(cases))

        # Summarise and save
        summary = collector.summarize(run_result, metrics)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        collector.save(run_result, summary, config.output_dir)

        _print_summary(summary)

        # Write GitHub summary if available
        if args.output_format == "github":
            _write_github_summary(summary)


def cmd_report(args: argparse.Namespace) -> None:
    """Print a summary from a previous run."""
    run_dir = Path(args.run_dir)
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        logger.error("No summary.json found in %s", run_dir)
        sys.exit(1)
    with open(summary_path) as f:
        summary = json.load(f)
    _print_summary(summary)


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------


def _print_summary(summary: dict) -> None:
    """Print a formatted summary to stdout."""
    overall = summary.get("overall", {})
    print()
    print("=" * 68)
    print(f"  Benchmark: {summary.get('benchmark', '?')}")
    print(f"  LLM: {summary.get('llm', '?')}")
    print(f"  Run ID: {summary.get('run_id', '?')}")
    print("=" * 68)

    print(f"\n  Total:     {overall.get('total', 0)}")
    print(f"  Correct:   {overall.get('correct', 0)}")
    print(f"  Accuracy:  {overall.get('accuracy_pct', 0):.1f}%")
    print(f"  Avg Lat:   {overall.get('avg_latency_ms', 0):.0f}ms")
    print(f"  Errors:    {overall.get('error_count', 0)}")

    by_diff = summary.get("by_difficulty", {})
    if by_diff:
        print(f"\n  {'Difficulty':<15} {'Correct':>8} {'Total':>8} {'Acc':>8}")
        print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*8}")
        for diff, stats in sorted(by_diff.items()):
            print(
                f"  {diff:<15} {stats['correct']:>8} "
                f"{stats['total']:>8} {stats['accuracy_pct']:>7.1f}%"
            )

    by_db = summary.get("by_database", {})
    if by_db:
        print(f"\n  {'Database':<25} {'Correct':>8} {'Total':>8} {'Acc':>8}")
        print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8}")
        for db, stats in sorted(by_db.items()):
            print(
                f"  {db:<25} {stats['correct']:>8} "
                f"{stats['total']:>8} {stats['accuracy_pct']:>7.1f}%"
            )

    print()
    print("=" * 68)


def _write_github_summary(summary: dict) -> None:
    """Write markdown to $GITHUB_STEP_SUMMARY if available."""
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    overall = summary.get("overall", {})
    lines = [
        f"## Benchmark: {summary.get('benchmark', '?')}",
        "",
        f"**LLM:** {summary.get('llm', '?')} | "
        f"**Run:** {summary.get('run_id', '?')}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Accuracy | **{overall.get('accuracy_pct', 0):.1f}%** "
        f"({overall.get('correct', 0)}/{overall.get('total', 0)}) |",
        f"| Avg Latency | {overall.get('avg_latency_ms', 0):.0f}ms |",
        f"| Errors | {overall.get('error_count', 0)} |",
        "",
    ]

    with open(summary_file, "a") as f:
        f.write("\n".join(lines) + "\n")


# ------------------------------------------------------------------
# Argument parser
# ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="benchmarks",
        description="QueryfyAI NL-to-Query Benchmark Runner",
    )
    sub = parser.add_subparsers(dest="command")

    # download
    dl = sub.add_parser("download", help="Download a benchmark dataset")
    dl.add_argument("--dataset", required=True, help="Dataset name")
    dl.add_argument(
        "--data-dir",
        default="benchmarks/data",
        help="Target directory",
    )

    # run
    run = sub.add_parser("run", help="Run benchmark suites")
    run.add_argument("--config", required=True, help="YAML config path")
    run.add_argument("--suite", help="Run a single suite by name")
    run.add_argument("--max-cases", type=int, help="Override max cases")
    run.add_argument(
        "--provider",
        help="Override LLM provider (e.g. openai, anthropic, azure, groq)",
    )
    run.add_argument(
        "--model",
        help="Override LLM model (e.g. gpt-4o, claude-sonnet-4-20250514)",
    )
    run.add_argument(
        "--output-format",
        choices=["console", "github"],
        default="console",
    )

    # report
    rp = sub.add_parser("report", help="Print report from a previous run")
    rp.add_argument("--run-dir", required=True, help="Path to run directory")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "download":
        cmd_download(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "report":
        cmd_report(args)


if __name__ == "__main__":
    main()
