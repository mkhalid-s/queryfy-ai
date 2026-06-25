"""
Cassandra Banking Benchmark Dataset

Hand-crafted NL-to-CQL benchmark cases targeting the ``banking_db``
keyspace. Covers Cassandra-specific query patterns:

- Partition-key filtering (required for efficient Cassandra queries)
- Clustering order and range scans
- Secondary index lookups
- Collection column access (list, map)
- ALLOW FILTERING usage

Requires the ``banking_db`` keyspace from ``data/cassandra-init/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.core.types import BenchmarkCase, DatabaseCategory, Difficulty

logger = logging.getLogger(__name__)

# Schema context extracted from the CQL init script
_SCHEMA = """
CREATE TABLE customers (
    customer_id uuid,
    region text,        -- partition key: NORTHEAST, WEST, SOUTH, MIDWEST
    first_name text, last_name text, email text, phone text,
    date_of_birth date, ssn_last_four text,
    address text, city text, state text, zip_code text, country text,
    credit_score int, customer_since date, customer_tier text,
    is_active boolean, created_at timestamp, updated_at timestamp,
    PRIMARY KEY ((region), customer_id)
);
-- Indexes: email, customer_tier

CREATE TABLE accounts (
    account_id uuid,
    customer_id uuid,   -- partition key
    account_number text, account_type text, currency text,
    balance decimal, available_balance decimal, credit_limit decimal,
    interest_rate decimal, opened_date date, status text, branch_id text,
    last_transaction_date timestamp,
    created_at timestamp, updated_at timestamp,
    PRIMARY KEY ((customer_id), account_id)
);
-- Indexes: account_type, status

CREATE TABLE transactions (
    account_id uuid,
    transaction_month text,  -- composite partition: (account_id, transaction_month)
    transaction_id uuid,
    transaction_date timestamp,  -- clustering key DESC
    transaction_type text, amount decimal, currency text,
    description text, category text, merchant_name text,
    merchant_category text, reference_number text,
    balance_after decimal, status text, channel text, location text,
    PRIMARY KEY ((account_id, transaction_month), transaction_date, transaction_id)
) WITH CLUSTERING ORDER BY (transaction_date DESC, transaction_id ASC);
-- Indexes: transaction_type, category

CREATE TABLE loans (
    loan_id uuid,
    customer_id uuid,   -- partition key
    loan_type text, principal_amount decimal, interest_rate decimal,
    term_months int, monthly_payment decimal, total_interest decimal,
    remaining_balance decimal, start_date date, end_date date,
    status text, collateral_type text, collateral_value decimal,
    loan_officer_id text, branch_id text,
    created_at timestamp, updated_at timestamp,
    PRIMARY KEY ((customer_id), loan_id)
);
-- Indexes: loan_type, status

CREATE TABLE branches (
    branch_id text PRIMARY KEY,
    branch_name text, branch_type text,
    address text, city text, state text, zip_code text, country text,
    phone text, manager_name text, employee_count int,
    opened_date date, is_active boolean,
    services list<text>,
    operating_hours map<text, text>
);

