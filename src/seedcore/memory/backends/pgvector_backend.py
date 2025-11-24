import asyncpg
import numpy as np
import json
import asyncio
import time
import logging
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any, Iterable
from uuid import uuid4

logger = logging.getLogger(__name__)

class Holon(BaseModel):
    """
    Pydantic model for a Holon, representing the data structure
    for vector storage.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    uuid: str = Field(default_factory=lambda: str(uuid4()))
    embedding: np.ndarray
    meta: dict

class PgVectorStore:
    """
    Optimized, async-native PgVector backend using a connection pool.
    
    This class manages all interactions with the PostgreSQL database
    housing the 'holons' table.
    """
    def __init__(self, dsn: str, pool_size: int = 10, pool_min_size: int = 2):
        self.dsn = dsn
        self.pool_size = pool_size
        self.pool_min_size = pool_min_size
        self._pool: Optional[asyncpg.Pool] = None
        self._init_lock = asyncio.Lock()
        
    async def _get_pool(self) -> asyncpg.Pool:
        """
        Lazily initialize and return the asyncpg connection pool.
        """
        if self._pool is None:
            async with self._init_lock:
                # Check again in case another coroutine initialized
                # the pool while we were waiting for the lock.
                if self._pool is None:
                    logger.info(f"Creating connection pool (min: {self.pool_min_size}, max: {self.pool_size})...")
                    start_time = time.time()
                    try:
                        self._pool = await asyncpg.create_pool(
                            self.dsn,
                            min_size=self.pool_min_size,
                            max_size=self.pool_size,
                            command_timeout=30,
                            # Automatically encode/decode JSON
                            init=self._setup_json_codec
                        )
                        elapsed = time.time() - start_time
                        logger.info(f"Connection pool created in {elapsed:.2f}s")
                    except Exception as e:
                        logger.critical(f"Failed to create connection pool: {e}")
                        raise
        return self._pool

    @staticmethod
    async def _setup_json_codec(conn):
        """Set up JSON codec for the connection."""
        await conn.set_type_codec(
            'jsonb',
            encoder=json.dumps,
            decoder=json.loads,
            schema='pg_catalog'
        )

    @staticmethod
    def _embedding_to_str(embedding: np.ndarray) -> str:
        """Utility to convert numpy array to pgvector string format."""
        return '[' + ','.join(str(x) for x in embedding.tolist()) + ']'

    async def upsert(self, holon: Holon) -> bool:
        """
        Inserts or updates a single holon in the database.
        """
        q = """
            INSERT INTO holons (uuid, embedding, meta)
            VALUES ($1, $2::vector, $3)
            ON CONFLICT (uuid) DO UPDATE SET
            embedding = EXCLUDED.embedding,
            meta = EXCLUDED.meta
            """
        
        try:
            pool = await self._get_pool()
            vec_str = self._embedding_to_str(holon.embedding)
            async with pool.acquire() as conn:
                await conn.execute(q, holon.uuid, vec_str, holon.meta)
            return True
        except Exception as e:
            logger.error(f"Upsert failed for holon {holon.uuid}: {e}", exc_info=True)
            return False

    async def search(self, emb: np.ndarray, k: int = 10, filters: Optional[Dict[str, Any]] = None) -> List[asyncpg.Record]:
        """
        Performs vector similarity search with optional metadata filtering.
        Returns raw asyncpg.Record objects.
        
        Args:
            emb: Query embedding vector
            k: Number of results to return
            filters: Optional filter dictionary. Supports:
                - "or": List of filter conditions (each is a dict with keys like "scope", "access_policy", "entity_id")
        """
        where_clauses = []
        params = [emb]  # First param is always the embedding vector
        param_idx = 2  # Start from $2 since $1 is the embedding
        
        # Build WHERE clause from filters
        if filters and "or" in filters:
            or_conditions = []
            for condition in filters["or"]:
                if "scope" in condition:
                    if condition["scope"] == "global":
                        or_conditions.append("meta->>'scope' = 'global'")
                    elif condition["scope"] == "organ" and "access_policy" in condition:
                        or_conditions.append(
                            f"(meta->>'scope' = 'organ' AND ${param_idx} = ANY(SELECT jsonb_array_elements_text(meta->'access_policy')))"
                        )
                        params.append(condition["access_policy"])
                        param_idx += 1
                    elif condition["scope"] == "entity" and "entity_id" in condition:
                        entity_filter = condition["entity_id"]
                        if isinstance(entity_filter, dict) and "in" in entity_filter:
                            # Handle "in" operator for entity_id
                            entity_ids = entity_filter["in"]
                            or_conditions.append(
                                f"(meta->>'scope' = 'entity' AND meta->>'entity_id' = ANY(${param_idx}::text[]))"
                            )
                            params.append(entity_ids)
                            param_idx += 1
                        else:
                            or_conditions.append(
                                f"(meta->>'scope' = 'entity' AND meta->>'entity_id' = ${param_idx})"
                            )
                            params.append(entity_filter)
                            param_idx += 1
            
            if or_conditions:
                where_clauses.append(f"({' OR '.join(or_conditions)})")
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Add limit parameter
        params.append(k)
        limit_param = param_idx
        
        q = f"""
            SELECT uuid, meta, embedding <-> $1::vector AS dist
            FROM holons 
            {where_sql}
            ORDER BY dist 
            LIMIT ${limit_param}
            """
        
        try:
            pool = await self._get_pool()
            vec_str = self._embedding_to_str(emb)
            params[0] = vec_str  # Replace embedding numpy array with string
            async with pool.acquire() as conn:
                return await conn.fetch(q, *params)
        except Exception as e:
            logger.error(f"Vector search failed: {e}", exc_info=True)
            return []

    async def get_by_id(self, holon_id: str) -> Optional[Holon]:
        """
        Retrieves a single holon by its UUID.
        Returns a parsed Holon object.
        """
        q = "SELECT uuid, embedding, meta FROM holons WHERE uuid = $1"
        
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(q, holon_id)
                
            if row:
                return Holon(
                    uuid=str(row["uuid"]),
                    embedding=np.array(row["embedding"]),
                    meta=row["meta"] # Should be auto-parsed as dict
                )
            return None
        except Exception as e:
            logger.error(f"Get by ID failed for {holon_id}: {e}", exc_info=True)
            return None

    async def get_by_ids(self, uuids: List[str]) -> List[Holon]:
        """
        Retrieves a batch of holons by their UUIDs.
        """
        q = "SELECT uuid, embedding, meta FROM holons WHERE uuid = ANY($1::uuid[])"
        
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(q, uuids)
            
            return [
                Holon(
                    uuid=str(row["uuid"]),
                    embedding=np.array(row["embedding"]),
                    meta=row["meta"]
                ) for row in rows
            ]
        except Exception as e:
            logger.error(f"Get by IDs failed: {e}", exc_info=True)
            return []

    async def get_count(self) -> int:
        """
        Maintains a count of all holons in the database.
        Required for `HolonFabric.get_stats()` and `cost_vq`.
        """
        q = "SELECT count(*) FROM holons"
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # fetchval returns the first column of the first row
                count = await conn.fetchval(q)
                return int(count) if count is not None else 0
        except Exception as e:
            logger.error(f"Get count failed: {e}", exc_info=True)
            return 0

    async def execute_scalar_query(self, query: str) -> Any:
        """
        Executes a query that is expected to return a single scalar value.
        Required for `HolonFabric.get_stats()` to get `bytes_used`.
        
        Example: "SELECT pg_total_relation_size('holons')"
        
        NOTE: Use with caution. Ensure query is safe.
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                return await conn.fetchval(query)
        except Exception as e:
            logger.error(f"Execute scalar query failed: {e}", exc_info=True)
            return None

    async def close(self):
        """Close the connection pool gracefully."""
        if self._pool:
            logger.info("Closing connection pool...")
            await self._pool.close()
            self._pool = None
            logger.info("Connection pool closed.") 