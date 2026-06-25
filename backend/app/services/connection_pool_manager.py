"""
QueryfyAI - Connection Pool Manager

Multi-database connection pooling with support for:
- Async databases (PostgreSQL, MySQL, MongoDB)
- Sync databases via thread pool (Snowflake, BigQuery, SQL Server, Oracle, Redshift, Databricks)
- Data Lakes (AWS Athena, Trino/Presto, ClickHouse, Spark/Hive)

Features:
- Pool sharing across sessions with same connection URL
- Lazy pool creation (on-demand)
- Automatic cleanup of idle pools
- Health checks and connection validation
"""

import asyncio
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.core.config import settings
from app.models.schemas import DatabaseConfig

logger = logging.getLogger(__name__)


@dataclass
class PoolConfig:
    """Configuration for connection pools"""

    # Async pool settings
    min_size: int = 2
    max_size: int = 10

    # Sync pool settings (thread executor)
    sync_max_workers: int = 20

    # Pool lifecycle
    max_idle_time: int = 300  # 5 minutes - close idle pools
    max_pool_age: int = 3600  # 1 hour - recreate pools
    health_check_interval: int = 60  # Check pool health every minute

    # Connection settings
    connection_timeout: int = 10
    query_timeout: int = 300


@dataclass
class PoolStats:
    """Statistics for a connection pool"""

    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    total_connections: int = 0
    active_connections: int = 0
    total_queries: int = 0
    errors: int = 0


