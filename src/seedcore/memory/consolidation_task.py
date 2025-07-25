import asyncio, os, time, numpy as np
import ray
from .backends.pgvector_backend import PgVectorStore
from .backends.neo4j_graph      import Neo4jGraph
from .holon_fabric     import HolonFabric
from .consolidation_worker import consolidate_batch

@ray.remote
def consolidation_worker(pg_dsn: str, neo_uri: str, neo_auth: tuple,
                         mw_snapshot: dict, tau: float, batch: int):
    async def _run():
        vec   = PgVectorStore(pg_dsn)
        graph = Neo4jGraph(neo_uri, auth=neo_auth)
        fabric= HolonFabric(vec, graph)
        return await consolidate_batch(fabric, mw_snapshot, tau, batch)
    return asyncio.run(_run()) 