"""
Retrieval-quality harness — recall@k for vector_db.get_relevant_schema().

Closes Tier A7 of the 2026-05-09 audit rollout. Source: Reviewer C move 3
("Build offline `recall@k` retrieval-quality harness").

This is the **measurement floor** for every Tier B retrieval change:
hybrid retrieval (B1), column-context fix (B2), embedding swap (B3),
column-level chunks (B4). Without it, a change to retrieval is "ship
and pray". With it, every change has a before/after number.

Read-only. Touches only the user's already-indexed `vector_db`. Does
not write to the cache, does not call any LLM, does not modify any
production code.

Usage:
    python -m benchmarks.retrieval.harness \
        --fixture benchmarks/retrieval/fixtures/demo.yaml \
        --connection-url postgresql://user:pass@host/db \
        [--k 5 10 15] \
        [--output json|text] \
        [--output-file results.json]

The fixture is a YAML file mapping questions to expected tables. For
each question, the harness calls vector_db.get_relevant_schema(query,
max_items=max(k)) and parses ``TABLE: <name>`` lines from the formatted
output. Then it computes per-question and aggregate metrics:

    recall@k = |retrieved ∩ expected| / |expected|
    fpr@k    = |retrieved \\ expected| / |retrieved|

Output: human-readable summary by default; JSON for trend tracking
(plug into Grafana/Prometheus if you want longitudinal recall@k
graphs).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Fixture types
# ---------------------------------------------------------------------------


@dataclass
class FixtureCase:
    """One (question, expected_tables) pair."""

    question: str
    expected_tables: List[str]
    notes: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FixtureCase":
        if "question" not in d or "expected_tables" not in d:
            raise ValueError(
                f"fixture case missing required field: {d!r} "
                f"(needs 'question' and 'expected_tables')"
            )
        return cls(
            question=str(d["question"]).strip(),
            expected_tables=[str(t).strip() for t in d["expected_tables"]],
            notes=d.get("notes"),
        )


@dataclass
class Fixture:
    """The full YAML fixture."""

    name: str
    description: str
    cases: List[FixtureCase]

    @classmethod
    def load(cls, path: Path) -> "Fixture":
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as e:
            raise SystemExit(
                "PyYAML is required: pip install pyyaml (or run inside "
                "the backend venv via bash backend/scripts/run-tests.sh)"
            ) from e
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict) or "cases" not in raw:
            raise ValueError(
                f"fixture must be a YAML mapping with 'cases': {path}"
            )
        return cls(
            name=str(raw.get("fixture_name", path.stem)),
            description=str(raw.get("description", "")).strip(),
            cases=[FixtureCase.from_dict(c) for c in raw["cases"]],
        )


# ---------------------------------------------------------------------------
# Retrieval output parser
# ---------------------------------------------------------------------------


# vector_db.get_relevant_schema() returns formatted text like:
#   TABLE: customers (schema: demoapp)
#       Columns: id, name, email, ...
#   COLLECTION: users        # MongoDB path uses COLLECTION instead
#       ...
#
# We match either prefix so the harness covers SQL, Cassandra,
# DynamoDB AND MongoDB with one fixture format. Without both, every
# Mongo run silently returned [], and recall was structurally 0 —
# the lie this audit doc warns about. Caught in the A7 deep review.
_TABLE_LINE = re.compile(r"^(?:TABLE|COLLECTION):\s*([^\s(]+)(?:\s*\(schema:\s*([^)]+)\))?")


def parse_retrieved_tables(text: str) -> List[str]:
    """
    Parse ``TABLE: <name> (schema: <schema>)`` and
    ``COLLECTION: <name>`` lines from the formatted schema text.
    Returns names in retrieval order (vector_db preserves rank
    ordering). Emits the schema-qualified form (``schema.table``)
    when a schema is present, else the bare name. Fixtures can use
    either form — ``_matches()`` treats them as equivalent.
    """
    out: List[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        m = _TABLE_LINE.match(line.strip())
        if not m:
            continue
        bare = m.group(1).strip()
        schema = (m.group(2) or "").strip()
        form = f"{schema}.{bare}" if schema else bare
        if form and form not in seen:
            seen.add(form)
            out.append(form)
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    """Per-case scoring outcome."""

    question: str
    expected: List[str]
    retrieved: List[str]
    metrics: Dict[int, Dict[str, float]] = field(default_factory=dict)


def _matches(a: str, b: str) -> bool:
    """
    Case-insensitive table-name equivalence that treats
    ``schema.table`` and bare ``table`` as the same. So a fixture
    case with expected_tables=["customers"] matches a retrieved
    ``demoapp.customers`` and vice versa.

    Match rule: lowercased, equal after stripping the leading
    ``schema.`` from whichever side has it. Exact equality also
    matches (the simple case).
    """
    al = a.lower()
    bl = b.lower()
    if al == bl:
        return True
    a_bare = al.rsplit(".", 1)[-1]
    b_bare = bl.rsplit(".", 1)[-1]
    # If either side is bare, allow match on the bare name. If both
    # are qualified, require exact match (already covered above).
    if "." not in al or "." not in bl:
        return a_bare == b_bare
    return False


def score_case(
    expected: List[str],
    retrieved: List[str],
    k_values: List[int],
) -> Dict[int, Dict[str, float]]:
    """
    Compute recall@k and FPR@k for every k in ``k_values``.

      recall@k = |expected ∩ retrieved[:k]| / |expected|   (0.0 if no expected)
      fpr@k    = |retrieved[:k] \\ expected| / |retrieved[:k]|   (0.0 if empty)

    Matching is case-insensitive and treats ``schema.table`` as
    equivalent to bare ``table`` — see :func:`_matches`.
    """
    out: Dict[int, Dict[str, float]] = {}
    for k in k_values:
        top_k = retrieved[:k]
        if expected:
            hits = sum(
                1 for e in expected if any(_matches(e, r) for r in top_k)
            )
            recall = hits / len(expected)
        else:
            recall = 1.0  # no expectation = trivially satisfied

        if top_k:
            misses = sum(
                1 for r in top_k if not any(_matches(e, r) for e in expected)
            )
            fpr = misses / len(top_k)
        else:
            fpr = 0.0
        out[k] = {"recall": round(recall, 4), "fpr": round(fpr, 4)}
    return out


def aggregate(results: List[CaseResult], k_values: List[int]) -> Dict[int, Dict[str, float]]:
    """Mean recall@k and mean FPR@k across all cases."""
    out: Dict[int, Dict[str, float]] = {}
    for k in k_values:
        recalls = [r.metrics[k]["recall"] for r in results if k in r.metrics]
        fprs = [r.metrics[k]["fpr"] for r in results if k in r.metrics]
        out[k] = {
            "mean_recall": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
            "mean_fpr": round(sum(fprs) / len(fprs), 4) if fprs else 0.0,
            "n": len(recalls),
        }
    return out


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def render_text(
    fixture: Fixture,
    results: List[CaseResult],
    agg: Dict[int, Dict[str, float]],
    k_values: List[int],
) -> str:
    lines: List[str] = []
    lines.append(f"Retrieval recall@k — fixture: {fixture.name}")
    if fixture.description:
        lines.append(f"  ({fixture.description})")
    lines.append("")
    lines.append(f"Cases: {len(results)}    k values: {k_values}")
    lines.append("")
    lines.append("Per-case results:")
    for r in results:
        ks = "  ".join(
            f"k={k} recall={r.metrics[k]['recall']:.2f} fpr={r.metrics[k]['fpr']:.2f}"
            for k in k_values
        )
        lines.append(f"  • {r.question[:70]!r:70s}  {ks}")
    lines.append("")
    lines.append("Aggregate:")
    for k in k_values:
        a = agg[k]
        lines.append(
            f"  k={k:2d}  mean_recall={a['mean_recall']:.3f}  "
            f"mean_fpr={a['mean_fpr']:.3f}  n={a['n']}"
        )
    return "\n".join(lines) + "\n"


def render_json(
    fixture: Fixture,
    results: List[CaseResult],
    agg: Dict[int, Dict[str, float]],
    k_values: List[int],
) -> str:
    return json.dumps(
        {
            "fixture": {"name": fixture.name, "description": fixture.description},
            "k_values": k_values,
            "aggregate": agg,
            "cases": [
                {
                    "question": r.question,
                    "expected": r.expected,
                    "retrieved": r.retrieved,
                    "metrics": r.metrics,
                }
                for r in results
            ],
        },
        indent=2,
    ) + "\n"


# ---------------------------------------------------------------------------
# Harness driver
# ---------------------------------------------------------------------------


RetrievalFn = Callable[[str, str, int], str]
"""(connection_url, query, max_items) -> formatted text"""


def run_harness(
    fixture: Fixture,
    retrieval_fn: RetrievalFn,
    connection_url: str,
    k_values: List[int],
) -> List[CaseResult]:
    """
    Run the harness against any function with the
    ``vector_db.get_relevant_schema`` shape. Inverting the dependency
    so unit tests can pass a deterministic fake — production runs
    pass `vector_db.get_relevant_schema`.
    """
    max_k = max(k_values)
    results: List[CaseResult] = []
    for case in fixture.cases:
        text = retrieval_fn(connection_url, case.question, max_k)
        retrieved = parse_retrieved_tables(text or "")
        metrics = score_case(case.expected_tables, retrieved, k_values)
        results.append(
            CaseResult(
                question=case.question,
                expected=case.expected_tables,
                retrieved=retrieved,
                metrics=metrics,
            )
        )
    return results


def _default_retrieval_fn() -> RetrievalFn:
    """
    Lazy import the production vector_db so the module can be imported
    in isolation (e.g. unit tests using `run_harness` with a fake fn).
    """

    def _call(connection_url: str, query: str, max_items: int) -> str:
        from app.services.vector_db import vector_db  # type: ignore[import-not-found]

        return vector_db.get_relevant_schema(
            connection_url=connection_url,
            query=query,
            max_items=max_items,
        )

    return _call


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="benchmarks.retrieval.harness",
        description="Offline recall@k measurement for vector_db schema retrieval.",
    )
    p.add_argument(
        "--fixture",
        required=True,
        type=Path,
        help="Path to YAML fixture (see fixtures/demo.yaml).",
    )
    p.add_argument(
        "--connection-url",
        required=True,
        help=(
            "Connection URL whose schema is already indexed in the "
            "user's vector_db (the harness does not index — it only "
            "measures the existing index)."
        ),
    )
    p.add_argument(
        "--k",
        type=int,
        nargs="+",
        default=[5, 10, 15],
        help="Cutoffs to compute recall and FPR at (default: 5 10 15).",
    )
    p.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Render format (default: text).",
    )
    p.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Write to file instead of stdout.",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    fixture = Fixture.load(args.fixture)
    results = run_harness(
        fixture=fixture,
        retrieval_fn=_default_retrieval_fn(),
        connection_url=args.connection_url,
        k_values=sorted(set(args.k)),
    )
    agg = aggregate(results, sorted(set(args.k)))

    if args.output == "json":
        out = render_json(fixture, results, agg, sorted(set(args.k)))
    else:
        out = render_text(fixture, results, agg, sorted(set(args.k)))

    if args.output_file:
        args.output_file.write_text(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