class ConnectionPoolManager:
    """
    Manages connection pools for multiple databases across sessions.

    Usage:
        pool_manager = ConnectionPoolManager()

        async with pool_manager.get_connection(db_config) as conn:
            result = await conn.fetch("SELECT * FROM users")
    """

    _instance = None
    _initialized: bool
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.config = PoolConfig()

        # Async pools keyed by connection URL hash
        self._async_pools: Dict[str, Any] = {}
        self._pool_stats: Dict[str, PoolStats] = {}
        self._pool_locks: Dict[str, asyncio.Lock] = {}

        # Sync database thread pool
        self._sync_executor = ThreadPoolExecutor(
            max_workers=self.config.sync_max_workers, thread_name_prefix="db_sync_"
        )

        # Sync connection pools (for pooled sync DBs like Snowflake)
        self._sync_pools: Dict[str, Any] = {}

        # Global lock for pool creation
        self._global_lock = asyncio.Lock()

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None

        self._initialized = True
        logger.info("ConnectionPoolManager initialized")

    def _get_pool_key(self, config: DatabaseConfig) -> str:
        """Generate unique key for connection URL (hashed for security)"""
        # Include db_type to differentiate same URL different types
        key_string = f"{config.db_type}:{config.connection_url}"
        return hashlib.sha256(key_string.encode()).hexdigest()[:16]

    async def _get_or_create_lock(self, pool_key: str) -> asyncio.Lock:
        """Get or create a lock for a specific pool"""
        if pool_key not in self._pool_locks:
            async with self._global_lock:
                if pool_key not in self._pool_locks:
                    self._pool_locks[pool_key] = asyncio.Lock()
        return self._pool_locks[pool_key]

    # =========================================================================
    # ASYNC DATABASE POOLS (PostgreSQL, MySQL, MongoDB)
    # =========================================================================

    async def _create_postgres_pool(self, config: DatabaseConfig) -> Any:
        """Create asyncpg connection pool"""
        import asyncpg

        parsed = urlparse(config.connection_url)

        pool = await asyncpg.create_pool(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path.strip("/").split("/")[0],
            user=parsed.username,
            password=parsed.password,
            min_size=self.config.min_size,
            max_size=self.config.max_size,
            command_timeout=self.config.query_timeout,
            timeout=self.config.connection_timeout,
        )

        logger.info(
            f"Created PostgreSQL pool: {parsed.hostname}:{parsed.port} (min={self.config.min_size}, max={self.config.max_size})"
        )
        return pool

    async def _create_mysql_pool(self, config: DatabaseConfig) -> Any:
        """Create aiomysql connection pool"""
        import aiomysql

        parsed = urlparse(config.connection_url)

        pool = await aiomysql.create_pool(
            host=parsed.hostname,
            port=parsed.port or 3306,
            db=parsed.path.strip("/").split("/")[0],
            user=parsed.username,
            password=parsed.password,
            minsize=self.config.min_size,
            maxsize=self.config.max_size,
            connect_timeout=self.config.connection_timeout,
            autocommit=True,
        )

        logger.info(f"Created MySQL pool: {parsed.hostname}:{parsed.port}")
        return pool

    async def _create_mongodb_client(self, config: DatabaseConfig) -> Any:
        """Create MongoDB client (has built-in pooling)"""
        from motor.motor_asyncio import AsyncIOMotorClient

        client: Any = AsyncIOMotorClient(
            config.connection_url,
            maxPoolSize=self.config.max_size,
            minPoolSize=self.config.min_size,
            serverSelectionTimeoutMS=self.config.connection_timeout * 1000,
        )

        # Verify connection
        await client.admin.command("ping")

        logger.info("Created MongoDB client with pooling")
        return client

    # =========================================================================
    # SYNC DATABASE SUPPORT (via Thread Executor)
    # =========================================================================

    def _create_snowflake_connection(self, config: DatabaseConfig) -> Any:
        """Create Snowflake connection (sync, runs in thread)"""
        import snowflake.connector

        parsed = urlparse(config.connection_url)
        path_parts = parsed.path.strip("/").split("/")
        params = (
            dict(p.split("=") for p in parsed.query.split("&") if "=" in p)
            if parsed.query
            else {}
        )

        conn = snowflake.connector.connect(
            user=parsed.username,
            password=parsed.password,
            account=parsed.hostname,
            database=path_parts[0] if path_parts else None,
            schema=path_parts[1] if len(path_parts) > 1 else "PUBLIC",
            warehouse=params.get("warehouse"),
            role=params.get("role"),
            login_timeout=self.config.connection_timeout,
        )

        logger.info(f"Created Snowflake connection: {parsed.hostname}")
        return conn

    def _create_bigquery_client(self, config: DatabaseConfig) -> Any:
        """Create BigQuery client (sync, runs in thread)"""
        from google.cloud import bigquery

        # Format: bigquery://project-id/dataset
        url = config.connection_url.replace("bigquery://", "")
        parts = url.split("/")
        project_id = parts[0]

        client = bigquery.Client(project=project_id)

        logger.info(f"Created BigQuery client: {project_id}")
        return client

    def _create_sqlserver_connection(self, config: DatabaseConfig) -> Any:
        """Create SQL Server connection (sync, runs in thread)"""
        import pyodbc

        parsed = urlparse(config.connection_url)
        database = parsed.path.strip("/").split("/")[0]

        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={parsed.hostname},{parsed.port or 1433};"
            f"DATABASE={database};"
            f"UID={parsed.username};"
            f"PWD={parsed.password};"
            f"Connection Timeout={self.config.connection_timeout};"
        )

        conn = pyodbc.connect(conn_str)

        logger.info(f"Created SQL Server connection: {parsed.hostname}")
        return conn

    def _create_oracle_connection(self, config: DatabaseConfig) -> Any:
        """Create Oracle connection (sync, runs in thread)"""
        import cx_Oracle

        parsed = urlparse(config.connection_url)
        service_name = parsed.path.strip("/").split("/")[0]

        dsn = cx_Oracle.makedsn(
            parsed.hostname, parsed.port or 1521, service_name=service_name
        )

        conn = cx_Oracle.connect(
            user=parsed.username,
            password=parsed.password,
            dsn=dsn,
        )

        logger.info(f"Created Oracle connection: {parsed.hostname}")
        return conn

    def _create_redshift_connection(self, config: DatabaseConfig) -> Any:
        """Create Redshift connection (sync, uses psycopg2)"""
        import psycopg2

        parsed = urlparse(config.connection_url)
        database = parsed.path.strip("/").split("/")[0]

        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5439,
            database=database,
            user=parsed.username,
            password=parsed.password,
            connect_timeout=self.config.connection_timeout,
        )

        logger.info(f"Created Redshift connection: {parsed.hostname}")
        return conn

    def _create_databricks_connection(self, config: DatabaseConfig) -> Any:
        """Create Databricks connection (sync, runs in thread)"""
        from databricks import sql

        parsed = urlparse(config.connection_url)
        params = (
            dict(p.split("=") for p in parsed.query.split("&") if "=" in p)
            if parsed.query
            else {}
        )

        conn = sql.connect(
            server_hostname=parsed.hostname,
            http_path=params.get("http_path", ""),
            access_token=parsed.password,  # Token in password field
        )

        logger.info(f"Created Databricks connection: {parsed.hostname}")
        return conn

    # =========================================================================
    # DATA LAKE SUPPORT (via Thread Executor)
    # =========================================================================

    def _create_athena_connection(self, config: DatabaseConfig) -> Any:
        """
        Create AWS Athena connection (sync, runs in thread)

        URL format: athena://access_key:secret_key@region/database?s3_staging_dir=s3://bucket/path
        Or: athena://region/database?s3_staging_dir=s3://bucket/path (uses default AWS credentials)
        """
        from pyathena import connect as athena_connect

        parsed = urlparse(config.connection_url)
        params = (
            dict(p.split("=") for p in parsed.query.split("&") if "=" in p)
            if parsed.query
            else {}
        )
        database = parsed.path.strip("/").split("/")[0] if parsed.path else "default"

        conn_kwargs = {
            "region_name": parsed.hostname,
            "schema_name": database,
            "s3_staging_dir": params.get("s3_staging_dir", ""),
            "work_group": params.get("work_group", "primary"),
        }

        # Use explicit credentials if provided
        if parsed.username and parsed.password:
            conn_kwargs["aws_access_key_id"] = parsed.username
            conn_kwargs["aws_secret_access_key"] = parsed.password

        conn = athena_connect(**conn_kwargs)

        logger.info(f"Created Athena connection: {parsed.hostname}/{database}")
        return conn

    def _create_trino_connection(self, config: DatabaseConfig) -> Any:
        """
        Create Trino/Presto connection (sync, runs in thread)

        URL format: trino://user:password@host:port/catalog/schema
        """
        from trino.auth import BasicAuthentication
        from trino.dbapi import connect as trino_connect

        parsed = urlparse(config.connection_url)
        path_parts = parsed.path.strip("/").split("/")
        catalog = path_parts[0] if path_parts else "hive"
        schema = path_parts[1] if len(path_parts) > 1 else "default"

        conn_kwargs = {
            "host": parsed.hostname,
            "port": parsed.port or 8080,
            "user": parsed.username or "anonymous",
            "catalog": catalog,
            "schema": schema,
        }

        # Add authentication if password provided
        if parsed.password:
            conn_kwargs["auth"] = BasicAuthentication(parsed.username, parsed.password)
            conn_kwargs["http_scheme"] = "https"

        conn = trino_connect(**conn_kwargs)

        logger.info(
            f"Created Trino connection: {parsed.hostname}:{parsed.port}/{catalog}/{schema}"
        )
        return conn

    def _create_clickhouse_connection(self, config: DatabaseConfig) -> Any:
        """
        Create ClickHouse connection (sync, runs in thread)

        URL format: clickhouse://user:password@host:port/database
        """
        import clickhouse_connect

        parsed = urlparse(config.connection_url)
        database = parsed.path.strip("/").split("/")[0] if parsed.path else "default"

        client = clickhouse_connect.get_client(
            host=parsed.hostname,
            port=parsed.port or 8123,  # HTTP interface default
            username=parsed.username or "default",
            password=parsed.password or "",
            database=database,
            connect_timeout=self.config.connection_timeout,
        )

        logger.info(
            f"Created ClickHouse connection: {parsed.hostname}:{parsed.port}/{database}"
        )
        return client

    def _create_hive_connection(self, config: DatabaseConfig) -> Any:
        """
        Create Apache Hive connection (sync, runs in thread)

        URL format: hive://user:password@host:port/database
        """
        from pyhive import hive

        parsed = urlparse(config.connection_url)
        database = parsed.path.strip("/").split("/")[0] if parsed.path else "default"

        conn = hive.Connection(
            host=parsed.hostname,
            port=parsed.port or 10000,
            username=parsed.username,
            password=parsed.password,
            database=database,
            auth="CUSTOM" if parsed.password else "NONE",
        )

        logger.info(
            f"Created Hive connection: {parsed.hostname}:{parsed.port}/{database}"
        )
        return conn

    def _create_spark_connection(self, config: DatabaseConfig) -> Any:
        """
        Create Spark SQL connection via Thrift server (sync, runs in thread)

        URL format: spark://host:port/database
        Requires: Spark Thrift Server running
        """
        from pyhive import hive  # Spark Thrift uses Hive protocol

        parsed = urlparse(config.connection_url)
        database = parsed.path.strip("/").split("/")[0] if parsed.path else "default"

        conn = hive.Connection(
            host=parsed.hostname,
            port=parsed.port or 10001,  # Spark Thrift default
            username=parsed.username or "spark",
            database=database,
        )

        logger.info(
            f"Created Spark Thrift connection: {parsed.hostname}:{parsed.port}/{database}"
        )
        return conn

    def _create_duckdb_connection(self, config: DatabaseConfig) -> Any:
        """
        Create DuckDB connection (sync, runs in thread)

        URL formats:
        - duckdb:///path/to/database.duckdb  (file-based)
        - duckdb://:memory:                  (in-memory)
        """
        import duckdb

        parsed = urlparse(config.connection_url)

        # Handle :memory: special case
        if parsed.netloc == ":memory:" or config.connection_url.endswith(":memory:"):
            db_path = ":memory:"
        else:
            # Handle file path
            path = parsed.path
            if not path or path == "/":
                db_path = ":memory:"
            else:
                # Remove leading slash for Windows paths
                if path.startswith("/") and len(path) > 2 and path[2] == ":":
                    path = path[1:]
                db_path = path

        conn = (
            duckdb.connect(db_path, read_only=True)
            if db_path != ":memory:"
            else duckdb.connect()
        )

        logger.info(f"Created DuckDB connection: {db_path}")
        return conn

    def _create_sqlite_connection(self, config: DatabaseConfig) -> Any:
        """
        Create SQLite connection (sync, runs in thread)

        URL formats:
        - sqlite:///path/to/database.db  (file-based)
        - sqlite://:memory:              (in-memory)
        """
        import sqlite3

        parsed = urlparse(config.connection_url)

        # Handle :memory: special case
        if parsed.netloc == ":memory:" or config.connection_url.endswith(":memory:"):
            db_path = ":memory:"
        else:
            path = parsed.path
            if not path or path == "/":
                db_path = ":memory:"
            else:
                # Remove leading slash for Windows paths
                if path.startswith("/") and len(path) > 2 and path[2] == ":":
                    path = path[1:]
                db_path = path

        conn = sqlite3.connect(db_path)

        logger.info(f"Created SQLite connection: {db_path}")
        return conn

    def _create_cassandra_session(self, config: DatabaseConfig) -> Any:
        """
        Create Cassandra session (sync, runs in thread)

        URL format: cassandra://user:pass@host:port/keyspace
        """
        from urllib.parse import unquote

        from cassandra.auth import PlainTextAuthProvider
        from cassandra.cluster import Cluster

        parsed = urlparse(config.connection_url)
        keyspace = parsed.path.lstrip("/") if parsed.path else None

        auth_provider = None
        if parsed.username and parsed.password:
            auth_provider = PlainTextAuthProvider(
                username=unquote(parsed.username), password=unquote(parsed.password)
            )

        cluster = Cluster(
            contact_points=[parsed.hostname or "localhost"],
            port=parsed.port or 9042,
            auth_provider=auth_provider,
            protocol_version=4,
        )

        session = cluster.connect()

        # Store cluster reference for cleanup
        session._cluster_ref = cluster

        # Set default keyspace if provided
        if keyspace:
            session.set_keyspace(keyspace)

        # Verify connection
        session.execute("SELECT now() FROM system.local")

        logger.info(f"Created Cassandra session: {parsed.hostname}:{parsed.port}")
        return session

    def _get_dynamodb_client_kwargs(self, config: DatabaseConfig) -> Dict[str, Any]:
        """
        Build DynamoDB boto3 client keyword arguments (sync, runs in thread).

        Note: This method returns a configuration dict, not a client instance.
        The caller is responsible for creating the boto3 client using these kwargs.

        URL formats:
        - dynamodb://region/                     (uses default AWS credentials)
        - dynamodb://access_key:secret@region/   (explicit credentials)
        - dynamodb://localhost:8000/             (local DynamoDB)

        Returns:
            Dict of keyword arguments for boto3.client('dynamodb', **kwargs)
        """
        from urllib.parse import unquote

        parsed = urlparse(config.connection_url)

        client_kwargs = {}

        # Check if it's a local endpoint (has port)
        if parsed.port:
            client_kwargs["endpoint_url"] = f"http://{parsed.hostname}:{parsed.port}"
            client_kwargs["region_name"] = "local"
        else:
            # AWS DynamoDB
            client_kwargs["region_name"] = parsed.hostname or "us-east-1"

        # Add credentials if provided
        if parsed.username and parsed.password:
            client_kwargs["aws_access_key_id"] = parsed.username
            client_kwargs["aws_secret_access_key"] = unquote(parsed.password)

        logger.info(
            f"Created DynamoDB config: {client_kwargs.get('region_name', 'unknown')}"
        )
        return client_kwargs

    # =========================================================================
    # CONNECTION ACQUISITION
    # =========================================================================

    async def _get_or_create_async_pool(self, config: DatabaseConfig) -> Any:
        """Get existing pool or create new one for async databases"""
        pool_key = self._get_pool_key(config)

        # Fast path - pool exists
        if pool_key in self._async_pools:
            self._pool_stats[pool_key].last_used = datetime.now()
            return self._async_pools[pool_key]

        # Slow path - need to create pool
        lock = await self._get_or_create_lock(pool_key)
        async with lock:
            # Double-check after acquiring lock
            if pool_key in self._async_pools:
                return self._async_pools[pool_key]

            # Create pool based on type
            if config.db_type == "postgresql":
                pool = await self._create_postgres_pool(config)
            elif config.db_type == "mysql":
                pool = await self._create_mysql_pool(config)
            elif config.db_type == "mongodb":
                pool = await self._create_mongodb_client(config)
            else:
                raise ValueError(f"No async pool support for: {config.db_type}")

            self._async_pools[pool_key] = pool
            self._pool_stats[pool_key] = PoolStats()

            return pool

    async def _get_sync_connection(self, config: DatabaseConfig) -> Any:
        """Get connection for sync databases (runs in thread executor)"""
        loop = asyncio.get_event_loop()

        creators = {
            # Cloud Data Warehouses
            "snowflake": self._create_snowflake_connection,
            "bigquery": self._create_bigquery_client,
            "databricks": self._create_databricks_connection,
            "redshift": self._create_redshift_connection,
            # Enterprise Databases
            "sqlserver": self._create_sqlserver_connection,
            "oracle": self._create_oracle_connection,
            # Data Lakes & Analytics
            "athena": self._create_athena_connection,
            "trino": self._create_trino_connection,
            "presto": self._create_trino_connection,  # Presto uses same driver as Trino
            "clickhouse": self._create_clickhouse_connection,
            "hive": self._create_hive_connection,
            "spark": self._create_spark_connection,
            # Embedded Databases
            "duckdb": self._create_duckdb_connection,
            "sqlite": self._create_sqlite_connection,
            # NoSQL
            "cassandra": self._create_cassandra_session,
            "dynamodb": self._get_dynamodb_client_kwargs,
        }

        creator = creators.get(config.db_type)
        if not creator:
            raise ValueError(f"Unsupported database type: {config.db_type}")

        # Run sync connection in thread pool
        conn = await loop.run_in_executor(self._sync_executor, creator, config)

        pool_key = self._get_pool_key(config)
        if pool_key not in self._pool_stats:
            self._pool_stats[pool_key] = PoolStats()
        self._pool_stats[pool_key].last_used = datetime.now()
        self._pool_stats[pool_key].total_connections += 1

        return conn

    @asynccontextmanager
    async def get_connection(self, config: DatabaseConfig):
        """
        Get a database connection from the appropriate pool.

        Usage:
            async with pool_manager.get_connection(config) as conn:
                # Use connection
                result = await conn.fetch("SELECT 1")
        """
        pool_key = self._get_pool_key(config)
        conn = None

        try:
            # Async databases - use pooling
            if config.db_type in ("postgresql", "mysql"):
                pool = await self._get_or_create_async_pool(config)

                if config.db_type == "postgresql":
                    conn = await pool.acquire()
                    try:
                        # Phase 2 Day 3: pre-flight the connection before
                        # yielding. asyncpg does some validation internally,
                        # but a connection that died between acquire and
                        # use (mid-flight network blip, DB restart) will
                        # still be handed to the caller and fail mid-query.
                        # One SELECT 1 with a 2s timeout is cheap; on
                        # failure discard and re-acquire once.
                        if settings.FIX_POOL_PREFLIGHT:
                            try:
                                await asyncio.wait_for(
                                    conn.fetchval("SELECT 1"),
                                    timeout=2.0,
                                )
                            except Exception as e:
                                try:
                                    from app.api.metrics import record_fix_event
                                    record_fix_event("pool_preflight_discarded")
                                except Exception:
                                    pass
                                logger.warning(
                                    f"Pool pre-flight failed for {pool_key}, "
                                    f"discarding connection and retrying once: {e}"
                                )
                                # Discard dead connection and get a fresh one.
                                await pool.release(conn, discard=True)
                                conn = await pool.acquire()
                                # Don't double-validate; if this one is also
                                # dead, the caller's query will surface it.
                        yield conn
                    finally:
                        await pool.release(conn)

                elif config.db_type == "mysql":
                    conn = await pool.acquire()
                    try:
                        yield conn
                    finally:
                        pool.release(conn)

            # MongoDB - return client (has internal pooling)
            elif config.db_type == "mongodb":
                client = await self._get_or_create_async_pool(config)
                yield client

            # Sync databases - use thread executor
            else:
                conn = await self._get_sync_connection(config)
                try:
                    yield conn
                finally:
                    # Close sync connections after use
                    await self._close_sync_connection(conn, config.db_type)

            # Update stats
            if pool_key in self._pool_stats:
                self._pool_stats[pool_key].total_queries += 1

        except Exception as e:
            if pool_key in self._pool_stats:
                self._pool_stats[pool_key].errors += 1
            logger.error(f"Connection error for {config.db_type}: {e}")
            raise

    async def _close_sync_connection(self, conn: Any, db_type: str):
        """Close sync connection in thread executor"""
        loop = asyncio.get_event_loop()

        def close():
            try:
                # Special handling for Cassandra - need to shutdown cluster
                if db_type == "cassandra" and hasattr(conn, "_cluster_ref"):
                    conn._cluster_ref.shutdown()
                elif hasattr(conn, "close"):
                    conn.close()
            except Exception as e:
                logger.warning(f"Error closing {db_type} connection: {e}")

        await loop.run_in_executor(self._sync_executor, close)

    # =========================================================================
    # POOL LIFECYCLE MANAGEMENT
    # =========================================================================

    async def start_cleanup_task(self):
        """Start background task to cleanup idle pools"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Started pool cleanup task")

    async def _cleanup_loop(self):
        """Periodically cleanup idle pools"""
        while True:
            try:
                await asyncio.sleep(self.config.health_check_interval)
                await self._cleanup_idle_pools()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")

    async def _cleanup_idle_pools(self):
        """Close pools that have been idle too long"""
        now = datetime.now()
        pools_to_remove = []

        for pool_key, stats in self._pool_stats.items():
            idle_seconds = (now - stats.last_used).total_seconds()

            if idle_seconds > self.config.max_idle_time:
                pools_to_remove.append(pool_key)

        for pool_key in pools_to_remove:
            await self._close_pool(pool_key)
            logger.info(f"Closed idle pool: {pool_key[:8]}...")

    async def _close_pool(self, pool_key: str):
        """Close a specific pool"""
        if pool_key in self._async_pools:
            pool = self._async_pools.pop(pool_key)
            try:
                if hasattr(pool, "close"):
                    result = pool.close()
                    if asyncio.iscoroutine(result):
                        await result

                # wait_closed() is for asyncpg/aiomysql pools, but not Motor (MongoDB)
                # Motor clients clean up internally on close()
                if hasattr(pool, "wait_closed"):
                    # Check if it's a Motor client using isinstance
                    try:
                        from motor.motor_asyncio import AsyncIOMotorClient
                        is_motor = isinstance(pool, AsyncIOMotorClient)
                    except ImportError:
                        is_motor = False

                    if not is_motor:
                        await pool.wait_closed()
            except Exception as e:
                logger.warning(f"Error closing pool: {e}")

        self._pool_stats.pop(pool_key, None)
        self._pool_locks.pop(pool_key, None)

    async def close_all(self):
        """Close all pools (call on shutdown)"""
        logger.info("Closing all connection pools...")

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Close all async pools
        for pool_key in list(self._async_pools.keys()):
            await self._close_pool(pool_key)

        # Shutdown sync executor
        self._sync_executor.shutdown(wait=True)

        logger.info("All connection pools closed")

    # =========================================================================
    # HEALTH & STATS
    # =========================================================================

    def get_pool_stats(self) -> Dict[str, Dict]:
        """Get statistics for all pools"""
        stats = {}
        for pool_key, pool_stat in self._pool_stats.items():
            stats[pool_key] = {
                "created_at": pool_stat.created_at.isoformat(),
                "last_used": pool_stat.last_used.isoformat(),
                "total_queries": pool_stat.total_queries,
                "errors": pool_stat.errors,
                "idle_seconds": (datetime.now() - pool_stat.last_used).total_seconds(),
            }
        return stats

    async def health_check(self, config: DatabaseConfig) -> Dict[str, Any]:
        """Check health of a specific database connection"""
        try:
            async with self.get_connection(config) as conn:
                if config.db_type == "postgresql":
                    await conn.fetchval("SELECT 1")
                elif config.db_type == "mysql":
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT 1")
                elif config.db_type == "mongodb":
                    await conn.admin.command("ping")
                # Add health checks for sync DBs as needed

            return {"healthy": True, "message": "Connection OK"}
        except Exception as e:
            return {"healthy": False, "message": str(e)}


# Global singleton instance
pool_manager = ConnectionPoolManager()


# ---------------------------------------------------------------------------
# Phase 3b.1: native-async executor routing hook
# ---------------------------------------------------------------------------
#
# The legacy pool wraps every sync DB driver in a ThreadPoolExecutor. Cloud
# warehouses like BigQuery and Snowflake expose native async APIs
# (QueryJob polling, execute_async) — running an async executor inside a
# thread is doubly wasteful. Phase 3b.1 adds this helper; the drivers
# themselves are Phase 3b.3 / 3b.4 and register via the registry on import
# once their dependencies are available. This helper lets the pool
# manager (and ToolRegistry) short-circuit to the native-async path when
# a driver is registered.


def is_async_native_db(db_type: Optional[str]) -> bool:
    """
    True when an ``AsyncExecutorProtocol`` implementation is registered
    for ``db_type`` (case-insensitive). Callers check this before
    acquiring a pooled connection so async-native drivers can skip the
    ThreadPoolExecutor detour.
    """
    # Lazy import to avoid a circular dependency at module load.
    from app.services.async_executor_protocol import async_executor_registry

    return async_executor_registry.is_async_native(db_type)