CREATE TABLE cards (
    card_id uuid,
    customer_id uuid,   -- partition key
    account_id uuid, card_number_masked text, card_type text,
    card_brand text, credit_limit decimal, current_balance decimal,
    expiry_date date, status text, issued_date date,
    reward_points int, annual_fee decimal,
    PRIMARY KEY ((customer_id), card_id)
);
"""

# NL-to-CQL benchmark cases
_CASES: List[dict] = [
    # --- SIMPLE: Direct partition-key lookups ---
    {
        "id": "cass_001",
        "nl": "Show all customers in the NORTHEAST region.",
        "cql": "SELECT * FROM customers WHERE region = 'NORTHEAST'",
        "difficulty": "simple",
    },
    {
        "id": "cass_002",
        "nl": "List all branches.",
        "cql": "SELECT * FROM branches",
        "difficulty": "simple",
    },
    {
        "id": "cass_003",
        "nl": "Get the branch details for branch BR003.",
        "cql": "SELECT * FROM branches WHERE branch_id = 'BR003'",
        "difficulty": "simple",
    },
    {
        "id": "cass_004",
        "nl": "Show all customers in the WEST region.",
        "cql": "SELECT * FROM customers WHERE region = 'WEST'",
        "difficulty": "simple",
    },
    {
        "id": "cass_005",
        "nl": "What are the names and cities of all branches?",
        "cql": "SELECT branch_name, city FROM branches",
        "difficulty": "simple",
    },
    {
        "id": "cass_006",
        "nl": "Show the branch name and manager for branch BR001.",
        "cql": "SELECT branch_name, manager_name FROM branches WHERE branch_id = 'BR001'",
        "difficulty": "simple",
    },
    {
        "id": "cass_007",
        "nl": "List all customers from the SOUTH region.",
        "cql": "SELECT * FROM customers WHERE region = 'SOUTH'",
        "difficulty": "simple",
    },
    {
        "id": "cass_008",
        "nl": "How many employees does each branch have?",
        "cql": "SELECT branch_name, employee_count FROM branches",
        "difficulty": "simple",
    },
    # --- MODERATE: Secondary index, column selection, ALLOW FILTERING ---
    {
        "id": "cass_009",
        "nl": "Find all PLATINUM tier customers.",
        "cql": "SELECT * FROM customers WHERE customer_tier = 'PLATINUM' ALLOW FILTERING",
        "difficulty": "moderate",
    },
    {
        "id": "cass_010",
        "nl": "Find the customer with email 'james.anderson@email.com'.",
        "cql": "SELECT * FROM customers WHERE email = 'james.anderson@email.com' ALLOW FILTERING",
        "difficulty": "moderate",
    },
    {
        "id": "cass_011",
        "nl": "Show the names, email, and credit score of customers in the MIDWEST region.",
        "cql": "SELECT first_name, last_name, email, credit_score FROM customers WHERE region = 'MIDWEST'",
        "difficulty": "moderate",
    },
    {
        "id": "cass_012",
        "nl": "List all active branches with their services.",
        "cql": "SELECT branch_name, services FROM branches WHERE is_active = true ALLOW FILTERING",
        "difficulty": "moderate",
    },
    {
        "id": "cass_013",
        "nl": "Find all branches in California.",
        "cql": "SELECT * FROM branches WHERE state = 'CA' ALLOW FILTERING",
        "difficulty": "moderate",
    },
    {
        "id": "cass_014",
        "nl": "What are the operating hours of the Downtown Main Branch?",
        "cql": "SELECT operating_hours FROM branches WHERE branch_id = 'BR001'",
        "difficulty": "moderate",
    },
    {
        "id": "cass_015",
        "nl": "Show branches that have the 'Investments' service.",
        "cql": "SELECT branch_name, city FROM branches WHERE services CONTAINS 'Investments' ALLOW FILTERING",
        "difficulty": "moderate",
    },
    {
        "id": "cass_016",
        "nl": "Find all GOLD tier customers in the NORTHEAST region.",
        "cql": "SELECT * FROM customers WHERE region = 'NORTHEAST' AND customer_tier = 'GOLD' ALLOW FILTERING",
        "difficulty": "moderate",
    },
    {
        "id": "cass_017",
        "nl": "List all active customers in the WEST region with their credit scores.",
        "cql": "SELECT first_name, last_name, credit_score FROM customers WHERE region = 'WEST' AND is_active = true ALLOW FILTERING",
        "difficulty": "moderate",
    },
    {
        "id": "cass_018",
        "nl": "Find branches with more than 30 employees.",
        "cql": "SELECT branch_name, employee_count FROM branches WHERE employee_count > 30 ALLOW FILTERING",
        "difficulty": "moderate",
    },
    # --- CHALLENGING: Multi-condition, collection queries, LIMIT ---
    {
        "id": "cass_019",
        "nl": "Show 5 customers from the SOUTH region with their credit scores.",
        "cql": "SELECT first_name, last_name, credit_score FROM customers WHERE region = 'SOUTH' LIMIT 5",
        "difficulty": "challenging",
        "evidence": "LIMIT caps the number of rows returned from a partition query.",
    },
    {
        "id": "cass_020",
        "nl": "List all branches that offer both 'Loans' and 'Digital Banking' services.",
        "cql": "SELECT branch_name, services FROM branches WHERE services CONTAINS 'Loans' AND services CONTAINS 'Digital Banking' ALLOW FILTERING",
        "difficulty": "challenging",
    },
    {
        "id": "cass_021",
        "nl": "Count the number of customers in each region.",
        "cql": "SELECT region, COUNT(*) FROM customers GROUP BY region",
        "difficulty": "challenging",
        "evidence": "Cassandra supports GROUP BY on partition key columns.",
    },
    {
        "id": "cass_022",
        "nl": "Show the Saturday operating hours for all branches.",
        "cql": "SELECT branch_name, operating_hours['Sat'] FROM branches",
        "difficulty": "challenging",
        "evidence": "Cassandra supports accessing map values by key using bracket notation.",
    },
    {
        "id": "cass_023",
        "nl": "Find all Full Service branches that are active and located in a specific state.",
        "cql": "SELECT branch_name, city, state FROM branches WHERE branch_type = 'Full Service' AND is_active = true ALLOW FILTERING",
        "difficulty": "challenging",
    },
    {
        "id": "cass_024",
        "nl": "Find customers in the NORTHEAST region who have been customers since before 2015.",
        "cql": "SELECT first_name, last_name, customer_since FROM customers WHERE region = 'NORTHEAST' AND customer_since < '2015-01-01' ALLOW FILTERING",
        "difficulty": "challenging",
    },
    {
        "id": "cass_025",
        "nl": "Find customers in the WEST region with a credit score above 750.",
        "cql": "SELECT first_name, last_name, credit_score FROM customers WHERE region = 'WEST' AND credit_score > 750 ALLOW FILTERING",
        "difficulty": "challenging",
        "evidence": "Filtering on non-partition, non-clustering columns requires ALLOW FILTERING.",
    },
]


class CassandraBankingDataset(BenchmarkDataset):
    """Hand-crafted NL-to-CQL benchmark for the banking_db keyspace."""

    NAME = "cassandra-banking"
    DESCRIPTION = "25 NL-to-CQL questions on a banking schema (Cassandra)"
    DB_TYPE = DatabaseCategory.NOSQL_WIDE_COLUMN
    SOURCE_URL = ""  # bundled in-repo
    TOTAL_CASES = 25

    def load(self, data_dir: Path) -> List[BenchmarkCase]:
        """Load the hand-crafted CQL benchmark cases."""
        cases = []
        for item in _CASES:
            difficulty_map = {
                "simple": Difficulty.SIMPLE,
                "moderate": Difficulty.MODERATE,
                "challenging": Difficulty.CHALLENGING,
            }
            cases.append(
                BenchmarkCase(
                    case_id=item["id"],
                    natural_language=item["nl"],
                    gold_query=item["cql"],
                    db_name="banking_db",
                    db_type=DatabaseCategory.NOSQL_WIDE_COLUMN,
                    difficulty=difficulty_map.get(item["difficulty"], Difficulty.SIMPLE),
                    evidence=item.get("evidence"),
                    schema_context=_SCHEMA,
                )
            )
        logger.info("Loaded %d Cassandra banking benchmark cases", len(cases))
        return cases

    def download(self, data_dir: Path) -> None:
        """No download needed — cases are bundled in this module."""
        logger.info("Cassandra banking dataset is bundled (no download required)")
