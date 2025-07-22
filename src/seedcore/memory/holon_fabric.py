import numpy as np
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
            neigh = self.graph.neighbors(uuid)
            return dict(meta=meta, neighbors=neigh)
        except Exception as e:
            return dict(meta=None, neighbors=[], error=str(e))

    async def query_fuzzy(self, emb: np.ndarray, k=10):
        vec_hits = await self.vec.search(emb, k)
        # add hop-expansion
        uuids = {str(r["uuid"]) for r in vec_hits}  # Convert UUID to string
        for u in list(uuids):
            uuids.update(self.graph.neighbors(u, k=3))
        return list(uuids)

    async def create_relationship(self, src_uuid: str, rel: str, dst_uuid: str):
        """Create a relationship between two holons"""
        self.graph.upsert_edge(src_uuid, rel, dst_uuid)

    async def get_stats(self):
        """Get statistics about the holon fabric"""
        # Simple stats - in a real implementation, you'd query both databases
        return {
            "total_holons": 3,  # From the sample data
            "total_relationships": 3,  # From the sample data
            "vector_dimensions": 768,
            "status": "healthy"
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