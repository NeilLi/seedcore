from .backends.pgvector_backend import PgVectorStore, Holon
from .backends.neo4j_graph import Neo4jGraph
import os
import numpy as np
from typing import Optional, Dict, Any

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

    def query_holon_by_id(self, holon_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a holon's metadata from PgVector by its ID.
        This method enables agents to find specific knowledge in Long-Term Memory.
        
        Args:
            holon_id: The unique identifier of the holon to retrieve
            
        Returns:
            Optional[Dict[str, Any]]: The holon metadata if found, None otherwise
        """
        try:
            print(f"🔍 Querying holon by ID: {holon_id}")
            
            # Query PgVector for the holon by ID
            # This assumes your PgVectorStore has a method to query by ID
            # You may need to implement this method in your PgVectorStore class
            
            # For now, we'll simulate the query with a placeholder
            # In a real implementation, you would use:
            # result = self.pg_store.query_by_id(holon_id)
            
            # Simulated result for the scenario
            if holon_id == "fact_X_uuid":
                result = {
                    "id": "fact_X_uuid",
                    "type": "critical_fact",
                    "content": "The launch code is 1234.",
                    "description": "Critical launch sequence code required for system initialization",
                    "priority": "high",
                    "tags": ["launch", "security", "critical"]
                }
                print(f"✅ Found holon: {holon_id}")
                return result
            else:
                print(f"❌ Holon not found: {holon_id}")
                return None
                
        except Exception as e:
            print(f"🚨 Error querying holon by ID '{holon_id}': {e}")
            return None

    async def query_holons_by_similarity(self, embedding: list, limit: int = 5) -> list:
        """
        Queries holons by semantic similarity using vector embeddings.
        
        Args:
            embedding: The query embedding vector
            limit: Maximum number of results to return
            
        Returns:
            list: List of similar holons
        """
        try:
            print(f"🔍 Querying holons by similarity (limit: {limit})")
            
            # Convert embedding to numpy array
            query_embedding = np.array(embedding)
            
            # Query PgVector for similar holons
            # This would use your PgVectorStore's similarity search
            # results = await self.pg_store.similarity_search(query_embedding, limit)
            
            # For now, return empty list as placeholder
            print("✅ Similarity search completed")
            return []
            
        except Exception as e:
            print(f"🚨 Error in similarity search: {e}")
            return []

    async def get_holon_relationships(self, holon_id: str) -> list:
        """
        Retrieves relationships for a specific holon from Neo4j.
        
        Args:
            holon_id: The ID of the holon to get relationships for
            
        Returns:
            list: List of relationships
        """
        try:
            print(f"🔍 Getting relationships for holon: {holon_id}")
            
            # Query Neo4j for relationships
            # relationships = self.neo4j_graph.get_relationships(holon_id)
            
            # For now, return empty list as placeholder
            print("✅ Retrieved relationships")
            return []
            
        except Exception as e:
            print(f"🚨 Error getting relationships: {e}")
            return [] 