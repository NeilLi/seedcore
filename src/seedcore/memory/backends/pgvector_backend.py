import asyncpg
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from typing import List
import json
from uuid import uuid4
import asyncio

class Holon(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    uuid: str = Field(default_factory=lambda: str(uuid4()))
    embedding: np.ndarray
    meta: dict

class PgVectorStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    async def _conn(self):
        return await asyncpg.connect(self.dsn)

    async def upsert(self, holon: Holon):
        import json
        q = """INSERT INTO holons (uuid, embedding, meta)
               VALUES ($1,$2::vector,$3)
               ON CONFLICT (uuid) DO UPDATE SET embedding=$2, meta=$3"""
        conn = await self._conn()
        try:
            vec_str = '[' + ','.join(str(x) for x in holon.embedding.tolist()) + ']'
            await conn.execute(q, holon.uuid, vec_str, json.dumps(holon.meta))
        finally:
            await conn.close()

    async def search(self, emb: np.ndarray, k: int = 10):
        q = """SELECT uuid, meta, embedding <-> $1::vector AS dist
               FROM holons ORDER BY dist LIMIT $2"""
        conn = await self._conn()
        try:
            # Convert numpy array to string format for PGVector
            vec_str = '[' + ','.join(str(x) for x in emb.tolist()) + ']'
            rows = await conn.fetch(q, vec_str, k)
            return rows
        finally:
            await conn.close() 

    async def _get_by_id_async(self, holon_id: str):
        q = "SELECT uuid, embedding, meta FROM holons WHERE uuid = $1"
        conn = await self._conn()
        try:
            row = await conn.fetchrow(q, holon_id)
            if row:
                return {
                    "id": str(row["uuid"]),  # Convert UUID to string
                    "embedding": row["embedding"],
                    "meta": json.loads(row["meta"]) if isinstance(row["meta"], str) else row["meta"]
                }
            return None
        finally:
            await conn.close()

    async def get_by_id(self, holon_id: str):
        q = "SELECT uuid, embedding, meta FROM holons WHERE uuid = $1"
        conn = await self._conn()
        try:
            row = await conn.fetchrow(q, holon_id)
            if row:
                return {
                    "id": str(row["uuid"]),  # Convert UUID to string
                    "embedding": row["embedding"],
                    "meta": json.loads(row["meta"]) if isinstance(row["meta"], str) else row["meta"]
                }
            return None
        finally:
            await conn.close()

    def get_by_id(self, holon_id: str):
        """
        Synchronous version of get_by_id for use in LongTermMemoryManager.
        """
        try:
            # Check if we're already in an event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, use asyncio.run_coroutine_threadsafe
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._get_by_id_async(holon_id))
                    return future.result()
            except RuntimeError:
                # No event loop running, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._get_by_id_async(holon_id))
                loop.close()
                return result
        except Exception as e:
            print(f"Error in synchronous get_by_id: {e}")
            return None 