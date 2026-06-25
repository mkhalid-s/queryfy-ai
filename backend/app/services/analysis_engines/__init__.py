"""
Analysis Engines - Statistical and Pattern Detection Modules

Core analytical capabilities for the ReAct agent's analysis tools.
"""

from .chart_intelligence import prepare_chart_data, recommend_chart
from .comparisons import compare_periods
from .data_quality import assess_data_quality
from .insight_detector import detect_insights
from .statistics import compute_statistics
from .validator import (
    log_analysis_tool_output,
    validate_chart_spec,
    validate_insights_accuracy,
)

__all__ = [
    "detect_insights",
    "compute_statistics",
    "assess_data_quality",
    "compare_periods",
    "recommend_chart",
    "prepare_chart_data",
    "validate_insights_accuracy",
    "validate_chart_spec",
    "log_analysis_tool_output",
]
