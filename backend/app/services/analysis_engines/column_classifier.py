"""
Unified column classifier (Phase 2 Day 5).

Single source of truth for classifying columns in a result set as
numeric, categorical, date, ID, or text. Previously three separate
``_get_numeric_columns`` / ``_get_categorical_columns`` implementations
across insight_detector.py, statistics.py, and comparisons.py gave
subtly different answers — only insight_detector honoured the Day 2c
smart-ID exclusion, so statistics and comparisons happily ran analytics
on ``policy_id`` and produced the 18865% trend that motivated the Phase
1 remediation.

All analysis engines now delegate to ``classify_columns(data)``. The
existing per-engine helpers stay for call-site compatibility but
become thin wrappers over this module.

Also provides ``sanitize_numeric`` for NaN/Infinity scrubbing, used by
every statistics computation so those values never reach the JSON
serializer downstream.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List

from app.core.logging_config import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------


class ColumnType(str, Enum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATE = "date"
    ID = "id"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass
class ClassifiedColumn:
    name: str
    type: ColumnType
    cardinality: int
    sample_size: int
    # True when the column was flagged as ID by heuristic (name + all-unique).
    is_id_heuristic: bool = False


# --------------------------------------------------------------------------
# Heuristic constants — kept in sync with insight_detector's originals
# --------------------------------------------------------------------------

_ID_COLUMN_PATTERN = re.compile(r"(?i)(^id$|_id$|_pk$|^pk_)")
_DATE_NAME_KEYWORDS = (
    "date",
    "time",
    "timestamp",
    "created",
    "updated",
    "month",
    "year",
    "day",
)
_CATEGORICAL_CARDINALITY_RATIO = 0.3  # < 30% unique → categorical
_CARDINALITY_SAMPLE_SIZE = 100


# --------------------------------------------------------------------------
# Primitive type checks
# --------------------------------------------------------------------------


def _is_numeric(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _is_date_value(val: Any) -> bool:
    return isinstance(val, (datetime, date))


def _name_suggests_date(col_name: str) -> bool:
    col_lower = col_name.lower()
    return any(keyword in col_lower for keyword in _DATE_NAME_KEYWORDS)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def classify_columns(data: List[Dict[str, Any]]) -> Dict[str, ClassifiedColumn]:
    """
    Classify every column in ``data`` exactly once and return a dict of
    ``column_name → ClassifiedColumn``. Uses the first 100 rows for
    cardinality sampling — cheap and accurate enough for the 10K-row
    ceiling the agent enforces.

    Precedence (first match wins):
      1. DATE  — value is datetime/date or name matches date keywords
      2. ID    — numeric + name matches ID pattern + all-unique in sample
                 (only when FIX_SMART_ID_EXCLUSION is enabled, per Day 2c)
      3. NUMERIC — value is int/float (not bool)
      4. CATEGORICAL — low cardinality (<30% unique, >1 unique)
      5. TEXT — everything else
    """
    if not data:
        return {}

    sample = data[:_CARDINALITY_SAMPLE_SIZE]
    sample_size = len(sample)
    first_row = data[0]

    result: Dict[str, ClassifiedColumn] = {}
    for col, sample_val in first_row.items():
        unique_values: set = set()
        for row in sample:
            v = row.get(col)
            if v is not None:
                try:
                    unique_values.add(v)
                except TypeError:
                    # Unhashable (dict/list) — skip cardinality counting
                    pass
        cardinality = len(unique_values)

        col_type, is_id = _classify_one(
            col, sample_val, cardinality, sample_size, sample
        )
        result[col] = ClassifiedColumn(
            name=col,
            type=col_type,
            cardinality=cardinality,
            sample_size=sample_size,
            is_id_heuristic=is_id,
        )

    return result


def _classify_one(
    col: str,
    sample_val: Any,
    cardinality: int,
    sample_size: int,
    sample: List[Dict[str, Any]],
) -> tuple:
    # Date wins over everything
    if _is_date_value(sample_val) or _name_suggests_date(col):
        return ColumnType.DATE, False

    # ID detection — numeric + name-pattern + all-unique in sample.
    # (Flag amnesty 2026-05-12: FIX_SMART_ID_EXCLUSION rollback removed.)
    if _is_numeric(sample_val):
        if (
            _ID_COLUMN_PATTERN.search(col)
            and cardinality == sample_size
            and sample_size > 0
        ):
            return ColumnType.ID, True
        return ColumnType.NUMERIC, False

    # Categorical: low-cardinality strings (or other non-numeric)
    # Use the SAMPLE size as denominator (cardinality sampled over the
    # first 100 rows), matching the previous comparisons / insight_detector
    # heuristic. Guard against sample_size=1 division-by-zero edge cases.
    if cardinality > 1 and sample_size > 0:
        if cardinality < max(2, sample_size * _CATEGORICAL_CARDINALITY_RATIO):
            return ColumnType.CATEGORICAL, False

    # Fall through: text / unknown
    if sample_val is None:
        return ColumnType.UNKNOWN, False
    return ColumnType.TEXT, False


# --------------------------------------------------------------------------
# Convenience queries (used by the per-engine wrappers)
# --------------------------------------------------------------------------


def numeric_columns(data: List[Dict[str, Any]]) -> List[str]:
    """Return names of columns classified as NUMERIC (excludes IDs)."""
    return [
        c.name
        for c in classify_columns(data).values()
        if c.type is ColumnType.NUMERIC
    ]


def categorical_columns(data: List[Dict[str, Any]]) -> List[str]:
    """Return names of columns classified as CATEGORICAL."""
    return [
        c.name
        for c in classify_columns(data).values()
        if c.type is ColumnType.CATEGORICAL
    ]


def date_columns(data: List[Dict[str, Any]]) -> List[str]:
    """Return names of columns classified as DATE."""
    return [
        c.name
        for c in classify_columns(data).values()
        if c.type is ColumnType.DATE
    ]


def id_columns(data: List[Dict[str, Any]]) -> List[str]:
    """Return names of columns classified as ID (primary-key / sequence)."""
    return [
        c.name
        for c in classify_columns(data).values()
        if c.type is ColumnType.ID
    ]


# --------------------------------------------------------------------------
# NaN / Infinity sanitization
# --------------------------------------------------------------------------


def sanitize_numeric(value: Any) -> Any:
    """
    Replace NaN and ±Infinity with None recursively. Applied at the
    source of every statistics computation so these values never reach
    the JSON serializer downstream (``json.dumps(allow_nan=False)``
    would raise; ``allow_nan=True`` produces invalid JSON the frontend
    can't parse).

    Walks dicts and lists; leaves other types unchanged.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: sanitize_numeric(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_numeric(v) for v in value]
    if isinstance(value, tuple):
        return tuple(sanitize_numeric(v) for v in value)
    return value
