#!/usr/bin/env python3
"""
Test data generator (Step 1c).

Produces paired raw / aggregated JSON fixtures so analysis engines can
be validated in both modes from a single source of truth. Phase 3c.1
threshold-recalibration tests consume these.

Usage:
    python scripts/gen_test_data.py --rows 1000 --output tests/fixtures/
    python scripts/gen_test_data.py --rows 500 --seed 42 --output /tmp/td/

Writes (per run):
    raw_rows.json          — flat list of N rows, each dict has
                             region, product, date, revenue, quantity,
                             customer_id, policy_id
    grouped_by_region.json — aggregated view: region, total_revenue,
                             total_quantity, avg_revenue, row_count
    grouped_by_month.json  — month, total_revenue, row_count
    grouped_by_region_product.json — region, product, total_revenue, row_count
    metadata.json          — generator args + column types for reference

The raw rows include realistic cardinality:
    - region: 5 distinct (NA, EU, APAC, LATAM, MEA)
    - product: 8 distinct SKUs
    - date: daily across 12 months of 2024
    - revenue: log-normal-ish around $500 with seasonal bumps
    - quantity: Poisson(lambda=4) clipped to 1..20
    - customer_id: all-unique (for smart-ID-exclusion tests)
    - policy_id: all-unique (same reason)

The deterministic seed ensures fixtures are reproducible across CI
runs.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List


REGIONS = ["NA", "EU", "APAC", "LATAM", "MEA"]
PRODUCTS = [
    "WIDGET-A",
    "WIDGET-B",
    "GADGET-X",
    "GADGET-Y",
    "TOOL-1",
    "TOOL-2",
    "SERVICE-ALPHA",
    "SERVICE-BETA",
]


def _lognormal(rng: random.Random, mu: float = 5.5, sigma: float = 0.6) -> float:
    """Cheap log-normal-ish sample without numpy."""
    return math.exp(rng.gauss(mu, sigma))


def _poisson(rng: random.Random, lam: float = 4.0) -> int:
    """Knuth's algorithm — fine for small lambdas."""
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def generate_raw_rows(rows: int, seed: int = 0) -> List[Dict[str, Any]]:
    """Generate ``rows`` synthetic transaction-like records."""
    rng = random.Random(seed)
    base_date = date(2024, 1, 1)
    out: List[Dict[str, Any]] = []
    for i in range(rows):
        day_offset = rng.randint(0, 365)
        row_date = base_date + timedelta(days=day_offset)
        region = REGIONS[rng.randint(0, len(REGIONS) - 1)]
        product = PRODUCTS[rng.randint(0, len(PRODUCTS) - 1)]
        # Seasonal bump for Q4
        seasonal = 1.3 if row_date.month >= 10 else 1.0
        revenue = round(_lognormal(rng) * seasonal, 2)
        quantity = max(1, min(20, _poisson(rng, lam=4.0)))
        out.append(
            {
                "customer_id": 10000 + i,   # all-unique
                "policy_id": 20000 + i,     # all-unique
                "region": region,
                "product": product,
                "date": row_date.isoformat(),
                "revenue": revenue,
                "quantity": quantity,
            }
        )
    return out


def group_by(
    rows: List[Dict[str, Any]],
    keys: List[str],
) -> List[Dict[str, Any]]:
    """Aggregate ``rows`` by the tuple of ``keys``."""
    buckets: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        k = tuple(r[key] for key in keys)
        b = buckets.setdefault(
            k,
            {
                **{key: r[key] for key in keys},
                "row_count": 0,
                "total_revenue": 0.0,
                "total_quantity": 0,
            },
        )
        b["row_count"] += 1
        b["total_revenue"] = round(b["total_revenue"] + r["revenue"], 2)
        b["total_quantity"] += r["quantity"]
    rollups: List[Dict[str, Any]] = []
    for b in buckets.values():
        b["avg_revenue"] = round(b["total_revenue"] / b["row_count"], 2)
        rollups.append(b)
    # Stable sort for deterministic fixtures
    rollups.sort(key=lambda r: tuple(r.get(k) for k in keys))
    return rollups


def group_by_month(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate by YYYY-MM extracted from ``date``."""
    buckets: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        month = r["date"][:7]
        b = buckets.setdefault(
            month,
            {"month": month, "row_count": 0, "total_revenue": 0.0},
        )
        b["row_count"] += 1
        b["total_revenue"] = round(b["total_revenue"] + r["revenue"], 2)
    out = list(buckets.values())
    out.sort(key=lambda r: r["month"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate paired raw / aggregated test fixtures"
    )
    parser.add_argument("--rows", type=int, default=1000, help="raw row count")
    parser.add_argument("--seed", type=int, default=0, help="deterministic seed")
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="output directory (created if missing)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = generate_raw_rows(args.rows, seed=args.seed)
    (out_dir / "raw_rows.json").write_text(json.dumps(raw, indent=2))

    grouped_region = group_by(raw, ["region"])
    (out_dir / "grouped_by_region.json").write_text(
        json.dumps(grouped_region, indent=2)
    )

    grouped_month = group_by_month(raw)
    (out_dir / "grouped_by_month.json").write_text(
        json.dumps(grouped_month, indent=2)
    )

    grouped_region_product = group_by(raw, ["region", "product"])
    (out_dir / "grouped_by_region_product.json").write_text(
        json.dumps(grouped_region_product, indent=2)
    )

    metadata = {
        "rows": args.rows,
        "seed": args.seed,
        "columns": {
            "customer_id": "int (all-unique — ID exclusion target)",
            "policy_id": "int (all-unique — ID exclusion target)",
            "region": "categorical (5 values)",
            "product": "categorical (8 values)",
            "date": "ISO date (12 months of 2024)",
            "revenue": "float (log-normal, Q4 seasonal bump)",
            "quantity": "int (Poisson(lambda=4), clipped 1..20)",
        },
        "aggregates": {
            "grouped_by_region.json": f"{len(grouped_region)} groups",
            "grouped_by_month.json": f"{len(grouped_month)} groups",
            "grouped_by_region_product.json": f"{len(grouped_region_product)} groups",
        },
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    print(f"Generated {args.rows} raw rows + 3 aggregated views in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
