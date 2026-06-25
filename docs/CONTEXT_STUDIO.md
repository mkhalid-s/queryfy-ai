# Context Studio

Context Studio is nl2sql-app's metadata management system. It helps the AI understand your data by letting you define business terms, add column descriptions, and save query patterns -- making every query more accurate and relevant to your domain.

---

## Contents

- [Overview](#overview)
- [Business Terms](#business-terms)
- [Schema Context](#schema-context)
- [Query Patterns](#query-patterns)
- [Having Better Conversations](#having-better-conversations)
- [UI Reference](#ui-reference)

---

## Overview

When you ask a question like "show me top customers," the AI only sees raw column names and data types. It has no idea that "top" means "by revenue," that "revenue" actually means `gross_sales - refunds`, or that your `tier` column holds values like `bronze`, `silver`, `gold`, and `platinum`. Without that context, the AI guesses -- and guesses are often wrong.

Context Studio bridges this gap. It gives you a place to teach the AI about your data: what your tables represent, what your columns mean in business terms, and how your organization talks about its data. The result is dramatically better SQL generation -- queries that reflect your actual business logic instead of generic assumptions.

Here is a quick example of the difference context makes:

| Question | Without Context | With Context |
|----------|-----------------|--------------|
| "Show top customers" | `SELECT * FROM customers LIMIT 10` | `SELECT * FROM customers ORDER BY revenue DESC LIMIT 10` |
| "Active users this month" | `SELECT * WHERE status = 'active'` | `SELECT * WHERE status = 'active' AND last_login >= DATE_TRUNC('month', NOW())` |
| "Revenue YTD" | `SELECT SUM(amount) FROM orders` | `SELECT SUM(gross_sales - refunds) FROM orders WHERE order_date >= DATE_TRUNC('year', NOW())` |

Providing semantic metadata improves text-to-SQL accuracy by roughly 27% and prevents about 42% of silent query failures -- cases where the SQL runs without error but returns the wrong answer.

---

## Business Terms

Business terms are definitions that teach the AI your organization's vocabulary. When someone asks about "churn" or "ARR" or "VIP customers," Context Studio ensures the AI translates those terms into the correct SQL expressions.

### Adding a Term

To add a business term:

1. Open **Context Studio** from the header.
2. Go to the **Terms** tab.
3. Click **Add Term**.
4. Fill in the fields:
   - **Term** -- The word or phrase your team uses (e.g., "VIP Customer").
   - **Definition** -- A plain-language explanation (e.g., "Customer with platinum tier or annual revenue over $500,000").
   - **SQL Expression** -- The corresponding SQL (e.g., `tier = 'platinum' OR annual_revenue > 500000`).
   - **Scope** -- Where this term applies (see below).

### Scoping

Business terms are resolved in priority order, so more specific definitions override general ones:

| Scope | Purpose | Example |
|-------|---------|---------|
| **Session** | Temporary overrides for your current session | Testing a new definition of "active user" |
| **Tenant** | Company-specific definitions (multi-tenant deployments) | Your company's unique revenue formula |
| **Database** | Definitions tied to a specific connected database | Schema-specific column mappings |
| **Global** | Universal patterns available to everyone | Common date shortcuts like YTD, MTD |

If the same term is defined at multiple scopes, the most specific scope wins. A session-level definition of "revenue" overrides a global one.

### Built-in Global Terms

Context Studio ships with several useful global terms out of the box:

| Term | What It Translates To |
|------|----------------------|
| YTD | `date_column >= DATE_TRUNC('year', NOW())` |
| MTD | `date_column >= DATE_TRUNC('month', NOW())` |
| Top 10 | `ORDER BY ... DESC LIMIT 10` |
| Last 30 days | `date_column >= NOW() - INTERVAL '30 days'` |
| Active | `status = 'active'` |
| Recent | `ORDER BY created_at DESC LIMIT 100` |

You can override any of these at a more specific scope if they don't match your usage.

### Tips for Good Term Definitions

| Do | Don't |
|----|-------|
| Define company-specific jargon ("ARR", "MRR", "churn rate") | Create terms for standard SQL keywords |
| Include the SQL expression so the AI can use it directly | Use vague definitions like "important customers" |
| Keep definitions concise and unambiguous | Duplicate the same term across multiple scopes without reason |

---

## Schema Context

Schema context lets you describe what your tables and columns actually represent in business terms. This is especially valuable for databases with cryptic column names, abbreviated identifiers, or columns whose meaning is not obvious from the name alone.

### Column Descriptions

For each column, you can provide:

- **Description** -- What the column represents in plain language.
- **Sample Values** -- Representative values that help the AI understand the data format and range.

**Example:**

| Table | Column | Description | Sample Values |
|-------|--------|-------------|---------------|
| `customers` | `tier` | Customer loyalty level | bronze, silver, gold, platinum |
| `orders` | `amt_net` | Net order amount after discounts and refunds | 150.00, 2340.50, 89.99 |
| `products` | `cat_id` | Foreign key to product_categories table | 1, 5, 12 |

### How Schema Context Affects SQL Generation

When you describe a column, that description is injected into the AI's prompt whenever the column's table is relevant to a query. This means:

- The AI knows that `tier` holds loyalty levels, not numerical tiers.
- It understands that `amt_net` is a dollar amount, not a count.
- It recognizes foreign key relationships and can generate proper JOINs.

### Bulk Descriptions

If you have many columns to describe, you can add descriptions in bulk rather than one at a time. This is useful when onboarding a new database or when you have documentation in a spreadsheet.

### Tips for Good Column Descriptions

| Do | Don't |
|----|-------|
| List all valid enum values ("bronze, silver, gold, platinum") | Describe obvious columns like `id` or `created_at` |
| Explain cryptic column names (`amt_net` = "Net order amount") | Duplicate descriptions that already exist as database comments |
| Note whether a field is calculated or stored | Leave foreign keys undescribed -- the AI needs to know relationships |
| Mention business rules ("negative values indicate refunds") | Write overly long descriptions -- a sentence or two is enough |

### Cross-Database Support

Context Studio works with any database type that QueryfyAI supports. The SQL expressions in your terms are interpreted in the context of your connected database:

| Database | Expression Style |
|----------|-----------------|
| PostgreSQL, MySQL, SQL Server, etc. | `status = 'active'` |
| MongoDB | `{"status": "active"}` |
| Cassandra (CQL) | `status = 'active'` |
| DynamoDB (PartiQL) | `status = 'active'` |

---

## Query Patterns

Query patterns are example question-and-SQL pairs that teach the AI by example. This is sometimes called "few-shot learning" -- by showing the AI what good queries look like for your data, it learns to generate similar ones.

### Adding a Pattern

1. Open **Context Studio** and go to the **Query Patterns** tab.
2. Click **Add Pattern**.
3. Provide:
   - **Question** -- A natural-language question (e.g., "Show top customers by revenue").
   - **SQL** -- The correct SQL for that question (e.g., `SELECT customer_id, SUM(amount) as total FROM orders GROUP BY customer_id ORDER BY total DESC LIMIT 10`).

### When Patterns Help Most

Query patterns are especially useful for:

- **Complex joins** -- If a common question requires joining three or four tables, an example saves the AI from guessing the join path.
- **Business-specific aggregations** -- When "revenue" means a specific calculation involving multiple columns.
- **Domain conventions** -- If your team always wants results ordered a certain way or filtered by a default date range.
- **Ambiguous questions** -- When a simple question like "show orders" should actually return a specific subset or aggregation.

### Tips for Good Patterns

- Focus on your most common questions first -- the ones your team asks every week.
- Make sure the SQL is correct and tested. The AI will learn from these examples, including any mistakes.
- Include a variety of question styles (aggregations, filters, joins, time-based queries) to give the AI a broad foundation.
- You don't need hundreds of patterns. Even 5-10 well-chosen examples make a meaningful difference.

---

## Having Better Conversations

QueryfyAI supports multi-turn conversations, meaning you can ask follow-up questions that build on previous results. This makes data exploration feel natural -- like talking to a colleague who remembers what you just discussed.

### How Follow-Ups Work

When you ask a follow-up question, the AI automatically has access to your recent conversation history (the last 5 queries by default). It uses this context to understand references like "those results," "that data," or "break it down further."

**Example conversation:**

```
You:  Show top 10 customers by revenue
AI:   [Returns top customers table + insights]

You:  Break that down by region
AI:   [Adds region grouping to the previous query]

You:  Now show the trend over time
AI:   [References customer data from the first query, adds time dimension]
```

### What Triggers a Follow-Up

The AI automatically detects follow-up questions when you use phrases like:

- "Break that down by..."
- "Filter those results where..."
- "Sort that by..."
- "What about last year?"
- "And also include..."
- "Now show..."
- "The same thing but for..."

Standalone questions like "Show all products" or "How many orders exist?" are treated as new queries.

### Starting Fresh

If the AI is carrying over context you don't want, you can start a new conversation:

- Click **New Conversation** in the conversation controls area.
- This clears the context window so your next question is treated as a fresh start.

The turn counter in the UI shows where you are in a conversation (Turn 1, Turn 2, etc.), so you always know how much context the AI is working with.

### Tips for Effective Queries

**Be specific about what you want:**

| Instead of... | Try... |
|---------------|--------|
| "Show me data" | "Show me all customers who made purchases last month" |
| "Show orders" | "Show orders over $1,000 from the last 30 days" |
| "Revenue" | "Total revenue by month for this year" |

**Build incrementally.** Start with a broad question, then refine:

1. "Show Q1 revenue by region"
2. "Compare that to Q1 last year"
3. "Which region grew the most?"
4. "Why did the West region decline?"

**Use natural language for follow-ups.** You don't need to repeat the full context:

- "Filter by status = active" works.
- "Now only show the top 5" works.
- "Add product category to that breakdown" works.

**Know when to start fresh.** If you've been refining a query for many turns and the results start feeling off, hit **New Conversation** and restate your question clearly. Long conversations (20+ turns) can accumulate context that confuses things.

### Follow-Up Suggestions

After each response, the AI may suggest follow-up questions based on what it found in your data. These suggestions are ranked by relevance:

- **High priority** -- Significant patterns or anomalies worth investigating.
- **Medium priority** -- Useful comparisons or breakdowns.
- **Low priority** -- Additional perspectives that might be interesting.

Click any suggestion to send it as your next question.

---

## UI Reference

### Opening Context Studio

Click the **Context Studio** button in the application header. The Context Studio panel slides in from the right side of the screen.

### Tabs

Context Studio is organized into tabs:

| Tab | What It Contains |
|-----|-----------------|
| **Terms** | Business term definitions. Add, edit, and delete terms with their SQL expressions and scopes. |
| **Columns** | Column descriptions and sample values. Browse your schema and add context to individual columns. |
| **Query Patterns** | Example question-SQL pairs for few-shot learning. Add patterns that teach the AI your team's common queries. |

### Key Interactions

**Adding entries:**
Each tab has an **Add** button. Fill in the form fields and save. New entries take effect immediately -- the next query you run will use the updated context.

**Editing entries:**
Click any existing entry to edit it. Changes are saved when you confirm.

**Deleting entries:**
Use the delete action on any entry. Deleted entries are removed immediately.

**Automatic injection:**
You don't need to do anything special to use your Context Studio data. When you ask a question, the system automatically:
1. Finds business terms that match your question.
2. Retrieves column descriptions for relevant tables.
3. Includes similar query patterns as examples.
4. Injects all of this into the AI's prompt before generating SQL.

### Statistics

Context Studio shows summary statistics for your dictionary: how many terms, column descriptions, and patterns you've defined. This helps you gauge how much context the AI has to work with.

### Import and Export

You can bulk-import and export your Context Studio data:

- **Export** -- Download your terms, column descriptions, and patterns as JSON or CSV. Useful for backup or sharing across environments.
- **Import** -- Upload a JSON or CSV file to add entries in bulk. The system previews what will be imported before confirming.

**JSON format example:**

```json
{
  "tables": [
    {
      "name": "customers",
      "description": "Customer master data",
      "columns": [
        {"name": "id", "description": "Primary key"},
        {"name": "status", "description": "active, inactive, suspended"}
      ]
    }
  ],
  "glossary": [
    {"term": "Active Customer", "definition": "Customer with order in last 90 days"}
  ]
}
```

### Best Practices for Getting Started

1. **Start with your most-queried tables.** You don't need to describe every column in every table. Focus on the tables your team asks about most often.
2. **Define your organization's jargon.** If people say "churn," "ARR," "active user," or "VIP" -- define those terms first.
3. **Add 5-10 query patterns.** Pick your team's most common questions and provide the correct SQL. This gives the AI a strong foundation.
4. **Iterate as you go.** When a query comes back wrong, check whether adding a term or column description would fix it. Context Studio is meant to grow over time.
5. **Export regularly.** Back up your Context Studio data so you can restore it if needed or share it across environments.
