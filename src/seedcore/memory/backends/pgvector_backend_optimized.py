import asyncpg
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any
import json
from uuid import uuid4
import asyncio
import time

class Holon(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    uuid: str = Field(default_factory=lambda: str(uuid4()))
    embedding: np.ndarray
    meta: dict

class PgVectorStoreOptimized:
    def __init__(self, dsn: str, pool_size: int = 10):
        self.dsn = dsn
        self.pool_size = pool_size
        self._pool = None
        self._init_lock = asyncio.Lock()
        
    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            async with self._init_lock:
                if self._pool is None:
                    print(f"🔌 Creating connection pool (size: {self.pool_size})...")
                    start_time = time.time()
                    self._pool = await asyncpg.create_pool(
                        self.dsn,
                        min_size=2,
                        max_size=self.pool_size,
                        command_timeout=30
                    )
                    elapsed = time.time() - start_time
                    print(f"✅ Connection pool created in {elapsed:.2f}s")
        return self._pool

    async def _conn(self):
        """Get connection from pool."""
        pool = await self._get_pool()
        return await pool.acquire()

    async def upsert(self, holon: Holon) -> bool:
        """Optimized upsert with connection pooling."""
        q = """INSERT INTO holons (uuid, embedding, meta)
               VALUES ($1,$2::vector,$3)
               ON CONFLICT (uuid) DO UPDATE SET embedding=$2, meta=$3"""
        
        start_time = time.time()
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                vec_str = '[' + ','.join(str(x) for x in holon.embedding.tolist()) + ']'
                await conn.execute(q, holon.uuid, vec_str, json.dumps(holon.meta))
                elapsed = time.time() - start_time
                print(f"✅ Upsert completed in {elapsed:.2f}s")
                return True
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Upsert failed in {elapsed:.2f}s: {e}")
            return False

    async def search(self, emb: np.ndarray, k: int = 10):
        """Optimized similarity search."""
        q = """SELECT uuid, meta, embedding <-> $1::vector AS dist
               FROM holons ORDER BY dist LIMIT $2"""
        
        start_time = time.time()
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                vec_str = '[' + ','.join(str(x) for x in emb.tolist()) + ']'
                rows = await conn.fetch(q, vec_str, k)
                elapsed = time.time() - start_time
                print(f"✅ Search completed in {elapsed:.2f}s")
                return rows
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Search failed in {elapsed:.2f}s: {e}")
            return []

    async def get_by_id(self, holon_id: str) -> Optional[Dict[str, Any]]:
        """Optimized get by ID with connection pooling."""
        q = "SELECT uuid, embedding, meta FROM holons WHERE uuid = $1"
        
        start_time = time.time()
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(q, holon_id)
                elapsed = time.time() - start_time
                print(f"✅ Get by ID completed in {elapsed:.2f}s")
                
                if row:
                    return {
                        "id": str(row["uuid"]),
                        "embedding": row["embedding"],
                        "meta": json.loads(row["meta"]) if isinstance(row["meta"], str) else row["meta"]
                    }
                return None
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Get by ID failed in {elapsed:.2f}s: {e}")
            return None

    def get_by_id_sync(self, holon_id: str) -> Optional[Dict[str, Any]]:
        """Synchronous version for compatibility."""
        try:
            # Check if we're already in an event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, use asyncio.run_coroutine_threadsafe
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.get_by_id(holon_id))
                    return future.result()
            except RuntimeError:
                # No event loop running, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self.get_by_id(holon_id))
                loop.close()
                return result
        except Exception as e:
            print(f"Error in synchronous get_by_id: {e}")
            return None

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None 