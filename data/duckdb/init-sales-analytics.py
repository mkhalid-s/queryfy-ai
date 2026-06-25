#!/usr/bin/env python3
"""
DuckDB Sales Analytics Database Initialization Script
Creates a sample OLAP database for testing NL2SQL queries
"""

import duckdb
import random
from datetime import datetime, timedelta
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent / "sales_analytics.duckdb"


def create_database():
    """Create and populate the DuckDB sales analytics database."""

    # Remove existing database
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = duckdb.connect(str(DB_PATH))

    print("Creating DuckDB Sales Analytics Database...")
    print(f"Location: {DB_PATH}")

    # =========================================================================
    # CREATE TABLES
    # =========================================================================

    # Products dimension
    conn.execute(
        """
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            product_name VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            subcategory VARCHAR,
            brand VARCHAR,
            unit_cost DECIMAL(10, 2),
            unit_price DECIMAL(10, 2),
            is_active BOOLEAN DEFAULT TRUE,
            created_date DATE
        )
    """
    )

    # Customers dimension
    conn.execute(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            customer_name VARCHAR NOT NULL,
            email VARCHAR,
            segment VARCHAR,
            region VARCHAR,
            country VARCHAR,
            state VARCHAR,
            city VARCHAR,
            registration_date DATE,
            lifetime_value DECIMAL(12, 2)
        )
    """
    )

    # Stores dimension
    conn.execute(
        """
        CREATE TABLE stores (
            store_id INTEGER PRIMARY KEY,
            store_name VARCHAR NOT NULL,
            store_type VARCHAR,
            region VARCHAR,
            country VARCHAR,
            state VARCHAR,
            city VARCHAR,
            opened_date DATE,
            manager_name VARCHAR,
            square_footage INTEGER
        )
    """
    )

    # Orders fact table
    conn.execute(
        """
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            order_date TIMESTAMP NOT NULL,
            customer_id INTEGER REFERENCES customers(customer_id),
            store_id INTEGER REFERENCES stores(store_id),
            product_id INTEGER REFERENCES products(product_id),
            quantity INTEGER,
            unit_price DECIMAL(10, 2),
            discount_percent DECIMAL(5, 2),
            gross_amount DECIMAL(12, 2),
            discount_amount DECIMAL(12, 2),
            net_amount DECIMAL(12, 2),
            cost_amount DECIMAL(12, 2),
            profit_amount DECIMAL(12, 2),
            payment_method VARCHAR,
            order_status VARCHAR,
            shipping_method VARCHAR,
            shipping_cost DECIMAL(8, 2)
        )
    """
    )

    # =========================================================================
    # INSERT SAMPLE DATA - PRODUCTS
    # =========================================================================
    products = [
        (
            1001,
            'MacBook Pro 16"',
            "Electronics",
            "Laptops",
            "Apple",
            1800.00,
            2499.00,
            True,
            "2023-01-15",
        ),
        (
            1002,
            "iPhone 15 Pro",
            "Electronics",
            "Smartphones",
            "Apple",
            800.00,
            1199.00,
            True,
            "2023-09-22",
        ),
        (
            1003,
            "Samsung Galaxy S24",
            "Electronics",
            "Smartphones",
            "Samsung",
            650.00,
            999.00,
            True,
            "2024-01-17",
        ),
        (
            1004,
            "Sony WH-1000XM5",
            "Electronics",
            "Headphones",
            "Sony",
            220.00,
            399.00,
            True,
            "2022-05-20",
        ),
        (
            1005,
            "Dell XPS 15",
            "Electronics",
            "Laptops",
            "Dell",
            1200.00,
            1799.00,
            True,
            "2023-03-10",
        ),
        (
            1006,
            'iPad Pro 12.9"',
            "Electronics",
            "Tablets",
            "Apple",
            900.00,
            1299.00,
            True,
            "2022-10-18",
        ),
        (
            1007,
            "Nike Air Max 90",
            "Apparel",
            "Footwear",
            "Nike",
            65.00,
            140.00,
            True,
            "2023-02-01",
        ),
        (
            1008,
            "Levi's 501 Jeans",
            "Apparel",
            "Pants",
            "Levi's",
            35.00,
            89.00,
            True,
            "2023-01-05",
        ),
        (
            1009,
            "North Face Jacket",
            "Apparel",
            "Outerwear",
            "North Face",
            120.00,
            299.00,
            True,
            "2023-08-15",
        ),
        (
            1010,
            "Adidas Ultraboost",
            "Apparel",
            "Footwear",
            "Adidas",
            80.00,
            190.00,
            True,
            "2023-04-20",
        ),
        (
            1011,
            "KitchenAid Mixer",
            "Home",
            "Kitchen",
            "KitchenAid",
            250.00,
            449.00,
            True,
            "2022-11-10",
        ),
        (
            1012,
            "Dyson V15 Vacuum",
            "Home",
            "Appliances",
            "Dyson",
            400.00,
            749.00,
            True,
            "2023-05-05",
        ),
        (
            1013,
            "Instant Pot Duo",
            "Home",
            "Kitchen",
            "Instant Pot",
            50.00,
            99.00,
            True,
            "2022-06-15",
        ),
        (
            1014,
            "Casper Mattress Queen",
            "Home",
            "Furniture",
            "Casper",
            600.00,
            1295.00,
            True,
            "2023-07-01",
        ),
        (
            1015,
            "Herman Miller Chair",
            "Home",
            "Furniture",
            "Herman Miller",
            800.00,
            1695.00,
            True,
            "2023-09-10",
        ),
        (
            1016,
            "AirPods Pro 2",
            "Electronics",
            "Audio",
            "Apple",
            150.00,
            249.00,
            True,
            "2023-09-12",
        ),
        (
            1017,
            "PlayStation 5",
            "Electronics",
            "Gaming",
            "Sony",
            400.00,
            499.00,
            True,
            "2023-11-10",
        ),
        (
            1018,
            "Nintendo Switch OLED",
            "Electronics",
            "Gaming",
            "Nintendo",
            280.00,
            349.00,
            True,
            "2023-10-08",
        ),
        (
            1019,
            'LG OLED TV 65"',
            "Electronics",
            "TVs",
            "LG",
            1500.00,
            2199.00,
            True,
            "2023-03-15",
        ),
        (
            1020,
            "Bose QuietComfort",
            "Electronics",
            "Headphones",
            "Bose",
            200.00,
            349.00,
            True,
            "2023-06-20",
        ),
    ]

    conn.executemany(
        """
        INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        products,
    )

    print(f"  Inserted {len(products)} products")

    # =========================================================================
    # INSERT SAMPLE DATA - CUSTOMERS
    # =========================================================================
    customers = [
        (
            10001,
            "TechCorp Industries",
            "tech@techcorp.com",
            "Enterprise",
            "Northeast",
            "USA",
            "NY",
            "New York",
            "2020-03-15",
            125000.00,
        ),
        (
            10002,
            "SmallBiz Solutions",
            "orders@smallbiz.com",
            "SMB",
            "West",
            "USA",
            "CA",
            "San Francisco",
            "2021-07-22",
            45000.00,
        ),
        (
            10003,
            "John Smith",
            "john.smith@email.com",
            "Consumer",
            "Southeast",
            "USA",
            "FL",
            "Miami",
            "2022-01-10",
            8500.00,
        ),
        (
            10004,
            "MegaCorp LLC",
            "procurement@megacorp.com",
            "Enterprise",
            "Midwest",
            "USA",
            "IL",
            "Chicago",
            "2019-11-05",
            350000.00,
        ),
        (
            10005,
            "Sarah Johnson",
            "sarah.j@email.com",
            "Consumer",
            "West",
            "USA",
            "WA",
            "Seattle",
            "2022-06-18",
            12000.00,
        ),
        (
            10006,
            "RetailMax Inc",
            "buying@retailmax.com",
            "Enterprise",
            "South",
            "USA",
            "TX",
            "Dallas",
            "2020-08-30",
            275000.00,
        ),
        (
            10007,
            "Michael Chen",
            "mchen@email.com",
            "Consumer",
            "West",
            "USA",
            "CA",
            "Los Angeles",
            "2023-02-14",
            6500.00,
        ),
        (
            10008,
            "StartupXYZ",
            "hello@startupxyz.com",
            "SMB",
            "Northeast",
            "USA",
            "MA",
            "Boston",
            "2022-09-01",
            28000.00,
        ),
        (
            10009,
            "Emily Davis",
            "emily.d@email.com",
            "Consumer",
            "Southeast",
            "USA",
            "GA",
            "Atlanta",
            "2023-04-25",
            4200.00,
        ),
        (
            10010,
            "GlobalTrade Partners",
            "orders@globaltrade.com",
            "Enterprise",
            "Northeast",
            "USA",
            "NY",
            "New York",
            "2018-05-12",
            520000.00,
        ),
        (
            10011,
            "Jessica Williams",
            "jwilliams@email.com",
            "Consumer",
            "Midwest",
            "USA",
            "OH",
            "Columbus",
            "2023-01-08",
            3200.00,
        ),
        (
            10012,
            "DataDriven Co",
            "sales@datadriven.com",
            "SMB",
            "West",
            "USA",
            "CO",
            "Denver",
            "2021-11-15",
            67000.00,
        ),
        (
            10013,
            "Robert Martinez",
            "rmartinez@email.com",
            "Consumer",
            "South",
            "USA",
            "AZ",
            "Phoenix",
            "2022-08-20",
            5800.00,
        ),
        (
            10014,
            "CloudFirst Inc",
            "procurement@cloudfirst.com",
            "Enterprise",
            "West",
            "USA",
            "CA",
            "San Jose",
            "2019-06-01",
            425000.00,
        ),
        (
            10015,
            "Amanda Lee",
            "alee@email.com",
            "Consumer",
            "Northeast",
            "USA",
            "PA",
            "Philadelphia",
            "2023-05-30",
            2900.00,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        customers,
    )

    print(f"  Inserted {len(customers)} customers")

    # =========================================================================
    # INSERT SAMPLE DATA - STORES
    # =========================================================================
    stores = [
        (
            101,
            "NYC Flagship Store",
            "Flagship",
            "Northeast",
            "USA",
            "NY",
            "New York",
            "2015-06-01",
            "Jennifer Morrison",
            45000,
        ),
        (
            102,
            "LA Premium Outlet",
            "Outlet",
            "West",
            "USA",
            "CA",
            "Los Angeles",
            "2017-03-15",
            "David Chen",
            32000,
        ),
        (
            103,
            "Chicago Downtown",
            "Standard",
            "Midwest",
            "USA",
            "IL",
            "Chicago",
            "2018-09-20",
            "Robert Martinez",
            28000,
        ),
        (
            104,
            "Miami Beach Store",
            "Standard",
            "Southeast",
            "USA",
            "FL",
            "Miami",
            "2019-11-10",
            "Maria Garcia",
            22000,
        ),
        (
            105,
            "Dallas Mega Store",
            "Flagship",
            "South",
            "USA",
            "TX",
            "Dallas",
            "2016-04-25",
            "James Wilson",
            55000,
        ),
        (
            106,
            "Seattle Tech Hub",
            "Specialty",
            "West",
            "USA",
            "WA",
            "Seattle",
            "2020-02-14",
            "Lisa Park",
            18000,
        ),
        (
            107,
            "Boston Commons",
            "Standard",
            "Northeast",
            "USA",
            "MA",
            "Boston",
            "2019-07-04",
            "Kevin O'Brien",
            25000,
        ),
        (
            108,
            "Atlanta Perimeter",
            "Standard",
            "Southeast",
            "USA",
            "GA",
            "Atlanta",
            "2021-01-15",
            "Angela Thompson",
            20000,
        ),
        (
            109,
            "SF Union Square",
            "Flagship",
            "West",
            "USA",
            "CA",
            "San Francisco",
            "2014-08-20",
            "Michelle Wong",
            40000,
        ),
        (
            110,
            "Online Store",
            "E-commerce",
            "National",
            "USA",
            "NA",
            "Virtual",
            "2010-01-01",
            "System Admin",
            0,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO stores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        stores,
    )

    print(f"  Inserted {len(stores)} stores")

    # =========================================================================
    # INSERT SAMPLE DATA - ORDERS (Generate 10,000 orders)
    # =========================================================================
    print("  Generating 10,000 orders...")

    random.seed(42)  # For reproducibility

    product_ids = [p[0] for p in products]
    product_prices = {p[0]: (p[5], p[6]) for p in products}  # cost, price
    customer_ids = [c[0] for c in customers]

    store_ids = [s[0] for s in stores]

    payment_methods = [
        "Credit Card",
        "Debit Card",
        "PayPal",
        "Apple Pay",
        "Wire Transfer",
    ]
    order_statuses = [
        "Completed",
        "Completed",
        "Completed",
        "Completed",
        "Shipped",
        "Processing",
        "Refunded",
    ]
    shipping_methods = ["Standard", "Express", "Next Day", "Store Pickup"]
    shipping_costs = [0.00, 5.99, 9.99, 14.99, 24.99]
    discount_options = [0, 5, 10, 15, 20, 25]

    # Generate date range: 2023-01-01 to 2025-01-09
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2025, 1, 9)
    date_range = (end_date - start_date).days

    orders = []
    for i in range(10000):
        order_id = 1000000 + i
        order_date = start_date + timedelta(
            days=random.randint(0, date_range),
            hours=random.randint(6, 22),
            minutes=random.randint(0, 59),
        )
        customer_id = random.choice(customer_ids)
        store_id = random.choice(store_ids)
        product_id = random.choice(product_ids)
        quantity = random.randint(1, 5)

        cost, price = product_prices[product_id]
        unit_price = price
        discount_percent = random.choice(discount_options)
        gross_amount = quantity * unit_price
        discount_amount = gross_amount * (discount_percent / 100)
        net_amount = gross_amount - discount_amount
        cost_amount = quantity * cost
        profit_amount = net_amount - cost_amount

        payment_method = random.choice(payment_methods)
        order_status = random.choice(order_statuses)
        shipping_method = random.choice(shipping_methods)
        shipping_cost = (
            random.choice(shipping_costs) if shipping_method != "Store Pickup" else 0
        )

        orders.append(
            (
                order_id,
                order_date,
                customer_id,
                store_id,
                product_id,
                quantity,
                unit_price,
                discount_percent,
                gross_amount,
                discount_amount,
                net_amount,
                cost_amount,
                profit_amount,
                payment_method,
                order_status,
                shipping_method,
                shipping_cost,
            )
        )

    conn.executemany(
        """
        INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        orders,
    )

    print(f"  Inserted {len(orders)} orders")

    # =========================================================================
    # CREATE VIEWS FOR ANALYTICS
    # =========================================================================

    # Daily sales summary view
    conn.execute(
        """
        CREATE VIEW v_daily_sales AS
        SELECT
            DATE_TRUNC('day', order_date) AS date,
            COUNT(*) AS total_orders,
            SUM(quantity) AS total_units,
            SUM(gross_amount) AS gross_revenue,
            SUM(net_amount) AS net_revenue,
            SUM(profit_amount) AS profit,
            AVG(net_amount) AS avg_order_value,
            COUNT(DISTINCT customer_id) AS unique_customers
        FROM orders
        WHERE order_status != 'Refunded'
        GROUP BY DATE_TRUNC('day', order_date)
        ORDER BY date
    """
    )

    # Monthly sales by category view
    conn.execute(
        """
        CREATE VIEW v_monthly_category_sales AS
        SELECT
            DATE_TRUNC('month', o.order_date) AS month,
            p.category,
            COUNT(*) AS total_orders,
            SUM(o.quantity) AS total_units,
            SUM(o.net_amount) AS revenue,
            SUM(o.profit_amount) AS profit
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
        WHERE o.order_status != 'Refunded'
        GROUP BY DATE_TRUNC('month', o.order_date), p.category
        ORDER BY month, revenue DESC
    """
    )

    # Customer segment analysis view
    conn.execute(
        """
        CREATE VIEW v_customer_segment_analysis AS
        SELECT
            c.segment,
            c.region,
            COUNT(DISTINCT c.customer_id) AS customer_count,
            COUNT(o.order_id) AS total_orders,
            SUM(o.net_amount) AS total_revenue,
            AVG(o.net_amount) AS avg_order_value,
            SUM(o.profit_amount) AS total_profit
        FROM customers c
        LEFT JOIN orders o ON c.customer_id = o.customer_id
        GROUP BY c.segment, c.region
        ORDER BY total_revenue DESC
    """
    )

    # Top products view
    conn.execute(
        """
        CREATE VIEW v_top_products AS
        SELECT
            p.product_id,
            p.product_name,
            p.category,
            p.brand,
            COUNT(o.order_id) AS times_ordered,
            SUM(o.quantity) AS units_sold,
            SUM(o.net_amount) AS revenue,
            SUM(o.profit_amount) AS profit,
            AVG(o.discount_percent) AS avg_discount
        FROM products p
        LEFT JOIN orders o ON p.product_id = o.product_id
        GROUP BY p.product_id, p.product_name, p.category, p.brand
        ORDER BY revenue DESC
    """
    )

    # Store performance view
    conn.execute(
        """
        CREATE VIEW v_store_performance AS
        SELECT
            s.store_id,
            s.store_name,
            s.store_type,
            s.region,
            s.city,
            COUNT(o.order_id) AS total_orders,
            SUM(o.net_amount) AS revenue,
            SUM(o.profit_amount) AS profit,
            AVG(o.net_amount) AS avg_order_value,
            COUNT(DISTINCT o.customer_id) AS unique_customers
        FROM stores s
        LEFT JOIN orders o ON s.store_id = o.store_id
        GROUP BY s.store_id, s.store_name, s.store_type, s.region, s.city
        ORDER BY revenue DESC
    """
    )

    print("  Created 5 analytics views")

    # =========================================================================
    # PRINT SUMMARY
    # =========================================================================

    # Get table counts
    tables = conn.execute("SHOW TABLES").fetchall()

    print("\n" + "=" * 60)
    print("DATABASE CREATED SUCCESSFULLY!")
    print("=" * 60)
    print(f"\nLocation: {DB_PATH}")
    print(f"Size: {DB_PATH.stat().st_size / 1024:.1f} KB")
    print("\nTables:")
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table[0]}").fetchone()[0]
        print(f"  - {table[0]}: {count:,} rows")

    print("\nViews:")
    print("  - v_daily_sales")
    print("  - v_monthly_category_sales")
    print("  - v_customer_segment_analysis")
    print("  - v_top_products")
    print("  - v_store_performance")

    print("\n" + "=" * 60)
    print("CONNECTION URL FOR NL2SQL APP:")
    print("=" * 60)
    print(f"\nduckdb:///{DB_PATH}")

    print("\n" + "=" * 60)
    print("SAMPLE QUERIES TO TEST:")
    print("=" * 60)
    print(
        """
1. "What are the top 5 selling products by revenue?"
2. "Show me monthly sales trends for 2024"
3. "Which customer segment generates the most profit?"
4. "Compare revenue by store region"
5. "What's the average discount by product category?"
"""
    )

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    create_database()
