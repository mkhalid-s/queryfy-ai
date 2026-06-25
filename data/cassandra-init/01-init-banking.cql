-- ============================================================================
-- FINANCE/BANKING CASSANDRA INITIALIZATION SCRIPT
-- Comprehensive mock data for banking domain
-- ============================================================================

-- Create keyspace
CREATE KEYSPACE IF NOT EXISTS banking_db
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE banking_db;

-- ============================================================================
-- CUSTOMERS TABLE
-- Partitioned by region for distributed queries
-- ============================================================================
CREATE TABLE IF NOT EXISTS customers (
    customer_id uuid,
    region text,
    first_name text,
    last_name text,
    email text,
    phone text,
    date_of_birth date,
    ssn_last_four text,
    address text,
    city text,
    state text,
    zip_code text,
    country text,
    credit_score int,
    customer_since date,
    customer_tier text,
    is_active boolean,
    created_at timestamp,
    updated_at timestamp,
    PRIMARY KEY ((region), customer_id)
);

CREATE INDEX IF NOT EXISTS idx_customers_email ON customers (email);
CREATE INDEX IF NOT EXISTS idx_customers_tier ON customers (customer_tier);

-- ============================================================================
-- ACCOUNTS TABLE
-- Partitioned by customer_id for efficient customer lookups
-- ============================================================================
CREATE TABLE IF NOT EXISTS accounts (
    account_id uuid,
    customer_id uuid,
    account_number text,
    account_type text,
    currency text,
    balance decimal,
    available_balance decimal,
    credit_limit decimal,
    interest_rate decimal,
    opened_date date,
    status text,
    branch_id text,
    last_transaction_date timestamp,
    created_at timestamp,
    updated_at timestamp,
    PRIMARY KEY ((customer_id), account_id)
);

CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts (account_type);
CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts (status);

-- ============================================================================
-- TRANSACTIONS TABLE
-- Time-series data partitioned by account and month
-- ============================================================================
CREATE TABLE IF NOT EXISTS transactions (
    account_id uuid,
    transaction_month text,
    transaction_id uuid,
    transaction_date timestamp,
    transaction_type text,
    amount decimal,
    currency text,
    description text,
    category text,
    merchant_name text,
    merchant_category text,
    reference_number text,
    balance_after decimal,
    status text,
    channel text,
    location text,
    PRIMARY KEY ((account_id, transaction_month), transaction_date, transaction_id)
) WITH CLUSTERING ORDER BY (transaction_date DESC, transaction_id ASC);

CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions (transaction_type);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions (category);

-- ============================================================================
-- LOANS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS loans (
    loan_id uuid,
    customer_id uuid,
    loan_type text,
    principal_amount decimal,
    interest_rate decimal,
    term_months int,
    monthly_payment decimal,
    total_interest decimal,
    remaining_balance decimal,
    start_date date,
    end_date date,
    status text,
    collateral_type text,
    collateral_value decimal,
    loan_officer_id text,
    branch_id text,
    created_at timestamp,
    updated_at timestamp,
    PRIMARY KEY ((customer_id), loan_id)
);

CREATE INDEX IF NOT EXISTS idx_loans_type ON loans (loan_type);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans (status);

-- ============================================================================
-- BRANCHES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS branches (
    branch_id text PRIMARY KEY,
    branch_name text,
    branch_type text,
    address text,
    city text,
    state text,
    zip_code text,
    country text,
    phone text,
    manager_name text,
    employee_count int,
    opened_date date,
    is_active boolean,
    services list<text>,
    operating_hours map<text, text>
);

-- ============================================================================
-- CARDS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS cards (
    card_id uuid,
    customer_id uuid,
    account_id uuid,
    card_number_masked text,
    card_type text,
    card_brand text,
    credit_limit decimal,
    current_balance decimal,
    expiry_date date,
    status text,
    issued_date date,
    reward_points int,
    annual_fee decimal,
    PRIMARY KEY ((customer_id), card_id)
);

-- ============================================================================
-- INSERT SAMPLE DATA
-- ============================================================================

-- Branches
INSERT INTO branches (branch_id, branch_name, branch_type, address, city, state, zip_code, country, phone, manager_name, employee_count, opened_date, is_active, services, operating_hours)
VALUES ('BR001', 'Downtown Main Branch', 'Full Service', '100 Financial Plaza', 'New York', 'NY', '10001', 'USA', '(212) 555-0100', 'Jennifer Morrison', 45, '1995-03-15', true, ['Deposits', 'Loans', 'Investments', 'Safe Deposit', 'Notary'], {'Mon-Fri': '9:00 AM - 5:00 PM', 'Sat': '9:00 AM - 1:00 PM', 'Sun': 'Closed'});

INSERT INTO branches (branch_id, branch_name, branch_type, address, city, state, zip_code, country, phone, manager_name, employee_count, opened_date, is_active, services, operating_hours)
VALUES ('BR002', 'Westside Financial Center', 'Full Service', '500 Commerce Drive', 'Los Angeles', 'CA', '90001', 'USA', '(310) 555-0200', 'Michael Chen', 38, '2001-07-22', true, ['Deposits', 'Loans', 'Investments', 'Wealth Management'], {'Mon-Fri': '9:00 AM - 6:00 PM', 'Sat': '10:00 AM - 2:00 PM', 'Sun': 'Closed'});

INSERT INTO branches (branch_id, branch_name, branch_type, address, city, state, zip_code, country, phone, manager_name, employee_count, opened_date, is_active, services, operating_hours)
VALUES ('BR003', 'Tech Hub Branch', 'Digital First', '250 Innovation Way', 'San Francisco', 'CA', '94105', 'USA', '(415) 555-0300', 'Sarah Williams', 22, '2018-11-01', true, ['Deposits', 'Digital Banking', 'Startup Loans', 'Business Banking'], {'Mon-Fri': '8:00 AM - 7:00 PM', 'Sat': '9:00 AM - 5:00 PM', 'Sun': '10:00 AM - 3:00 PM'});

