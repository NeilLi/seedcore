from neo4j import GraphDatabase

class Neo4jGraph:
    def __init__(self, uri, auth):
        self.driver = GraphDatabase.driver(uri, auth=auth)

    def upsert_edge(self, src_uuid: str, rel: str, dst_uuid: str):
        q = (
            "MERGE (a:Holon {uuid:$s}) "
            "MERGE (b:Holon {uuid:$d}) "
            f"MERGE (a)-[:{rel}]->(b)"
        )
        with self.driver.session() as s:
            s.run(q, s=src_uuid, d=dst_uuid)

    def neighbors(self, uuid: str, rel: str = None, k: int = 20):
        if rel is None:
            q = "MATCH (a:Holon{uuid:$u})-[*1..1]-(b) RETURN b.uuid AS uuid LIMIT $k"
        else:
            q = f"MATCH (a:Holon{{uuid:$u}})-[:{rel}]-(b) RETURN b.uuid AS uuid LIMIT $k"
        with self.driver.session() as s:
            return [r["uuid"] for r in s.run(q, u=uuid, k=k)]

    def close(self):
        if hasattr(self, "driver"):
            self.driver.close() 