# Analysis Tools Guide

**Version:** 1.3.0
**Last Updated:** 2026-02-18

Reference for the 8 analysis tools available to the ReAct agent. For implementation details, see the source in `backend/app/services/tools/` and `backend/app/services/analysis_engines/`.

---

## Table of Contents

- [Overview](#overview)
- [Tool Reference](#tool-reference)
- [Tool Chaining and Workflows](#tool-chaining-and-workflows)
- [Best Practices](#best-practices)
- [LLM-Assisted Analysis](#llm-assisted-analysis)

---

## Overview

The ReAct agent has **8 specialized analysis tools** that transform raw data into actionable insights.

| Category | Tools | Purpose |
|----------|-------|---------|
| **Insight Detection** | `detect_insights` | Find patterns, trends, anomalies |
| **Statistical Analysis** | `analyze_statistics` | Compute advanced statistics |
| **Quality Assessment** | `check_data_quality` | Assess data completeness |
| **Temporal Comparison** | `compare_periods` | MoM, YoY, QoQ comparisons |
| **Guidance** | `suggest_followups` | Generate next questions |
| **Visualization** | `recommend_chart`, `prepare_chart_data`, `annotate_chart` | Intelligent charting |

**Always prefer `execute_and_analyze`** for analyst mode -- it combines query execution with all analysis steps in a single call. Use individual tools only for specialized deep-dive or custom chaining workflows.

---

## Tool Reference

### detect_insights

Find patterns, trends, anomalies, and risks in query results.

**Parameters:** `data` (JSON string), `analysis_types` (list: `"concentration"`, `"trend"`, `"anomaly"`, `"comparison"`, `"all"`)

**Analysis types:**

| Type | Detects | Severity Thresholds |
|------|---------|-------------------|
| `concentration` | Pareto/top-N concentration risk | High: top 3 > 50%, Medium: top 5 > 60%, Low: top 10 > 70% |
| `trend` | Linear trends, growth rates, acceleration | Strong trend: r_squared > 0.5 |
| `anomaly` | Outliers via z-score | Outlier: z > 3, Extreme: z > 4 |
| `comparison` | Segment top/bottom performers | Compares each segment vs average |

**Output fields per insight:** `type`, `severity`, `title`, `description`, `metrics`, `recommendations`

---

### analyze_statistics

Compute advanced statistics beyond basic aggregations.

**Parameters:** `data` (JSON string), `columns` (optional list, defaults to all numeric)

**Computed metrics:**

| Metric | Meaning |
|--------|---------|
| `mean`, `median` | Central tendency (median is robust to outliers) |
| `std_dev`, `iqr` | Variability / spread |
| `p10` - `p99` | Percentiles for tail analysis |
| `skewness` | Distribution shape (`-1..1` symmetric, `>1` right-skewed) |
| `gini` | Inequality (`0` = equal, `1` = maximal inequality) |

---

### check_data_quality

Assess data quality and completeness of query results.

**Parameters:** `data` (JSON string)

**Quality score formula:** `completeness * 0.4 + (100 - duplicate_pct) * 0.3 + (100 - outlier_pct) * 0.2 + consistency * 0.1`

| Score | Severity | Action |
|-------|----------|--------|
| 90-100 | None | Proceed with confidence |
| 70-89 | Low | Note issues in report |
| 50-69 | Medium | Investigate before analysis |
| 0-49 | High | Data quality problems |

**Output fields:** `overall_score`, `completeness`, `duplicate_count`, `outlier_count`, `issues[]`, `column_quality{}`

---

### compare_periods

Compare time periods or segments to show change over time.

**Parameters:** `current_data` (JSON string), `comparison_type` (`MoM` | `YoY` | `QoQ` | `WoW` | `segment_vs_avg`), `previous_data` (optional), `original_sql` (optional)

| Change % | Significance |
|----------|-------------|
| < 5% | not_significant |
| 5-15% | moderate |
| 15-30% | significant |
| > 30% | highly_significant |

**Output fields per comparison:** `metric`, `current`, `previous`, `absolute_change`, `percent_change`, `interpretation`, `significance`

---

### suggest_followups

Generate smart follow-up questions based on detected insights.

**Parameters:** `insights` (JSON string from detect_insights), `query_context` (original question)

**Suggestion categories:**

| Category | Purpose |
|----------|---------|
| `drill_down` | Deeper analysis of a specific finding |
| `comparison` | Temporal or segment comparison |
| `investigation` | Root cause analysis |
| `exploration` | Adjacent/related analysis |

**Output fields per suggestion:** `question`, `rationale`, `priority`, `category`

---

### recommend_chart

Recommend the optimal chart type for the data.

**Parameters:** `data` (JSON string), `insights` (optional), `analysis_goal` (`show_trend` | `compare_segments` | `show_distribution` | `show_composition` | `show_relationship` | `show_single_value`)

**Selection logic:**

```
Time series         -> line / area
High cardinality    -> bar (top N) + "Other"
Part-to-whole (<=8) -> pie
Part-to-whole (>8)  -> treemap
Comparison          -> bar / horizontal_bar
Correlation         -> scatter
Single value        -> gauge / KPI card
```

**Output fields:** `recommended_chart`, `rationale`, `config` (axis mapping + options), `alternatives[]`, `warnings[]`

---

### prepare_chart_data

Transform raw data for visualization (aggregation, grouping, outlier handling).

**Parameters:** `data` (JSON string), `chart_type` (`line` | `bar` | `pie` | `scatter` | `area`), `max_points` (default 50), `handle_outliers` (boolean)

**Transformations applied:**
- **Auto-aggregation:** 365 daily -> 52 weekly, 180 daily -> 26 biweekly, 90 daily -> 12 monthly
- **Top-N grouping:** 100 categories -> top 20 + "Other (80 items)"
- **Outlier capping:** Values above P95 are capped with annotation

**Output fields:** `transformed_data[]`, `transformations_applied[]`, `metadata` (original/final point counts)

---

### annotate_chart

Add intelligent annotations (trend lines, benchmarks, outlier markers, callouts) to charts.

**Parameters:** `chart_spec` (JSON string), `insights` (optional), `statistics` (optional), `comparisons` (optional)

**Annotation types:** `trend_line` (slope, equation), `benchmark` (average/target lines), `outlier` (marked points), `callout` (labeled events)

**Output fields:** `chart_type`, `title`, `annotations[]`

---

## Tool Chaining and Workflows

### Recommended Pipeline (use `execute_and_analyze`)

```
execute_and_analyze(sql, limit)
  -> detect_insights
  -> analyze_statistics
  -> check_data_quality
  -> recommend_chart
  -> enhance_insights_with_llm (for aggregates < 100 rows)
```

All steps run in a single tool call. The result contains: `insights`, `statistics`, `quality`, `chart_recommendation`.

### Custom Deep-Dive (individual tools)

```
1. execute_sql
2. check_data_quality  (validate data)
3. detect_insights     (find patterns)
4. analyze_statistics  (deep dive)
5. suggest_followups   (guide user)
```

### Visualization Pipeline (individual tools)

```
1. detect_insights     (inform chart choice)
2. recommend_chart     (pick chart type)
3. prepare_chart_data  (transform for rendering)
4. annotate_chart      (add context)
```

---

## Best Practices

1. **Use `execute_and_analyze` by default** -- it runs all analysis in one call and includes LLM enhancement for aggregate queries.
2. **Check data quality before strong claims** -- scores below 70 warrant caveats.
3. **Sample large datasets** -- for > 20,000 rows, analyze a representative sample.
4. **Handle errors gracefully** -- all tools return structured errors; fall back to partial results rather than failing entirely.

---

## LLM-Assisted Analysis

The analysis pipeline includes an LLM enhancement layer that adds business context to statistical insights. When `execute_and_analyze` processes an aggregate query with fewer than 100 rows, it sends the result data and pre-computed statistics to the configured LLM for interpretation. The LLM returns structured insights with specific category names, quantitative comparisons, and actionable recommendations that go beyond what rule-based analysis can provide.

This enhancement is automatic and transparent -- it runs as step 5 in the `execute_and_analyze` pipeline. If the LLM call fails, the system falls back gracefully to statistical insights only.

**Implementation:** `backend/app/services/tools/query_tools.py` -- see `enhance_insights_with_llm()`.

### How it Works

1. **Query classification** -- SQL is checked for aggregate keywords (`GROUP BY`, `COUNT(`, `SUM(`, window functions, MongoDB/Cassandra equivalents).
2. **Data preparation** -- First 50 rows sent to LLM with pre-computed statistics, column names, and query context. Strings truncated to 100 chars for token efficiency.
3. **LLM call** -- Prompt requests 3-4 structured insights as JSON. Temperature 0.3, max 4000 tokens. Supports OAuth Gateway and LiteLLM providers.
4. **Response parsing** -- `extract_json_from_llm_response()` handles varied LLM output formats. Falls back to wrapping raw text as a single insight.
5. **Merge** -- LLM insights prepended to statistical insights. Output sanitized for JSON serialization.

### Configuration

Uses the same LLM config as the ReAct agent (via `ToolContext.llm_config`). Activates automatically when:

- LLM config is available in the tool context
- Result set has <= 100 rows
- SQL contains aggregate keywords

Key parameters: temperature 0.3, max tokens 4000, supports all LiteLLM-compatible providers.

### Extending Analysis

- **Change the prompt** -- Edit the prompt in `enhance_insights_with_llm()`. It defines insight categories and the required JSON output schema.
- **Adjust query detection** -- Add SQL dialect keywords to the `is_aggregate` keyword list.
- **Change the row threshold** -- The 100-row limit is at the top of `enhance_insights_with_llm()`.
- **Customize output structure** -- JSON schema in the prompt must match the frontend `InsightCard` component: `type`, `severity`, `title`, `description`, `recommendations`.

---

## Related Documentation

- [Tool Development](./TOOL_DEVELOPMENT.md) - Creating custom tools
- [Agent Reference](./AGENT_REFERENCE.md) - API reference and troubleshooting
