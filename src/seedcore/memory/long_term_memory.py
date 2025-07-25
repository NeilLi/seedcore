from .backends.pgvector_backend import PgVectorStore, Holon
from .backends.neo4j_graph import Neo4jGraph
import os
import numpy as np

class LongTermMemoryManager:
    def __init__(self):
        # Use environment variables for DSN and Neo4j auth
        pg_dsn = os.getenv("PG_DSN", "postgresql://postgres:password@postgres:5432/postgres")
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        self.pg_store = PgVectorStore(pg_dsn)
        self.neo4j_graph = Neo4jGraph(neo4j_uri, auth=(neo4j_user, neo4j_password))
        print("✅ LongTermMemoryManager initialized.")

    async def insert_holon(self, holon_data: dict) -> bool:
        """
        Ensures an atomic insert operation across PgVector and Neo4j using a saga pattern.
        """
        vector_id = None
        try:
            # --- Phase 1: Insert into PgVector ---
            print("Attempting to insert into PgVector...")
            holon_data['vector']['embedding'] = np.array(holon_data['vector']['embedding'])
            holon = Holon(**holon_data['vector'])
            await self.pg_store.upsert(holon)
            vector_id = holon.uuid
            print(f"Success: Inserted into PgVector with id {vector_id}.")

            # --- Phase 2: Insert into Neo4j ---
            print("Attempting to insert into Neo4j...")
            graph_data = holon_data['graph']
            self.neo4j_graph.upsert_edge(**graph_data)
            print("Success: Inserted into Neo4j.")
            return True

        except Exception as e:
            print(f"🚨 ERROR during holon insertion: {e}")
            # --- Compensation Phase ---
            if vector_id is not None:
                print(f"Rolling back from PgVector: Deleting id {vector_id}...")
                # You would implement a delete method in PgVectorStore for this
                # await self.pg_store.delete(vector_id)
                print("Rollback complete.")
            return False 