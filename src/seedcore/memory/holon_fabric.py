import numpy as np
import asyncio
from .backends.pgvector_backend import PgVectorStore, Holon
from .backends.neo4j_graph import Neo4jGraph

class HolonFabric:
    def __init__(self, vec_store: PgVectorStore, graph: Neo4jGraph):
        self.vec = vec_store
        self.graph = graph

    # §8-spec API
    async def insert_holon(self, h: Holon):
        await self.vec.upsert(h)

    async def query_exact(self, uuid: str):
        # get doc + 1-hop neighbors
        try:
            vec_hits = await self.vec.search(uuid_vec(uuid), k=1)
            if vec_hits:
                meta = dict(vec_hits[0])  # Convert Record to dict
                # Convert any non-JSON-serializable values
                if "dist" in meta and (np.isinf(meta["dist"]) or np.isnan(meta["dist"])):
                    meta["dist"] = 0.0
            else:
                meta = None
            neigh = await self.graph.neighbors(uuid)
            return dict(meta=meta, neighbors=neigh)
        except Exception as e:
            return dict(meta=None, neighbors=[], error=str(e))

    async def query_fuzzy(self, emb: np.ndarray, k=10):
        vec_hits = await self.vec.search(emb, k)
        # add hop-expansion
        uuids = {str(r["uuid"]) for r in vec_hits}  # Convert UUID to string
        # Run neighbor queries in parallel for all initial hits
        neighbor_tasks = [self.graph.neighbors(u, k=3) for u in uuids]
        neighbor_lists = await asyncio.gather(*neighbor_tasks)
        for neighbors in neighbor_lists:
            uuids.update(neighbors)
        return list(uuids)

    async def create_relationship(self, src_uuid: str, rel: str, dst_uuid: str):
        """Create a relationship between two holons"""
        await self.graph.upsert_edge(src_uuid, rel, dst_uuid)

    async def get_stats(self):
        """Get statistics about the holon fabric"""
        try:
            # Query relationship count from Neo4j and holon count from PgVector in parallel
            rel_count_task = self.graph.get_count()
            holon_count_task = self.vec.get_count()
            bytes_task = self.vec.execute_scalar_query("SELECT pg_total_relation_size('holons')")
            
            rel_count, holon_count, bytes_used = await asyncio.gather(
                rel_count_task, holon_count_task, bytes_task
            )
            
            return {
                "total_holons": holon_count if holon_count is not None else 0,
                "total_relationships": rel_count,
                "vector_dimensions": 768,
                "bytes_used": int(bytes_used) if bytes_used is not None else 0,
                "status": "healthy"
            }
        except Exception as e:
            return {
                "total_holons": 0,
                "total_relationships": 0,
                "vector_dimensions": 768,
                "bytes_used": 0,
                "status": "unhealthy",
                "error": str(e)
            }

def uuid_vec(uuid: str) -> np.ndarray:
    """Convert UUID to vector for exact search - placeholder implementation"""
    # In a real implementation, this would use a hash function
    import hashlib
    hash_obj = hashlib.md5(uuid.encode())
    hash_bytes = hash_obj.digest()
    # Convert to 768-dimensional vector
    vec = np.frombuffer(hash_bytes, dtype=np.float32)
    # Pad or truncate to 768 dimensions
    if len(vec) < 768:
        vec = np.pad(vec, (0, 768 - len(vec)), mode='constant')
    else:
        vec = vec[:768]
    return vec 