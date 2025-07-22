# stats.py – helpers to pull numbers from each backend
import asyncpg, time, math
from neo4j import GraphDatabase

def safe_json_number(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val

EMB_DIM = 768            # keep in sync with your schema

class StatsCollector:
    def __init__(self, pg_dsn: str, neo_uri: str, neo_auth: tuple, mw_ref: dict):
        self.pg_dsn, self.neo_uri, self.neo_auth = pg_dsn, neo_uri, neo_auth
        self.mw = mw_ref            # in‑memory Tier‑1 cache (Mw)

    async def _pg(self):
        return await asyncpg.connect(self.pg_dsn)

    # ---------- Tier – Mw (Python dict) -----------------
    def mw_stats(self):
        now = time.time()
        ages = [now - m["ts"] for m in self.mw.values()] or [0]
        return {
            "count": len(self.mw),
            "avg_staleness_s": round(sum(ages)/len(ages), 2),
        }

    # ---------- Tier – Mlt (pgvector) -------------------
    async def mlt_stats(self):
        q = """
        SELECT COUNT(*)                       AS n,
               AVG(EXTRACT(EPOCH FROM now() - created_at)) AS staleness,
               AVG(octet_length(meta->>'raw_bytes')::float /
                   octet_length(meta->>'stored_bytes')::float) AS compress
        FROM   holons;
        """
        c = await self._pg()
        try:
            n, stale, compr = await c.fetchrow(q)
        finally:
            await c.close()
        return {
            "count": safe_json_number(n),
            "avg_staleness_s": safe_json_number(round(stale or 0, 2)),
            "compress_ratio": safe_json_number(round(compr, 3) if compr is not None else None)
        }

    # ---------- Tier – relationships (Neo4j) ------------
    def rel_stats(self):
        with GraphDatabase.driver(self.neo_uri, auth=self.neo_auth) as d:
            with d.session() as s:
                n = s.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
        return {"total_relationships": n}

    # ---------- Energy metrics (Prometheus counters) ----
    def energy_stats(self):
        # supplied by the CostVQ / energy loop; falls back to NaN if absent
        from prometheus_client import REGISTRY
        metric = REGISTRY.get_sample_value  # shorthand
        costvq = metric("costvq_current")
        deltaE = metric("energy_delta_last")
        return {
            "CostVQ": safe_json_number(costvq),
            "deltaE_last": safe_json_number(deltaE),
        } 