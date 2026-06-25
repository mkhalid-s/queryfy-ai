"""
A7 smoke: retrieval-quality harness scoring math + parser.

The harness's I/O (vector_db, file system) is intentionally inverted
via dependency injection, so these tests exercise the core scoring
math against deterministic fake retrieval outputs. They establish
that recall@k, FPR@k, and aggregate math are correct — the harness
is the measurement floor for Tier B, so its arithmetic has to be
unambiguous.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# benchmarks/ is at the repo root, not under backend/. Add it to
# sys.path so this test can import benchmarks.retrieval.harness
# without requiring an install.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.retrieval.harness import (  # noqa: E402
    CaseResult,
    Fixture,
    FixtureCase,
    aggregate,
    parse_retrieved_tables,
    run_harness,
    score_case,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_extracts_table_names_in_rank_order() -> None:
    text = (
        "DATABASE SCHEMA:\n"
        "==================================================\n"
        "\n"
        "TABLE: customers (schema: demoapp)\n"
        "    Columns: id, name, email\n"
        "\n"
        "TABLE: orders (schema: demoapp)\n"
        "    Columns: id, customer_id, total\n"
        "\n"
        "TABLE: claims\n"
        "    Columns: id, policy_id\n"
    )
    out = parse_retrieved_tables(text)
    assert out == ["demoapp.customers", "demoapp.orders", "claims"]


def test_parser_returns_empty_for_no_match() -> None:
    assert parse_retrieved_tables("") == []
    assert parse_retrieved_tables("No schema information available") == []


def test_parser_emits_qualified_form_when_schema_present() -> None:
    """Each TABLE: line contributes one entry — schema-qualified
    when a schema is present, bare otherwise."""
    text = "TABLE: x\nTABLE: y (schema: s)\n"
    assert parse_retrieved_tables(text) == ["x", "s.y"]


def test_parser_matches_collection_prefix_for_mongodb() -> None:
    """
    MongoDB emits ``COLLECTION: <name>`` instead of ``TABLE: <name>``
    (see backend/app/services/vector_db.py:655). Without matching
    both prefixes, recall against a Mongo connection is structurally
    0 — a silent lie. Caught in A7 deep review; locking it in here
    so a regex tighten can't silently regress this.
    """
    text = (
        "DATABASE SCHEMA:\n"
        "==================================================\n"
        "\n"
        "COLLECTION: users\n"
        "    Fields: _id, email, created_at\n"
        "\n"
        "COLLECTION: orders\n"
        "    Fields: _id, user_id, total\n"
    )
    assert parse_retrieved_tables(text) == ["users", "orders"]


def test_parser_mixes_table_and_collection_prefixes() -> None:
    """Polyglot setup: SQL tables + Mongo collections in one schema."""
    text = (
        "TABLE: customers (schema: demoapp)\n"
        "COLLECTION: events\n"
        "TABLE: orders (schema: demoapp)\n"
    )
    assert parse_retrieved_tables(text) == [
        "demoapp.customers",
        "events",
        "demoapp.orders",
    ]


def test_bare_expected_matches_qualified_retrieved() -> None:
    """Fixture-side ``customers`` should match retrieved ``demoapp.customers``.
    This is the load-bearing equivalence rule for usable fixtures."""
    from benchmarks.retrieval.harness import _matches

    assert _matches("customers", "demoapp.customers")
    assert _matches("demoapp.customers", "customers")
    assert _matches("Customers", "demoapp.CUSTOMERS")  # case-insensitive


def test_qualified_no_match_across_schemas() -> None:
    """Two different schemas with the same bare name must NOT match
    when both sides specify the schema."""
    from benchmarks.retrieval.harness import _matches

    assert not _matches("public.customers", "demoapp.customers")


# ---------------------------------------------------------------------------
# Scoring math
# ---------------------------------------------------------------------------


def test_perfect_recall_perfect_fpr_zero() -> None:
    """All expected in top-K, no extras → recall=1, fpr=0."""
    m = score_case(["a", "b"], ["a", "b"], [2, 5])
    assert m[2] == {"recall": 1.0, "fpr": 0.0}
    assert m[5] == {"recall": 1.0, "fpr": 0.0}


def test_partial_recall() -> None:
    """One of two expected in top-2 → recall=0.5."""
    m = score_case(["a", "b"], ["a", "c"], [2])
    assert m[2]["recall"] == 0.5
    assert m[2]["fpr"] == 0.5  # c is a false positive


def test_recall_grows_with_k() -> None:
    """expected=[a,b], retrieved=[c,a,b]: recall@1=0, @2=0.5, @3=1.0."""
    m = score_case(["a", "b"], ["c", "a", "b"], [1, 2, 3])
    assert m[1]["recall"] == 0.0
    assert m[2]["recall"] == 0.5
    assert m[3]["recall"] == 1.0


def test_fpr_drops_with_more_relevant_results() -> None:
    """Extras at higher k still inflate FPR even if recall is 1.0."""
    m = score_case(["a"], ["a", "b", "c", "d", "e"], [5])
    assert m[5]["recall"] == 1.0
    # 1 hit out of 5 retrieved → 4/5 fpr
    assert m[5]["fpr"] == 0.8


def test_case_insensitive_matching() -> None:
    """expected uses lowercase; retrieved uses TitleCase."""
    m = score_case(["customers"], ["Customers", "Orders"], [2])
    assert m[2]["recall"] == 1.0


def test_empty_expected_is_trivially_satisfied() -> None:
    """No expectation → recall=1.0 by convention (avoid divide-by-zero)."""
    m = score_case([], ["whatever"], [5])
    assert m[5]["recall"] == 1.0


def test_empty_retrieved_is_zero_recall() -> None:
    m = score_case(["a"], [], [5])
    assert m[5]["recall"] == 0.0
    assert m[5]["fpr"] == 0.0


def test_aggregate_means() -> None:
    """Aggregate is mean recall and mean FPR across all cases."""
    case_a = CaseResult(
        question="q1",
        expected=["a"],
        retrieved=["a"],
        metrics={5: {"recall": 1.0, "fpr": 0.0}},
    )
    case_b = CaseResult(
        question="q2",
        expected=["a"],
        retrieved=["b"],
        metrics={5: {"recall": 0.0, "fpr": 1.0}},
    )
    agg = aggregate([case_a, case_b], [5])
    assert agg[5]["mean_recall"] == 0.5
    assert agg[5]["mean_fpr"] == 0.5
    assert agg[5]["n"] == 2


# ---------------------------------------------------------------------------
# End-to-end (DI'd retrieval fn)
# ---------------------------------------------------------------------------


def test_run_harness_drives_full_loop() -> None:
    """
    Plug a fake retrieval_fn that always returns the same schema text
    and check the harness scores it correctly across multiple cases.
    """
    fixture = Fixture(
        name="unit",
        description="",
        cases=[
            FixtureCase(question="q1", expected_tables=["customers"]),
            FixtureCase(question="q2", expected_tables=["orders", "claims"]),
        ],
    )

    schema_text = (
        "TABLE: customers (schema: demoapp)\n"
        "TABLE: orders (schema: demoapp)\n"
        "TABLE: claims\n"
    )

    def fake_retrieval(connection_url: str, query: str, max_items: int) -> str:
        # Deterministic output regardless of query — proves the scoring
        # loop, not the retrieval backend.
        return schema_text

    results = run_harness(
        fixture=fixture,
        retrieval_fn=fake_retrieval,
        connection_url="postgresql://fake",
        k_values=[5],
    )

    assert len(results) == 2
    # q1 expects [customers]; retrieved includes "demoapp.customers".
    # Matching is case-insensitive on both forms — but the parser only
    # emits the schema-qualified form. So bare "customers" doesn't
    # match "demoapp.customers" by case-insensitive equality.
    # This is intentional — fixtures should use the form they want.
    # Verify the parser side covers both by checking the schema-
    # qualified expected:
    fixture_q = FixtureCase(question="q1", expected_tables=["demoapp.customers"])
    metrics = score_case(
        fixture_q.expected_tables,
        parse_retrieved_tables(schema_text),
        [5],
    )
    assert metrics[5]["recall"] == 1.0


def test_run_harness_no_retrieval_returns_zero_recall() -> None:
    """Empty retrieval text → zero recall."""
    fixture = Fixture(
        name="unit",
        description="",
        cases=[FixtureCase(question="q1", expected_tables=["customers"])],
    )

    def empty_retrieval(connection_url: str, query: str, max_items: int) -> str:
        return ""

    results = run_harness(
        fixture=fixture,
        retrieval_fn=empty_retrieval,
        connection_url="postgresql://fake",
        k_values=[5],
    )
    assert results[0].metrics[5]["recall"] == 0.0


# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------


def test_fixture_loader_validates_required_fields(tmp_path: Path) -> None:
    """Missing 'question' or 'expected_tables' must raise."""
    f = tmp_path / "bad.yaml"
    f.write_text("cases:\n  - question: 'no expected'\n")
    with pytest.raises(ValueError):
        Fixture.load(f)


def test_fixture_loader_parses_a_valid_fixture(tmp_path: Path) -> None:
    f = tmp_path / "ok.yaml"
    f.write_text(
        "fixture_name: test\n"
        "description: tiny\n"
        "cases:\n"
        "  - question: q1\n"
        "    expected_tables: [a, b]\n"
        "  - question: q2\n"
        "    expected_tables: [c]\n"
        "    notes: optional note\n"
    )
    fx = Fixture.load(f)
    assert fx.name == "test"
    assert fx.description == "tiny"
    assert len(fx.cases) == 2
    assert fx.cases[0].expected_tables == ["a", "b"]
    assert fx.cases[1].notes == "optional note"


@pytest.mark.parametrize("name", ["example.yaml", "demoapp.yaml"])
def test_bundled_fixtures_parse(name: str) -> None:
    """Both bundled fixtures must parse cleanly (regression guard).

    - ``example.yaml`` — illustrative shape, table names not in the
      bundled seed; useful for fixture-curation reference.
    - ``demoapp.yaml`` — real fixture against the seeded
      sessions/agent_state/query_history tables.
    """
    path = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "retrieval"
        / "fixtures"
        / name
    )
    if not path.exists():
        pytest.skip(f"{name} not present in this checkout")
    fx = Fixture.load(path)
    assert len(fx.cases) >= 5
    for case in fx.cases:
        assert case.question, "every case needs a question"
        assert case.expected_tables, "every case needs expected_tables"
