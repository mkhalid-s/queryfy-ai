# Retrieval-quality harness (recall@k)

**Closes Tier A7 of the 2026-05-09 audit rollout.** Source: Reviewer C move 3.

This harness is the **measurement floor for every Tier B retrieval change**:
hybrid retrieval (B1), column-context fix (B2), embedding swap (B3),
column-level chunks (B4). Without it, retrieval changes are ship-and-pray.
With it, every change has a before/after number.

## What it measures

For each `(question, expected_tables)` case in a YAML fixture:

1. Calls `vector_db.get_relevant_schema(connection_url, question, max_items=max(k))`.
2. Parses `TABLE: <name>` lines from the formatted output.
3. Computes per-question and aggregate metrics:
   - `recall@k = |expected ∩ retrieved[:k]| / |expected|`
   - `fpr@k    = |retrieved[:k] \ expected| / |retrieved[:k]|`

Defaults: `k ∈ {5, 10, 15}`.

## What it doesn't do

- **No indexing**. The harness only measures the existing index. Run
  `/api/v1/schema/refresh` (or whatever your indexing path is) first.
- **No LLM calls**. Read-only against the vector DB.
- **No production-code changes**. Standalone script under `benchmarks/`.

## Usage

From the repo root, inside the backend venv:

```bash
# Run against an already-indexed connection
python -m benchmarks.retrieval.harness \
  --fixture benchmarks/retrieval/fixtures/demoapp.yaml \
  --connection-url postgresql://demo:demo@localhost:5432/demoapp

# Custom k values
python -m benchmarks.retrieval.harness \
  --fixture benchmarks/retrieval/fixtures/demoapp.yaml \
  --connection-url postgresql://demo:demo@localhost:5432/demoapp \
  --k 3 5 10 20

# JSON output for trend tracking
python -m benchmarks.retrieval.harness \
  --fixture benchmarks/retrieval/fixtures/demoapp.yaml \
  --connection-url postgresql://demo:demo@localhost:5432/demoapp \
  --output json \
  --output-file results/$(date +%Y-%m-%d).json
```

## Bundled fixtures

- **`fixtures/demoapp.yaml`** — matches the seeded `sessions / agent_state / query_history` schema produced by `scripts/init-db/01-init.sql`. Use this against the bundled docker-compose dev stack.
- **`fixtures/example.yaml`** — illustrative *shape only*. Table names (customers, orders, policies, claims, agents, ...) are NOT in the bundled seed. Useful as a starting point when curating a fixture for your own schema.

## Fixture format

```yaml
fixture_name: demo
description: >
  Hand-curated cases against the demoapp Postgres schema.

cases:
  - question: "show me top 10 customers by revenue"
    expected_tables: [customers, orders]

  - question: "policies expiring this month"
    expected_tables: [policies]
    notes: optional free-text note
```

`expected_tables` can be bare names (`customers`) or schema-qualified
(`demoapp.customers`). The parser emits both forms — matching is
case-insensitive.

## Curating a fixture

Aim for ~20–50 cases that exercise the failure modes the next Tier B
change is supposed to fix:

- **Abbreviated column names** (`cust_id` ↔ "customer id") — these hurt
  dense-only retrieval the worst; expected to improve under hybrid (B1).
- **Multi-table intent** ("customers who have never placed an order") —
  exercises whether top-K reaches both tables.
- **Business-domain terms** ("policies expiring this month") — exercises
  the data-dictionary path (B2 column-context fix).
- **Schema-qualified vs bare name preferences** — your call.

## Use in CI

The harness is intentionally standalone so it can be called from a CI
job that:

1. Stands up a containerized Postgres seeded from a known SQL file.
2. Indexes the schema via the app's `/api/v1/schema/refresh`.
3. Runs the harness with `--output json`.
4. Compares the aggregate `mean_recall` against a baseline.
5. Fails if recall drops by more than X% vs the baseline.

Each Tier B PR should attach a before/after harness output, per the
Tier B PR conventions in `docs/PLAN-TRACKER.md`.

## References

- Audit: `docs/deep-audit-2026-05-09.md` Tier A row #7 (Reviewer C move 3).
- Tracker: `docs/PLAN-TRACKER.md` Tier A row A7.
- Underlying retrieval: `backend/app/services/vector_db.py:get_relevant_schema`.
