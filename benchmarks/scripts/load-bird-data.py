#!/usr/bin/env python3
"""
Load BIRD Mini-Dev SQLite databases into PostgreSQL and MySQL.

Uses sqlglot for DDL/DML transpilation from SQLite dialect to the target.
Each BIRD database (e.g. california_schools, card_games) becomes a separate
schema in PostgreSQL or a separate database in MySQL.

Usage:
    # Load into PostgreSQL
    python benchmarks/scripts/load-bird-data.py \
        --target postgresql \
        --connection "postgresql://benchmark:benchmark123@localhost:15432/benchmark_db" \
        --data-dir benchmarks/data

    # Load into MySQL
    python benchmarks/scripts/load-bird-data.py \
        --target mysql \
        --connection "mysql://benchmark:benchmark123@localhost:13306/benchmark_db" \
        --data-dir benchmarks/data

    # Load into both (used by run-sandbox.sh)
    python benchmarks/scripts/load-bird-data.py --all --data-dir benchmarks/data
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("load-bird-data")


def _get_sqlite_databases(data_dir: Path) -> List[Tuple[str, Path]]:
    """Find all BIRD SQLite database files."""
    bird_dir = data_dir / "bird-mini-dev" / "dev_databases"
    if not bird_dir.exists():
        logger.error("BIRD dev_databases not found at %s", bird_dir)
        logger.error("Run: python -m benchmarks download --dataset bird-mini-dev --data-dir %s", data_dir)
        sys.exit(1)

    dbs = []
    for db_dir in sorted(bird_dir.iterdir()):
        if not db_dir.is_dir():
            continue
        db_file = db_dir / f"{db_dir.name}.sqlite"
        if db_file.exists():
            dbs.append((db_dir.name, db_file))
    return dbs


def _extract_ddl_and_data(db_path: Path) -> Tuple[List[str], List[Tuple[str, List[Tuple]]]]:
    """Extract CREATE TABLE statements and row data from a SQLite database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get CREATE TABLE statements
    cursor.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND sql IS NOT NULL "
        "ORDER BY name"
    )
    tables = cursor.fetchall()

    ddl_statements = []
    table_data = []

    for table_name, create_sql in tables:
        if table_name.startswith("sqlite_"):
            continue
        ddl_statements.append(create_sql)

        # Extract rows
        try:
            cursor.execute(f'SELECT * FROM "{table_name}"')
            rows = cursor.fetchall()
            if rows:
                table_data.append((table_name, rows))
        except Exception as exc:
            logger.warning("Could not read data from %s: %s", table_name, exc)

    conn.close()
    return ddl_statements, table_data


def _transpile_ddl(create_sql: str, target: str) -> str:
    """Transpile a CREATE TABLE from SQLite to target dialect using sqlglot."""
    try:
        import sqlglot
        transpiled = sqlglot.transpile(
            create_sql,
            read="sqlite",
            write=target,
            pretty=True,
        )
        return transpiled[0] if transpiled else create_sql
    except Exception as exc:
        logger.warning("sqlglot transpile failed, using raw DDL: %s", exc)
        # Fallback: manual fixups for common SQLite→PostgreSQL/MySQL issues
        sql = create_sql
        if target == "postgres":
            sql = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
                         "SERIAL PRIMARY KEY", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bAUTOINCREMENT\b", "", sql, flags=re.IGNORECASE)
        elif target == "mysql":
            sql = re.sub(r"\bAUTOINCREMENT\b", "AUTO_INCREMENT",
                         sql, flags=re.IGNORECASE)
        return sql


# -------------------------------------------------------------------------
# PostgreSQL loader
# -------------------------------------------------------------------------


