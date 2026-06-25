"""
Aggregation detector (Phase 3a Day 3).

Given a SQL string and the result-set column names, decide whether the
query is analytical / aggregated and if so which columns it groups on.
The flag flows into ``execution_result`` so downstream engines (Phase
3c insight thresholds, chart recommender, the LLM prompt) can treat
aggregated results differently from raw rows.

Heuristic (regex-based, not AST):
  1. Aggregate function detection — scan the SQL for
     ``SUM/COUNT/AVG/MIN/MAX/STDDEV/VAR/MEDIAN/... (...)`` outside of
     subqueries the scanner can't see into. Any match → aggregated=True.
  2. GROUP BY extraction — find ``GROUP BY <cols>`` and parse the
     comma-separated column list up to the next clause (HAVING, ORDER
     BY, LIMIT, end-of-query, trailing ")").
  3. Aggregate-column names — column names returned by the query that
     match common aggregate prefixes (``sum_``, ``count_``, ``avg_``,
     ``total``, ``count``) or wrap an aggregate expression.

Known limitations (documented, not fixed):
  - Regex-based: subqueries with GROUP BY trigger outer aggregation
    flag. This is acceptable for Phase 3a — the false-positive only
    affects insight threshold tuning downstream, not correctness.
  - Dialect-specific aggregate functions (Snowflake's PERCENTILE_CONT,
    BigQuery's ARRAY_AGG) need the regex updated; the common set is
    covered.
  - CTEs with GROUP BY don't mark the outer SELECT as aggregated
    (regex only sees the first GROUP BY). Good enough for now.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


# Aggregate function names. Covers the ANSI set plus common warehouse
# extensions. Scan targets ``<FN>\s*\(`` to avoid false positives on
# column names that coincidentally contain these substrings.
_AGG_FUNCTIONS = (
    "SUM",
    "COUNT",
    "AVG",
    "MIN",
    "MAX",
    "STDDEV",
    "STDDEV_POP",
    "STDDEV_SAMP",
    "VAR",
    "VARIANCE",
    "VAR_POP",
    "VAR_SAMP",
    "MEDIAN",
    "ARRAY_AGG",
    "STRING_AGG",
    "LISTAGG",
    "GROUP_CONCAT",
    "BIT_AND",
    "BIT_OR",
    "BIT_XOR",
    "BOOL_AND",
    "BOOL_OR",
)

_AGG_FN_RE = re.compile(
    r"\b(?:" + "|".join(_AGG_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)

# Captures the column list of a GROUP BY clause up to the next clause
# terminator. Multiline-friendly. Non-greedy to stop at the first
# HAVING/ORDER/LIMIT/UNION/closing paren/end.
_GROUP_BY_RE = re.compile(
    r"\bGROUP\s+BY\s+(?P<cols>.+?)(?=\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|\bUNION\b|\bINTERSECT\b|\bEXCEPT\b|[\);]|$)",
    re.IGNORECASE | re.DOTALL,
)

# Column names that look like aggregates in the result set.
_AGG_COL_NAME_RE = re.compile(
    r"^(?:sum|count|avg|average|min|max|total|stddev|var|variance|median)[_.]?",
    re.IGNORECASE,
)


def detect_aggregation(
    sql: Optional[str],
    columns: Optional[List[str]] = None,
) -> Dict[str, object]:
    """
    Return a dict describing whether the query is aggregated.

    Shape:
        {
            "aggregated": bool,
            "grouping_columns": List[str],   # empty when no GROUP BY
            "aggregate_columns": List[str],  # result column names that look like aggregates
        }
    """
    columns = columns or []

    if not sql:
        return {
            "aggregated": False,
            "grouping_columns": [],
            "aggregate_columns": [],
        }

    has_agg_fn = bool(_AGG_FN_RE.search(sql))
    grouping_columns = _extract_group_by_columns(sql)
    aggregate_columns = [c for c in columns if _AGG_COL_NAME_RE.search(c or "")]

    aggregated = (
        has_agg_fn
        or bool(grouping_columns)
        or bool(aggregate_columns)
    )

    return {
        "aggregated": aggregated,
        "grouping_columns": grouping_columns,
        "aggregate_columns": aggregate_columns,
    }


def _extract_group_by_columns(sql: str) -> List[str]:
    """Regex-extract the column list of the first GROUP BY clause."""
    match = _GROUP_BY_RE.search(sql)
    if not match:
        return []
    cols_raw = match.group("cols").strip()
    # Split on top-level commas. Simple split is sufficient since the
    # common case is plain column identifiers; expressions like
    # ``ROLLUP(a, b)`` aren't handled (they're rare and documented as
    # a known limitation).
    parts = [p.strip() for p in cols_raw.split(",")]
    # Drop alias-qualifying backticks/quotes and trailing terms like
    # "1, 2" (positional GROUP BY) — those aren't column names.
    cleaned: List[str] = []
    for p in parts:
        p = p.strip().strip('"`[]')
        if not p:
            continue
        if p.isdigit():
            # Positional group-by — skip (we can't recover the column name
            # without the SELECT projection, which is a separate parse).
            continue
        # Take the last dotted component ("t.region" → "region")
        if "." in p:
            p = p.split(".")[-1].strip('"`[]')
        cleaned.append(p)
    return cleaned
