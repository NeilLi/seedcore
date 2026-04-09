import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)


def _sanitize_rel(rel: str) -> str:
    """
    Convert user/caller relationship labels into a safe Cypher rel token.

    Accepts canonical Neo4j-style labels like ``GENERATED_BY`` and normalizes
    mixed input into ``A_Z0_9_`` only.
    """
    raw = (rel or "").strip().upper()
    if not raw:
        logger.debug("Empty relationship type; using RELATED_TO")
        return "RELATED_TO"

    # Normalize unsupported chars into underscores, then collapse runs.
    normalized = re.sub(r"[^A-Z0-9_]", "_", raw)
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    # Cypher relationship types should start with a letter.
    if normalized and normalized[0].isalpha():
        return normalized

    logger.debug("Invalid relationship type %r; using RELATED_TO", rel)
    return "RELATED_TO"


class Neo4jGraph:
    def __init__(self, uri: str, auth: Tuple[str, str]):
        """
        Initializes the async driver for Neo4j.
        """
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=auth)
        self.database: str = "neo4j"  # Default database, can be made configurable

    async def ping(self) -> None:
        """Raise if Bolt is unreachable or the default database cannot run a trivial query."""
        async with self.driver.session(database=self.database) as session:
            result = await session.run("RETURN 1 AS ok")
            rec = await result.single()
            if rec is None or rec.get("ok") != 1:
                raise RuntimeError("neo4j ping: unexpected response")

    async def _execute_query(self, query: str, params: Optional[dict] = None):
        """Helper to run a query in a managed async session."""
        if params is None:
            params = {}
        try:
            async with self.driver.session(database=self.database) as session:
                await session.run(query, params)
        except Exception as e:
            logger.error("Neo4j query failed: %s", e)
            raise

    async def upsert_node(
        self,
        uuid: str,
        holon_type: str,
        summary: str,
        props: Optional[Dict[str, Any]] = None,
    ):
        """
        Asynchronously creates or updates a node with the given properties.
        """
        props = props or {}
        allowed_keys = {
            "scope",
            "organ_id",
            "entity_id",
            "confidence",
            "decay_rate",
            "created_at",
            "updated_at",
            "access_policy",
            "type",
        }
        set_parts = ["a.type = $t", "a.summary = $s"]
        params: Dict[str, Any] = {"u": uuid, "t": holon_type, "s": summary}
        idx = 0
        for key, val in props.items():
            if key in allowed_keys and val is not None:
                pname = f"p{idx}"
                set_parts.append(f"a.{key} = ${pname}")
                params[pname] = val
                idx += 1
        q = "MERGE (a:Holon {uuid:$u}) SET " + ", ".join(set_parts)
        await self._execute_query(q, params)

    async def upsert_edge(
        self,
        src_uuid: str,
        rel: str,
        dst_uuid: str,
        props: Optional[Dict[str, Any]] = None,
    ):
        """
        Asynchronously merges nodes and creates a relationship between them.
        """
        rel = _sanitize_rel(rel)
        if props:
            q = (
                "MERGE (a:Holon {uuid:$s}) "
                "MERGE (b:Holon {uuid:$d}) "
                f"MERGE (a)-[r:{rel}]->(b) "
                "SET r += $rp"
            )
            await self._execute_query(
                q, {"s": src_uuid, "d": dst_uuid, "rp": dict(props)}
            )
        else:
            q = (
                "MERGE (a:Holon {uuid:$s}) "
                "MERGE (b:Holon {uuid:$d}) "
                f"MERGE (a)-[:{rel}]->(b)"
            )
            await self._execute_query(q, {"s": src_uuid, "d": dst_uuid})

    async def delete_node(self, uuid: str) -> None:
        q = "MATCH (a:Holon {uuid:$u}) DETACH DELETE a"
        await self._execute_query(q, {"u": uuid})

    async def get_neighbors(
        self,
        uuid: str,
        rel: Optional[str] = None,
        k: int = 20,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return neighbor rows with uuid, holon_type, summary, rel_type, and props map.
        """
        lim = int(limit if limit is not None else k)
        params: Dict[str, Any] = {"u": uuid, "lim": lim}
        if rel:
            rel = _sanitize_rel(rel)
            q = f"""
            MATCH (a:Holon {{uuid: $u}})-[r:{rel}]-(b:Holon)
            RETURN b.uuid AS uuid, b.type AS holon_type, b.summary AS summary,
                   type(r) AS rel_type, properties(b) AS props
            LIMIT $lim
            """
        else:
            q = """
            MATCH (a:Holon {uuid: $u})-[r]-(b:Holon)
            RETURN b.uuid AS uuid, b.type AS holon_type, b.summary AS summary,
                   type(r) AS rel_type, properties(b) AS props
            LIMIT $lim
            """
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(q, params)
                rows: List[Dict[str, Any]] = []
                async for record in result:
                    props = dict(record["props"] or {})
                    rows.append(
                        {
                            "uuid": record["uuid"],
                            "holon_type": record["holon_type"],
                            "summary": record["summary"] or "",
                            "rel_type": record["rel_type"],
                            "props": props,
                        }
                    )
                return rows
        except Exception as e:
            logger.error("Neo4j get_neighbors failed: %s", e)
            return []

    async def get_count(self) -> int:
        """
        Asynchronously gets the total count of relationships.
        """
        q = "MATCH ()-[r]->() RETURN count(r) AS count"
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(q)
                record = await result.single()
                return record["count"] if record else 0
        except Exception as e:
            logger.error("Neo4j count query failed: %s", e)
            return 0

    async def close(self):
        """Asynchronously close the driver connection."""
        if hasattr(self, "driver") and self.driver is not None:
            await self.driver.close()