def load_into_postgresql(connection_url: str, data_dir: Path, db_names: Optional[List[str]] = None) -> None:
    """Load BIRD databases into PostgreSQL schemas."""
    try:
        import asyncpg
    except ImportError:
        logger.error("asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    import asyncio

    databases = _get_sqlite_databases(data_dir)
    if db_names:
        databases = [(n, p) for n, p in databases if n in db_names]

    logger.info("Loading %d databases into PostgreSQL", len(databases))

    async def _load():
        conn = await asyncpg.connect(connection_url)

        for db_name, db_path in databases:
            logger.info("  Loading %s...", db_name)
            ddl_statements, table_data = _extract_ddl_and_data(db_path)

            # Create schema for each database
            schema = db_name.lower()
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET search_path TO "{schema}"')

            # Create tables
            for create_sql in ddl_statements:
                transpiled = _transpile_ddl(create_sql, "postgres")
                try:
                    await conn.execute(transpiled)
                except Exception as exc:
                    logger.warning("    DDL failed for %s: %s", db_name, exc)
                    # Try raw DDL as fallback
                    try:
                        await conn.execute(create_sql)
                    except Exception:
                        logger.error("    DDL fallback also failed, skipping table")
                        continue

            # Insert data
            for table_name, rows in table_data:
                if not rows:
                    continue
                ncols = len(rows[0])
                insert_sql = f'INSERT INTO "{table_name}" VALUES ({", ".join(["$" + str(i + 1) for i in range(ncols)])})'
                try:
                    await conn.executemany(insert_sql, rows)
                    logger.info("    %s: %d rows", table_name, len(rows))
                except Exception as exc:
                    logger.warning("    Insert failed for %s.%s: %s", db_name, table_name, exc)

            # Reset search path
            await conn.execute('SET search_path TO public')

        await conn.close()
        logger.info("PostgreSQL loading complete")

    asyncio.run(_load())


# -------------------------------------------------------------------------
# MySQL loader
# -------------------------------------------------------------------------


def load_into_mysql(connection_url: str, data_dir: Path, db_names: Optional[List[str]] = None) -> None:
    """Load BIRD databases into MySQL (each as a separate database)."""
    try:
        import pymysql
    except ImportError:
        logger.error("pymysql not installed. Run: pip install pymysql")
        sys.exit(1)

    # Parse connection URL
    # mysql://user:pass@host:port/db
    from urllib.parse import urlparse
    parsed = urlparse(connection_url)

    databases = _get_sqlite_databases(data_dir)
    if db_names:
        databases = [(n, p) for n, p in databases if n in db_names]

    logger.info("Loading %d databases into MySQL", len(databases))

    conn = pymysql.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 3306,
        user=parsed.username or "benchmark",
        password=parsed.password or "benchmark123",
        charset="utf8mb4",
    )
    cursor = conn.cursor()

    for db_name, db_path in databases:
        logger.info("  Loading %s...", db_name)
        ddl_statements, table_data = _extract_ddl_and_data(db_path)

        # Create database
        safe_name = db_name.lower().replace("-", "_")
        cursor.execute(f"DROP DATABASE IF EXISTS `{safe_name}`")
        cursor.execute(f"CREATE DATABASE `{safe_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"USE `{safe_name}`")

        # Create tables
        for create_sql in ddl_statements:
            transpiled = _transpile_ddl(create_sql, "mysql")
            try:
                cursor.execute(transpiled)
            except Exception as exc:
                logger.warning("    DDL failed for %s: %s", db_name, exc)
                try:
                    cursor.execute(create_sql)
                except Exception:
                    logger.error("    DDL fallback also failed, skipping table")
                    continue

        # Insert data
        for table_name, rows in table_data:
            if not rows:
                continue
            ncols = len(rows[0])
            placeholders = ", ".join(["%s"] * ncols)
            insert_sql = f"INSERT INTO `{table_name}` VALUES ({placeholders})"
            try:
                cursor.executemany(insert_sql, rows)
                conn.commit()
                logger.info("    %s: %d rows", table_name, len(rows))
            except Exception as exc:
                logger.warning("    Insert failed for %s.%s: %s", db_name, table_name, exc)
                conn.rollback()

    cursor.close()
    conn.close()
    logger.info("MySQL loading complete")


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load BIRD Mini-Dev SQLite databases into PostgreSQL/MySQL"
    )
    parser.add_argument(
        "--target",
        choices=["postgresql", "mysql"],
        help="Target database type",
    )
    parser.add_argument(
        "--connection",
        help="Connection URL for the target database",
    )
    parser.add_argument(
        "--data-dir",
        default="benchmarks/data",
        help="Directory containing BIRD Mini-Dev data",
    )
    parser.add_argument(
        "--db-names",
        nargs="*",
        help="Only load specific databases (space-separated db_ids)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Load into both PostgreSQL and MySQL using default sandbox URLs",
    )

    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    if args.all:
        pg_url = os.getenv(
            "BENCHMARK_PG_URL",
            "postgresql://benchmark:benchmark123@localhost:15432/benchmark_db",
        )
        mysql_url = os.getenv(
            "BENCHMARK_MYSQL_URL",
            "mysql://benchmark:benchmark123@localhost:13306/benchmark_db",
        )
        load_into_postgresql(pg_url, data_dir, args.db_names)
        load_into_mysql(mysql_url, data_dir, args.db_names)
    elif args.target == "postgresql":
        url = args.connection or os.getenv(
            "BENCHMARK_PG_URL",
            "postgresql://benchmark:benchmark123@localhost:15432/benchmark_db",
        )
        load_into_postgresql(url, data_dir, args.db_names)
    elif args.target == "mysql":
        url = args.connection or os.getenv(
            "BENCHMARK_MYSQL_URL",
            "mysql://benchmark:benchmark123@localhost:13306/benchmark_db",
        )
        load_into_mysql(url, data_dir, args.db_names)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
