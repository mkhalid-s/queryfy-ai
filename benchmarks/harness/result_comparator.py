"""
QueryfyAI Benchmarks - Result Comparator

Compares result sets from gold and predicted query execution.
Handles order-insensitive comparison, type coercion, and NULL handling.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


def _normalise_value(v: Any) -> Any:
    """Normalise a single value for comparison."""
    if v is None:
        return None
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return v.strip()
    return v


def _extract_rows(result: Any) -> Optional[List[Tuple]]:
    """Extract a list of tuples from an executor result."""
    if result is None:
        return None

    rows: List = []
    if isinstance(result, dict):
        if not result.get("success", True):
            return None
        rows = result.get("rows", [])
    elif isinstance(result, list):
        rows = result
    else:
        return None

    tuples = []
    for row in rows:
        if isinstance(row, dict):
            values = tuple(_normalise_value(v) for v in row.values())
        elif isinstance(row, (list, tuple)):
            values = tuple(_normalise_value(v) for v in row)
        else:
            values = (_normalise_value(row),)
        tuples.append(values)

    return tuples


class ResultComparator:
    """Compares result sets from gold and predicted queries."""

    @staticmethod
    def compare(
        gold_result: Any,
        predicted_result: Any,
        order_matters: bool = False,
    ) -> Dict[str, Any]:
        """Compare two execution results.

        Args:
            gold_result: Result from executing the gold query.
            predicted_result: Result from executing the predicted query.
            order_matters: If ``True``, compare as ordered lists.
                Otherwise compare as unordered sets.

        Returns:
            Dictionary with ``match``, ``gold_row_count``,
            ``predicted_row_count``, ``matching_rows``, and ``details``.
        """
        gold_rows = _extract_rows(gold_result)
        pred_rows = _extract_rows(predicted_result)

        if gold_rows is None:
            return {
                "match": False,
                "gold_row_count": 0,
                "predicted_row_count": 0 if pred_rows is None else len(pred_rows),
                "matching_rows": 0,
                "details": "gold execution failed",
            }

        if pred_rows is None:
            return {
                "match": False,
                "gold_row_count": len(gold_rows),
                "predicted_row_count": 0,
                "matching_rows": 0,
                "details": "predicted execution failed",
            }

        if order_matters:
            match = gold_rows == pred_rows
            matching = sum(
                1 for g, p in zip(gold_rows, pred_rows) if g == p
            )
        else:
            gold_multiset = Counter(gold_rows)
            pred_multiset = Counter(pred_rows)
            match = gold_multiset == pred_multiset
            matching = sum((gold_multiset & pred_multiset).values())

        return {
            "match": match,
            "gold_row_count": len(gold_rows),
            "predicted_row_count": len(pred_rows),
            "matching_rows": matching,
            "details": "match" if match else "mismatch",
        }