INSERT INTO branches (branch_id, branch_name, branch_type, address, city, state, zip_code, country, phone, manager_name, employee_count, opened_date, is_active, services, operating_hours)
VALUES ('BR004', 'Midwest Regional Center', 'Regional HQ', '800 Lake Shore Blvd', 'Chicago', 'IL', '60601', 'USA', '(312) 555-0400', 'Robert Johnson', 65, '1988-05-10', true, ['Deposits', 'Loans', 'Investments', 'Commercial Banking', 'Treasury Services'], {'Mon-Fri': '8:30 AM - 5:30 PM', 'Sat': '9:00 AM - 12:00 PM', 'Sun': 'Closed'});

INSERT INTO branches (branch_id, branch_name, branch_type, address, city, state, zip_code, country, phone, manager_name, employee_count, opened_date, is_active, services, operating_hours)
VALUES ('BR005', 'South Beach Express', 'Express', '150 Ocean Drive', 'Miami', 'FL', '33139', 'USA', '(305) 555-0500', 'Carlos Rodriguez', 12, '2020-02-14', true, ['Deposits', 'ATM', 'Quick Loans'], {'Mon-Fri': '10:00 AM - 7:00 PM', 'Sat': '10:00 AM - 4:00 PM', 'Sun': 'Closed'});

-- Customers (Northeast region)
INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'NORTHEAST', 'James', 'Anderson', 'james.anderson@email.com', '(212) 555-1001', '1985-06-15', '4521', '123 Park Avenue', 'New York', 'NY', '10016', 'USA', 780, '2015-03-20', 'PLATINUM', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'NORTHEAST', 'Emily', 'Thompson', 'emily.thompson@email.com', '(617) 555-1002', '1990-11-28', '7832', '456 Beacon Street', 'Boston', 'MA', '02108', 'USA', 720, '2018-07-12', 'GOLD', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'NORTHEAST', 'David', 'Martinez', 'david.martinez@email.com', '(215) 555-1003', '1978-03-05', '2156', '789 Market Street', 'Philadelphia', 'PA', '19103', 'USA', 695, '2010-01-08', 'SILVER', true, toTimestamp(now()), toTimestamp(now()));

-- Customers (West region)
INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'WEST', 'Sophia', 'Lee', 'sophia.lee@email.com', '(415) 555-2001', '1992-09-18', '3847', '321 Silicon Valley Blvd', 'San Jose', 'CA', '95110', 'USA', 810, '2019-05-22', 'PLATINUM', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'WEST', 'Michael', 'Wong', 'michael.wong@email.com', '(310) 555-2002', '1988-12-03', '9156', '555 Sunset Boulevard', 'Los Angeles', 'CA', '90028', 'USA', 745, '2016-11-30', 'GOLD', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'WEST', 'Amanda', 'Garcia', 'amanda.garcia@email.com', '(206) 555-2003', '1995-07-21', '6234', '888 Pike Place', 'Seattle', 'WA', '98101', 'USA', 680, '2021-02-14', 'SILVER', true, toTimestamp(now()), toTimestamp(now()));

-- Customers (South region)
INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'SOUTH', 'William', 'Johnson', 'william.johnson@email.com', '(305) 555-3001', '1982-04-10', '5478', '100 Brickell Avenue', 'Miami', 'FL', '33131', 'USA', 765, '2012-08-05', 'GOLD', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'SOUTH', 'Rachel', 'Davis', 'rachel.davis@email.com', '(404) 555-3002', '1987-01-25', '8912', '200 Peachtree Street', 'Atlanta', 'GA', '30303', 'USA', 710, '2017-04-18', 'GOLD', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'SOUTH', 'Christopher', 'Brown', 'christopher.brown@email.com', '(512) 555-3003', '1975-08-30', '3621', '300 Congress Avenue', 'Austin', 'TX', '78701', 'USA', 825, '2008-12-01', 'PLATINUM', true, toTimestamp(now()), toTimestamp(now()));

-- Customers (Midwest region)
INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'MIDWEST', 'Jennifer', 'Wilson', 'jennifer.wilson@email.com', '(312) 555-4001', '1991-05-12', '7745', '400 Michigan Avenue', 'Chicago', 'IL', '60611', 'USA', 790, '2014-09-25', 'PLATINUM', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'MIDWEST', 'Daniel', 'Taylor', 'daniel.taylor@email.com', '(313) 555-4002', '1983-10-08', '2389', '500 Woodward Avenue', 'Detroit', 'MI', '48226', 'USA', 655, '2020-06-10', 'SILVER', true, toTimestamp(now()), toTimestamp(now()));

INSERT INTO customers (customer_id, region, first_name, last_name, email, phone, date_of_birth, ssn_last_four, address, city, state, zip_code, country, credit_score, customer_since, customer_tier, is_active, created_at, updated_at)
VALUES (uuid(), 'MIDWEST', 'Lisa', 'Miller', 'lisa.miller@email.com', '(614) 555-4003', '1989-02-17', '4567', '600 High Street', 'Columbus', 'OH', '43215', 'USA', 735, '2016-03-08', 'GOLD', true, toTimestamp(now()), toTimestamp(now()));

-- Note: Accounts, Transactions, Loans, and Cards would be inserted with actual customer_ids
-- after querying the customers table. For a full initialization, use a script that can
-- handle sequential inserts with ID lookups.

-- Sample message for verification
-- SELECT * FROM branches;
-- SELECT * FROM customers WHERE region = 'NORTHEAST';
