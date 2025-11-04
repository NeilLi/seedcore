import asyncio
from neo4j import AsyncGraphDatabase, AsyncSession, AsyncDriver
from typing import List, Optional, Tuple

class Neo4jGraph:
    def __init__(self, uri: str, auth: Tuple[str, str]):
        """
        Initializes the async driver for Neo4j.
        """
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=auth)
        self.database: str = "neo4j"  # Default database, can be made configurable

    async def _execute_query(self, query: str, params: dict = None):
        """Helper to run a query in a managed async session."""
        if params is None:
            params = {}
        try:
            async with self.driver.session(database=self.database) as session:
                await session.run(query, params)
        except Exception as e:
            # In a real app, you'd have more robust logging
            print(f"Neo4j query failed: {e}")
            raise

    async def upsert_edge(self, src_uuid: str, rel: str, dst_uuid: str):
        """
        Asynchronously merges nodes and creates a relationship between them.
        
        Note: Ensures 'rel' is sanitized or from a known-safe list
        to prevent Cypher injection if user-provided.
        """
        # A simple check for the relationship type
        if not rel.isalnum() or not rel.isupper():
            print(f"Invalid relationship type: {rel}. Using 'RELATED_TO'.")
            rel = "RELATED_TO"
            
        q = (
            "MERGE (a:Holon {uuid:$s}) "
            "MERGE (b:Holon {uuid:$d}) "
            f"MERGE (a)-[:{rel}]->(b)"
        )
        await self._execute_query(q, {"s": src_uuid, "d": dst_uuid})

    async def neighbors(self, uuid: str, rel: Optional[str] = None, k: int = 20) -> List[str]:
        """
        Asynchronously fetches neighbor UUIDs for a given holon.
        Kept method name as 'neighbors' for backward compatibility.
        """
        if rel:
            if not rel.isalnum() or not rel.isupper():
                rel = "RELATED_TO"
            q = f"MATCH (a:Holon{{uuid:$u}})-[:{rel}]-(b) RETURN b.uuid AS uuid LIMIT $k"
        else:
            q = "MATCH (a:Holon{uuid:$u})-[*1..1]-(b) RETURN b.uuid AS uuid LIMIT $k"
        
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(q, {"u": uuid, "k": k})
                # Use list comprehension with async result consumption
                return [record["uuid"] async for record in result]
        except Exception as e:
            print(f"Neo4j neighbors query failed: {e}")
            return []

    async def get_neighbors(self, uuid: str, rel: Optional[str] = None, k: int = 20) -> List[str]:
        """
        Alias for neighbors() method for API consistency.
        """
        return await self.neighbors(uuid, rel, k)

    async def get_count(self) -> int:
        """
        Asynchronously gets the total count of relationships.
        Required for `HolonFabric.get_stats()` and `cost_vq`.
        """
        q = "MATCH ()-[r]->() RETURN count(r) AS count"
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(q)
                record = await result.single()
                return record["count"] if record else 0
        except Exception as e:
            print(f"Neo4j count query failed: {e}")
            return 0

    async def close(self):
        """Asynchronously close the driver connection."""
        if hasattr(self, "driver"):
            await self.driver.close() 