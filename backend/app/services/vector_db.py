"""
QueryfyAI - Vector Database Service

Configurable vector storage with support for ChromaDB/Qdrant and multiple embedding providers
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_embedding_function():
    """Get the configured embedding function"""
    provider = settings.EMBEDDING_PROVIDER.lower()

    if provider == "none":
        logger.info("📝 Embeddings disabled - using simple text matching")
        return None

    elif provider == "openai":
        if not settings.OPENAI_API_KEY:
            logger.warning(
                "⚠️  OpenAI API key not set, falling back to local embeddings"
            )
            provider = "local"
        else:
            try:
                from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

                logger.info("🌐 Using OpenAI embeddings (text-embedding-ada-002)")
                return OpenAIEmbeddingFunction(
                    api_key=settings.OPENAI_API_KEY, model_name="text-embedding-ada-002"
                )
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI embeddings: {e}")
                provider = "local"

    if provider == "local":
        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            logger.info(f"🖥️  Using local embeddings ({settings.EMBEDDING_MODEL})")
            return DefaultEmbeddingFunction()
        except Exception as e:
            logger.error(f"Failed to initialize local embeddings: {e}")
            return None

    return None


class VectorDBService:
    """Configurable vector storage for efficient schema retrieval"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.client = None
        self.schema_collection = None
        self.query_collection = None
        self.negative_examples_collection = None
        self.db_type = "none"
        self._available = False

        try:
            self.embedding_fn = get_embedding_function()
            self._init_vector_db()
            self._available = True
        except Exception:
            logger.warning(
                "Vector DB initialization failed - running in degraded mode",
                exc_info=True,
            )
        self._initialized = True

    def _init_vector_db(self):
        """Initialize the configured vector database"""
        db_type = settings.VECTOR_DB_TYPE.lower()

        if db_type == "qdrant":
            self._init_qdrant()
        else:
            self._init_chromadb()

    def _init_chromadb(self):
        """Initialize ChromaDB"""
        import chromadb

        os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
        self.client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)

        collection_kwargs = {"metadata": {"hnsw:space": "cosine"}}
        if self.embedding_fn:
            collection_kwargs["embedding_function"] = self.embedding_fn

        self.schema_collection = self.client.get_or_create_collection(
            name="schema_embeddings", **collection_kwargs
        )

        self.query_collection = self.client.get_or_create_collection(
            name="query_history", **collection_kwargs
        )

        self.negative_examples_collection = self.client.get_or_create_collection(
            name="negative_examples", **collection_kwargs
        )

        self.db_type = "chromadb"
        logger.info(f"✓ ChromaDB initialized at {settings.CHROMA_PERSIST_DIR}")

    def _init_qdrant(self):
        """Initialize Qdrant"""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            if settings.QDRANT_URL:
                self.client = QdrantClient(
                    url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY
                )
            else:
                # In-memory for local development
                self.client = QdrantClient(":memory:")

            # Create collections if they don't exist
            collections = [c.name for c in self.client.get_collections().collections]

            vector_size = 384  # Default for all-MiniLM-L6-v2
            if settings.EMBEDDING_PROVIDER == "openai":
                vector_size = 1536  # OpenAI ada-002

            for collection_name in [
                "schema_embeddings",
                "query_history",
                "negative_examples",
            ]:
                if collection_name not in collections:
                    self.client.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(
                            size=vector_size, distance=Distance.COSINE
                        ),
                    )

            self.db_type = "qdrant"
            logger.info(f"✓ Qdrant initialized at {settings.QDRANT_URL or 'in-memory'}")

        except ImportError:
            logger.warning("Qdrant client not installed, falling back to ChromaDB")
            self._init_chromadb()
        except Exception as e:
            logger.error(f"Qdrant initialization failed: {e}, falling back to ChromaDB")
            self._init_chromadb()

    def _hash_connection(self, connection_url: str) -> str:
        """Create stable hash for connection URL (excluding credentials)"""
        sanitized = (
            connection_url.split("@")[-1] if "@" in connection_url else connection_url
        )
        return hashlib.sha256(sanitized.encode()).hexdigest()[:16]

    def _generate_embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Generate embeddings for texts"""
        if not self.embedding_fn:
            logger.warning("No embedding function available")
            return None
        try:
            logger.debug(f"Generating embeddings for {len(texts)} texts")
            result = self.embedding_fn(texts)
            if result is not None:
                logger.debug(
                    f"Generated {len(result)} embeddings, dimension: {len(result[0]) if result else 0}"
                )
            return result
        except Exception as e:
            logger.error(f"Embedding generation failed: {type(e).__name__}: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

    def update_table_in_schema(
        self,
        connection_url: str,
        table_dict: Dict[str, Any],
        *,
        item_type: str = "table",
    ) -> bool:
        """
        Replace a SINGLE table's (or collection's) entry in the vector
        DB without touching other tables for the same connection.

        Full ``store_schema`` deletes every entry for the
        connection_hash and re-adds them, which is too heavy when
        only one table's metadata went stale (e.g. a column-not-
        found error fired the auto-refresh, or NoSQL partition keys
        were missing on the indexed copy). This selective update
        rewrites only ``f"{conn_hash}_{table_name}"``.

        Args:
            connection_url: Connection URL (hashed for the entry key).
            table_dict: Same shape as one entry in ``schema["tables"]``
                (or ``schema["collections"]`` when item_type="collection").
                Must contain ``name``; everything else is best-effort.
            item_type: "table" or "collection" — controls metadata tag
                so consumers can tell the kinds apart.

        Returns:
            True on success, False on no-op (vector DB unavailable or
            unsupported db_type for the storage backend).

        Never raises — vector DB failures are logged and swallowed so
        a stale schema doesn't break the calling tool.
        """
        if not self._available:
            logger.debug("Vector DB not available, skipping update_table_in_schema")
            return False
        conn_hash = self._hash_connection(connection_url)
        table_name = table_dict.get("name")
        if not table_name:
            logger.warning(
                "update_table_in_schema: missing 'name' in table_dict, skipping"
            )
            return False

        # Same document shape as store_schema's table loop.
        if item_type == "collection":
            doc = f"Collection: {table_name}\n"
            doc += f"Fields: {', '.join([f['name'] + ' (' + f['type'] + ')' for f in table_dict.get('fields', [])])}\n"
            if table_dict.get("estimated_count"):
                doc += f"Estimated document count: {table_dict['estimated_count']}\n"
            if table_dict.get("indexes"):
                idx_names = [idx.get("name", "unknown") for idx in table_dict["indexes"]]
                doc += f"Indexes: {', '.join(idx_names)}"
        else:
            doc = f"Table: {table_name}\n"
            col_parts = []
            for c in table_dict.get("columns", []):
                col_desc = f"{c['name']} ({c['type']})"
                if c.get("key_type"):
                    col_desc += f" [{c['key_type']}]"
                col_parts.append(col_desc)
            doc += f"Columns: {', '.join(col_parts)}\n"
            if table_dict.get("partition_keys"):
                doc += f"Partition Keys: {', '.join(table_dict['partition_keys'])}\n"
            if table_dict.get("clustering_keys"):
                doc += f"Clustering Keys: {', '.join(table_dict['clustering_keys'])}\n"
            if table_dict.get("partition_key"):
                doc += f"Partition Key: {table_dict['partition_key']}\n"
            if table_dict.get("sort_key"):
                doc += f"Sort Key: {table_dict['sort_key']}\n"
            if table_dict.get("gsi"):
                gsi_names = [idx["name"] for idx in table_dict["gsi"]]
                doc += f"Global Secondary Indexes: {', '.join(gsi_names)}\n"
            if table_dict.get("lsi"):
                lsi_names = [idx["name"] for idx in table_dict["lsi"]]
                doc += f"Local Secondary Indexes: {', '.join(lsi_names)}\n"
            if table_dict.get("foreign_keys"):
                doc += f"Foreign Keys: {', '.join([fk['column'] + ' -> ' + fk.get('references_table', '') for fk in table_dict['foreign_keys']])}"

        metadata = {
            "connection_hash": conn_hash,
            "item_type": item_type,
            "name": table_name,
            "db_type": table_dict.get("db_type", "unknown"),
            "full_schema": json.dumps(table_dict)[:10000],
        }
        entry_id = f"{conn_hash}_{table_name}"

        try:
            if self.db_type == "chromadb":
                # Delete-then-add — ChromaDB's add() raises on duplicate IDs,
                # so a "replace" is two operations.
                try:
                    self.schema_collection.delete(ids=[entry_id])
                except Exception as e:
                    logger.debug(
                        f"update_table_in_schema: prior entry not present for "
                        f"{entry_id} (ok): {e}"
                    )
                self.schema_collection.add(
                    documents=[doc], metadatas=[metadata], ids=[entry_id]
                )
            elif self.db_type == "qdrant":
                from qdrant_client.models import PointStruct

                embeddings = self._generate_embeddings([doc])
                if not embeddings:
                    logger.warning(
                        "update_table_in_schema: embedding generation failed "
                        f"for {entry_id}"
                    )
                    return False
                self.client.upsert(
                    collection_name="schema_embeddings",
                    points=[
                        PointStruct(
                            id=hash(entry_id) % (2**63),
                            vector=embeddings[0],
                            payload={**metadata, "document": doc},
                        )
                    ],
                )
            else:
                logger.debug(
                    f"update_table_in_schema: storage backend "
                    f"{self.db_type!r} not supported for selective update"
                )
                return False

            logger.info(
                "vector_db.table_updated",
                extra={
                    "conn_hash": conn_hash[:8],
                    "table_name": table_name,
                    "item_type": item_type,
                    "db_type": metadata["db_type"],
                },
            )
            return True
        except Exception as e:
            logger.warning(
                f"update_table_in_schema failed for {entry_id}: {e}"
            )
            return False

    def store_schema(self, connection_url: str, schema: Dict[str, Any]):
        """Store schema with embeddings for similarity search"""
        if not self._available:
            logger.debug("Vector DB not available, skipping store_schema")
            return
        conn_hash = self._hash_connection(connection_url)
        db_type = schema.get("db_type", "unknown")

        logger.info(
            f"Storing schema for {db_type} database, conn_hash: {conn_hash[:8]}..."
        )

        # Delete existing entries for this connection
        if self.db_type == "chromadb":
            try:
                existing = self.schema_collection.get(
                    where={"connection_hash": conn_hash}
                )
                if existing["ids"]:
                    self.schema_collection.delete(ids=existing["ids"])
                    logger.info(
                        f"Deleted {len(existing['ids'])} existing entries for conn_hash {conn_hash[:8]}"
                    )
            except Exception as e:
                logger.debug(f"Failed to delete existing ChromaDB entries: {e}")
        elif self.db_type == "qdrant":
            try:
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                self.client.delete(
                    collection_name="schema_embeddings",
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="connection_hash", match=MatchValue(value=conn_hash)
                            )
                        ]
                    ),
                )
                logger.info(
                    f"Deleted existing entries for conn_hash {conn_hash[:8]} from Qdrant"
                )
            except Exception as e:
                logger.warning(f"Failed to delete existing Qdrant entries: {e}")

        # Prepare documents
        documents = []
        metadatas = []
        ids = []

        # Handle SQL tables (including Cassandra and DynamoDB which use 'tables')
        for table in schema.get("tables", []):
            table_name = table.get("name", "unknown")
            doc = f"Table: {table_name}\n"

            # Build column descriptions with key information
            col_parts = []
            for c in table.get("columns", []):
                col_desc = f"{c['name']} ({c['type']})"
                # Add key type for NoSQL databases (Cassandra/DynamoDB)
                if c.get("key_type"):
                    col_desc += f" [{c['key_type']}]"
                col_parts.append(col_desc)
            doc += f"Columns: {', '.join(col_parts)}\n"

            # Cassandra-specific: partition and clustering keys
            if table.get("partition_keys"):
                doc += f"Partition Keys: {', '.join(table['partition_keys'])}\n"
            if table.get("clustering_keys"):
                doc += f"Clustering Keys: {', '.join(table['clustering_keys'])}\n"

            # DynamoDB-specific: partition/sort key and indexes
            if table.get("partition_key"):
                doc += f"Partition Key: {table['partition_key']}\n"
            if table.get("sort_key"):
                doc += f"Sort Key: {table['sort_key']}\n"
            if table.get("gsi"):
                gsi_names = [idx["name"] for idx in table["gsi"]]
                doc += f"Global Secondary Indexes: {', '.join(gsi_names)}\n"
            if table.get("lsi"):
                lsi_names = [idx["name"] for idx in table["lsi"]]
                doc += f"Local Secondary Indexes: {', '.join(lsi_names)}\n"

            # SQL foreign keys
            if table.get("foreign_keys"):
                doc += f"Foreign Keys: {', '.join([fk['column'] + ' -> ' + fk.get('references_table', '') for fk in table['foreign_keys']])}"

            documents.append(doc)
            metadatas.append(
                {
                    "connection_hash": conn_hash,
                    "item_type": "table",
                    "name": table_name,
                    "db_type": db_type,
                    "full_schema": json.dumps(table)[:10000],
                }
            )
            ids.append(f"{conn_hash}_{table_name}")

        # Handle MongoDB collections
        for collection in schema.get("collections", []):
            collection_name = collection.get("name", "unknown")
            doc = f"Collection: {collection_name}\n"
            doc += f"Fields: {', '.join([f['name'] + ' (' + f['type'] + ')' for f in collection.get('fields', [])])}\n"
            if collection.get("estimated_count"):
                doc += f"Estimated document count: {collection['estimated_count']}\n"
            if collection.get("indexes"):
                idx_names = [
                    idx.get("name", "unknown") for idx in collection["indexes"]
                ]
                doc += f"Indexes: {', '.join(idx_names)}"

            documents.append(doc)
            metadatas.append(
                {
                    "connection_hash": conn_hash,
                    "item_type": "collection",
                    "name": collection_name,
                    "db_type": db_type,
                    "full_schema": json.dumps(collection)[:10000],
                }
            )
            ids.append(f"{conn_hash}_{collection_name}")

        if documents:
            if self.db_type == "chromadb":
                self.schema_collection.add(
                    documents=documents, metadatas=metadatas, ids=ids
                )
            elif self.db_type == "qdrant":
                embeddings = self._generate_embeddings(documents)
                if embeddings:
                    from qdrant_client.models import PointStruct

                    points = [
                        PointStruct(
                            id=hash(id_) % (2**63),
                            vector=emb,
                            payload={**meta, "document": doc},
                        )
                        for id_, emb, meta, doc in zip(
                            ids, embeddings, metadatas, documents
                        )
                    ]
                    self.client.upsert(
                        collection_name="schema_embeddings", points=points
                    )

            table_count = len(schema.get("tables", []))
            collection_count = len(schema.get("collections", []))
            logger.info(
                f"Stored {len(documents)} schema items ({table_count} tables, {collection_count} collections) for {db_type} database, conn_hash: {conn_hash[:8]}..."
            )
        else:
            logger.warning(
                f"No schema items to store for {db_type} database, conn_hash: {conn_hash[:8]}. Schema keys: {list(schema.keys())}"
            )

    def get_relevant_schema(
        self, connection_url: str, query: str, max_items: int = 15
    ) -> str:
        """Retrieve relevant schema parts based on query similarity"""
        if not self._available:
            return ""
        conn_hash = self._hash_connection(connection_url)
        logger.info(
            f"get_relevant_schema: conn_hash={conn_hash}, query={query[:50] if query else 'None'}, db_type={self.db_type}"
        )

        try:
            if self.db_type == "chromadb":
                results = self.schema_collection.query(
                    query_texts=(
                        [query] if query else ["database schema tables columns"]
                    ),
                    n_results=max_items,
                    where={"connection_hash": conn_hash},
                )
                metadatas = results.get("metadatas", [[]])[0]

            elif self.db_type == "qdrant":
                logger.info("Qdrant search: generating embeddings for query...")
                embeddings = self._generate_embeddings([query or "database schema"])
                if not embeddings:
                    logger.error(
                        f"FAILED to generate embeddings for query: {query[:50] if query else 'None'}"
                    )
                    return "No schema information available"

                logger.info(f"Embeddings generated, dimension: {len(embeddings[0])}")

                from qdrant_client.models import FieldCondition, Filter, MatchValue

                logger.info(f"Searching Qdrant for conn_hash: {conn_hash}")
                try:
                    # Use query_points (replaces deprecated search method in qdrant-client >= 1.16)
                    results = self.client.query_points(
                        collection_name="schema_embeddings",
                        query=embeddings[0],
                        query_filter=Filter(
                            must=[
                                FieldCondition(
                                    key="connection_hash",
                                    match=MatchValue(value=conn_hash),
                                )
                            ]
                        ),
                        limit=max_items,
                    )
                    logger.info(f"Qdrant search returned {len(results.points)} results")
                except Exception as search_err:
                    logger.error(f"Qdrant search FAILED: {search_err}")
                    raise

                metadatas = [r.payload for r in results.points]

        except Exception as e:
            logger.error(f"Schema query failed: {e}")
            return "No schema information available"

        if not metadatas:
            return "No schema information available"

        schema_text = "DATABASE SCHEMA:\n" + "=" * 50 + "\n\n"

        for metadata in metadatas:
            try:
                item = json.loads(metadata.get("full_schema", "{}"))
                item_type = metadata.get("item_type", "table")
                item_db_type = metadata.get("db_type", "")

                if item_type == "table":
                    schema_text += f"TABLE: {item.get('name', 'unknown')}"
                    if item.get("schema"):
                        schema_text += f" (schema: {item['schema']})"
                    schema_text += "\n"

                    # Cassandra-specific: show partition and clustering keys
                    if item.get("partition_keys"):
                        schema_text += f"PARTITION KEYS: {', '.join(item['partition_keys'])} (REQUIRED in WHERE clause)\n"
                    if item.get("clustering_keys"):
                        schema_text += f"CLUSTERING KEYS: {', '.join(item['clustering_keys'])} (determines sort order)\n"

                    # DynamoDB-specific: show partition/sort keys
                    if item.get("partition_key"):
                        schema_text += f"PARTITION KEY: {item['partition_key']} (REQUIRED in WHERE clause)\n"
                    if item.get("sort_key"):
                        schema_text += (
                            f"SORT KEY: {item['sort_key']} (use for range queries)\n"
                        )

                    schema_text += "COLUMNS:\n"
                    for col in item.get("columns", []):
                        # Check if column is a primary key
                        pk = ""
                        if col["name"] in item.get("primary_keys", []):
                            pk = " [PK]"
                        elif col.get("key_type"):
                            # NoSQL key types (partition_key, clustering, PARTITION, SORT)
                            pk = f" [{col['key_type'].upper()}]"

                        nullable = "" if col.get("nullable", True) else " NOT NULL"

                        # Include sample values for categorical columns
                        sample_vals = ""
                        if col.get("sample_values"):
                            vals = ", ".join(f"'{v}'" for v in col["sample_values"][:5])
                            if len(col["sample_values"]) > 5:
                                vals += ", ..."
                            sample_vals = f" [values: {vals}]"

                        # Include column comment if available
                        comment = f" -- {col['comment']}" if col.get("comment") else ""
                        schema_text += f"  - {col['name']}: {col['type']}{pk}{nullable}{sample_vals}{comment}\n"

                    # SQL foreign keys
                    if item.get("foreign_keys"):
                        schema_text += "FOREIGN KEYS:\n"
                        for fk in item["foreign_keys"]:
                            schema_text += f"  - {fk['column']} -> {fk.get('references_table')}.{fk.get('references_column')}\n"

                    # DynamoDB indexes
                    if item.get("gsi"):
                        schema_text += "GLOBAL SECONDARY INDEXES (GSI):\n"
                        for gsi in item["gsi"]:
                            keys = ", ".join(
                                [
                                    f"{k['name']} ({k['key_type']})"
                                    for k in gsi.get("keys", [])
                                ]
                            )
                            schema_text += f"  - {gsi['name']}: {keys}\n"
                    if item.get("lsi"):
                        schema_text += "LOCAL SECONDARY INDEXES (LSI):\n"
                        for lsi in item["lsi"]:
                            keys = ", ".join(
                                [
                                    f"{k['name']} ({k['key_type']})"
                                    for k in lsi.get("keys", [])
                                ]
                            )
                            schema_text += f"  - {lsi['name']}: {keys}\n"

                    # Cassandra secondary indexes
                    if item.get("indexes") and item_db_type == "cassandra":
                        schema_text += "SECONDARY INDEXES:\n"
                        for idx in item["indexes"]:
                            schema_text += (
                                f"  - {idx['name']}: {idx.get('target', '')}\n"
                            )

                elif item_type == "collection":
                    # MongoDB collections
                    schema_text += f"COLLECTION: {item.get('name', 'unknown')}\n"
                    if item.get("estimated_count"):
                        schema_text += (
                            f"ESTIMATED DOCUMENTS: {item['estimated_count']}\n"
                        )

                    schema_text += "FIELDS:\n"
                    for field in item.get("fields", []):
                        nullable = " (nullable)" if field.get("nullable") else ""

                        # Include sample values for categorical fields (same as SQL columns)
                        sample_vals = ""
                        if field.get("sample_values"):
                            vals = ", ".join(
                                f"'{v}'" for v in field["sample_values"][:5]
                            )
                            if len(field["sample_values"]) > 5:
                                vals += ", ..."
                            sample_vals = f" [values: {vals}]"

                        schema_text += f"  - {field['name']}: {field['type']}{nullable}{sample_vals}\n"

                    if item.get("indexes"):
                        schema_text += "INDEXES:\n"
                        for idx in item["indexes"]:
                            keys = ", ".join(str(k) for k in idx.get("keys", []))
                            schema_text += (
                                f"  - {idx.get('name', 'unknown')}: [{keys}]\n"
                            )

                schema_text += "\n"
            except Exception as e:
                logger.debug(f"Failed to parse schema metadata: {e}")
                continue

        return schema_text

    def get_full_schema_text(self, connection_url: str) -> str:
        """Get complete schema as formatted text"""
        return self.get_relevant_schema(connection_url, "", max_items=100)

    def store_successful_query(
        self, connection_url: str, query: str, sql: str, rating: int = 0
    ):
        """Store successful query for few-shot learning"""
        if not self._available:
            return
        conn_hash = self._hash_connection(connection_url)
        query_id = f"{conn_hash}_{hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()[:8]}"

        try:
            if self.db_type == "chromadb":
                self.query_collection.upsert(
                    documents=[f"Question: {query}\nSQL: {sql}"],
                    metadatas=[
                        {
                            "connection_hash": conn_hash,
                            "natural_query": query[:500],
                            "sql": sql[:2000],
                            "rating": rating,
                        }
                    ],
                    ids=[query_id],
                )
            elif self.db_type == "qdrant":
                embeddings = self._generate_embeddings(
                    [f"Question: {query}\nSQL: {sql}"]
                )
                if embeddings:
                    from qdrant_client.models import PointStruct

                    self.client.upsert(
                        collection_name="query_history",
                        points=[
                            PointStruct(
                                id=hash(query_id) % (2**63),
                                vector=embeddings[0],
                                payload={
                                    "connection_hash": conn_hash,
                                    "natural_query": query[:500],
                                    "sql": sql[:2000],
                                    "rating": rating,
                                },
                            )
                        ],
                    )
        except Exception as e:
            logger.error(f"Failed to store query: {e}")

    def find_similar_queries(
        self, connection_url: str, query: str, n: int = 3
    ) -> List[Dict]:
        """
        Find similar past queries for few-shot examples.

        Fetches more results than needed and prioritizes high-rated queries
        (from user feedback) to improve few-shot learning quality.
        """
        if not self._available:
            return []
        conn_hash = self._hash_connection(connection_url)
        # Fetch more results to allow for rating-based filtering
        fetch_limit = n * 3

        try:
            results = []

            if self.db_type == "chromadb":
                query_results = self.query_collection.query(
                    query_texts=[query],
                    n_results=fetch_limit,
                    where={"connection_hash": conn_hash},
                )
                if not query_results["metadatas"] or not query_results["metadatas"][0]:
                    return []
                results = query_results["metadatas"][0]

            elif self.db_type == "qdrant":
                embeddings = self._generate_embeddings([query])
                if not embeddings:
                    return []

                from qdrant_client.models import FieldCondition, Filter, MatchValue

                # Use query_points (replaces deprecated search method in qdrant-client >= 1.16)
                query_results = self.client.query_points(
                    collection_name="query_history",
                    query=embeddings[0],
                    query_filter=Filter(
                        must=[
                            FieldCondition(
                                key="connection_hash", match=MatchValue(value=conn_hash)
                            )
                        ]
                    ),
                    limit=fetch_limit,
                )
                results = [r.payload for r in query_results.points]

            # Sort by rating (higher is better) to prioritize positively-rated queries
            # Queries without rating default to 0
            results.sort(key=lambda x: x.get("rating", 0), reverse=True)

            return results[:n]

        except Exception as e:
            logger.error(f"Similar query search failed: {e}")
            return []

    def store_failed_query(
        self,
        connection_url: str,
        question: str,
        failed_sql: str,
        error_message: str,
        error_type: str,
        context: Optional[Dict] = None,
    ) -> str:
        """
        Store a failed query for learning (negative examples).

        These are used to prevent the LLM from repeating the same mistakes
        by including anti-patterns in the prompt.

        Args:
            connection_url: Database connection URL
            question: The natural language question
            failed_sql: The SQL that failed
            error_message: The error message from the database
            error_type: Classified error type (syntax, semantic, timeout, etc.)
            context: Optional additional context

        Returns:
            The ID of the stored failure
        """
        if not self._available:
            return ""
        conn_hash = self._hash_connection(connection_url)
        failure_id = f"{conn_hash}_{hashlib.md5((question + failed_sql).encode(), usedforsecurity=False).hexdigest()[:8]}"

        metadata = {
            "connection_hash": conn_hash,
            "question": question[:500],
            "failed_sql": failed_sql[:2000],
            "error_message": error_message[:1000],
            "error_type": error_type,
            "timestamp": datetime.now().isoformat(),
        }
        if context:
            metadata["context"] = json.dumps(context)[:1000]

        document = (
            f"Question: {question}\nFailed SQL: {failed_sql}\nError: {error_message}"
        )

        try:
            if self.db_type == "chromadb":
                self.negative_examples_collection.upsert(
                    documents=[document], metadatas=[metadata], ids=[failure_id]
                )
            elif self.db_type == "qdrant":
                embeddings = self._generate_embeddings([document])
                if embeddings:
                    from qdrant_client.models import PointStruct

                    self.client.upsert(
                        collection_name="negative_examples",
                        points=[
                            PointStruct(
                                id=hash(failure_id) % (2**63),
                                vector=embeddings[0],
                                payload={**metadata, "document": document},
                            )
                        ],
                    )

            logger.info(
                f"Stored failed query: {failure_id[:16]} (error_type: {error_type})"
            )
            return failure_id

        except Exception as e:
            logger.error(f"Failed to store failed query: {e}")
            return ""

    def find_similar_failures(
        self, connection_url: str, question: str, limit: int = 3
    ) -> List[Dict]:
        """
        Find similar past failures to avoid repeating mistakes.

        Returns failed queries with similar questions so the LLM can
        learn from past errors and avoid similar pitfalls.

        Args:
            connection_url: Database connection URL
            question: The natural language question
            limit: Maximum number of failures to return

        Returns:
            List of failed query records with question, failed_sql, error_message, error_type
        """
        if not self._available:
            return []
        conn_hash = self._hash_connection(connection_url)

        try:
            results = []

            if self.db_type == "chromadb":
                query_results = self.negative_examples_collection.query(
                    query_texts=[question],
                    n_results=limit,
                    where={"connection_hash": conn_hash},
                )
                if query_results["metadatas"] and query_results["metadatas"][0]:
                    results = query_results["metadatas"][0]

            elif self.db_type == "qdrant":
                embeddings = self._generate_embeddings([question])
                if not embeddings:
                    return []

                from qdrant_client.models import FieldCondition, Filter, MatchValue

                query_results = self.client.query_points(
                    collection_name="negative_examples",
                    query=embeddings[0],
                    query_filter=Filter(
                        must=[
                            FieldCondition(
                                key="connection_hash", match=MatchValue(value=conn_hash)
                            )
                        ]
                    ),
                    limit=limit,
                )
                results = [r.payload for r in query_results.points]

            # Format results for use in prompts
            formatted = []
            for r in results:
                formatted.append(
                    {
                        "question": r.get("question", ""),
                        "failed_sql": r.get("failed_sql", ""),
                        "error_message": r.get("error_message", ""),
                        "error_type": r.get("error_type", "unknown"),
                    }
                )

            logger.debug(f"Found {len(formatted)} similar failures for question")
            return formatted

        except Exception as e:
            logger.error(f"Similar failure search failed: {e}")
            return []


# Singleton instance
vector_db = VectorDBService()
