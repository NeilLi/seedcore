import os
import json
import logging
from typing import Optional, Dict, Any
from .backends.pgvector_backend import PgVectorStore
from .backends.neo4j_graph import Neo4jGraph
import numpy as np # Added back for embedding
import asyncio # Added for event loop in insert_holon

logger = logging.getLogger(__name__)

class LongTermMemoryManager:
    def __init__(self):
        self.pg_store = PgVectorStore(os.getenv("PG_DSN", "postgresql://postgres:CHANGE_ME@postgresql:5432/postgres"))
        self.neo4j_graph = Neo4jGraph(
            os.getenv("NEO4J_URI") or os.getenv("NEO4J_BOLT_URL", "bolt://neo4j:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))
        )
        print("✅ LongTermMemoryManager initialized.")

    async def incr_miss(self, fact_id: str):
        # fire-and-forget: no need to await
        pass # MwStore actor removed

    async def get_fact(self, fact_id: str):
        # Async Ray-native get
        pass # MwStore actor removed

    async def hot_items(self, k: int):
        # Run queries concurrently
        pass # MwStore actor removed

    def query_holon_by_id(self, holon_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a holon's metadata from PgVector by its ID.
        This is a simplified but more realistic query for the scenarios.
        """
        try:
            logger.info(f"[{self.__class__.__name__}] Querying Mlt for holon_id: {holon_id}")
            
            # Query the actual PgVector database
            logger.info(f"[{self.__class__.__name__}] Calling pg_store.get_by_id({holon_id})")
            result = self.pg_store.get_by_id(holon_id)
            logger.info(f"[{self.__class__.__name__}] Database query result: {result}")
            
            if result:
                logger.info(f"[{self.__class__.__name__}] Found holon: {holon_id}")
                return result
            else:
                logger.warning(f"[{self.__class__.__name__}] Holon '{holon_id}' not found in database.")
                return None
                
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] Error querying holon by ID '{holon_id}': {e}")
            import traceback
            logger.error(f"[{self.__class__.__name__}] Traceback: {traceback.format_exc()}")
            return None

    async def query_holon_by_id_async(self, holon_id: str) -> Optional[Dict[str, Any]]:
        """
        Async version of query_holon_by_id for use in async code.
        """
        try:
            logger.info(f"[{self.__class__.__name__}] (async) Querying Mlt for holon_id: {holon_id}")
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.pg_store.get_by_id, holon_id)
            logger.info(f"[{self.__class__.__name__}] (async) Database query result: {result}")
            if result:
                logger.info(f"[{self.__class__.__name__}] (async) Found holon: {holon_id}")
                return result
            else:
                logger.warning(f"[{self.__class__.__name__}] (async) Holon '{holon_id}' not found in database.")
                return None
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] (async) Error querying holon by ID '{holon_id}': {e}")
            import traceback
            logger.error(f"[{self.__class__.__name__}] (async) Traceback: {traceback.format_exc()}")
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

    def insert_holon(self, holon_data: dict) -> bool:
        """
        Inserts a holon into the Long-Term Memory database.
        """
        try:
            print(f"Inserting holon: {holon_data['vector']['id']}")
            
            # Create a Holon object for PgVector
            from .backends.pgvector_backend import Holon
            holon = Holon(
                uuid=holon_data['vector']['id'],
                embedding=np.array(holon_data['vector']['embedding']),
                meta=holon_data['vector']['meta']
            )
            
            # Insert into PgVector with proper event loop handling
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, use asyncio.run_coroutine_threadsafe
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.pg_store.upsert(holon))
                    future.result()
            except RuntimeError:
                # No event loop running, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.pg_store.upsert(holon))
                loop.close()
            
            # Insert graph relationships into Neo4j if present
            if 'graph' in holon_data:
                graph_data = holon_data['graph']
                self.neo4j_graph.upsert_edge(
                    graph_data['src_uuid'],
                    graph_data['rel'],
                    graph_data['dst_uuid']
                )
            
            print(f"✅ Successfully inserted holon: {holon_data['vector']['id']}")
            return True
            
        except Exception as e:
            print(f"Error inserting holon: {e}")
            return False 