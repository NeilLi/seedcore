import os
import json
import logging
import time
from typing import Optional, Dict, Any
from .backends.pgvector_backend_optimized import PgVectorStoreOptimized
from .backends.neo4j_graph import Neo4jGraph
import numpy as np
import asyncio

logger = logging.getLogger(__name__)

class LongTermMemoryManagerOptimized:
    def __init__(self):
        print("🔌 Initializing optimized LongTermMemoryManager...")
        start_time = time.time()
        
        self.pg_store = PgVectorStoreOptimized(
            os.getenv("PG_DSN", "postgresql://postgres:CHANGE_ME@postgresql:5432/postgres"),
            pool_size=10
        )
        
        self.neo4j_graph = Neo4jGraph(
            os.getenv("NEO4J_URI") or os.getenv("NEO4J_BOLT_URL", "bolt://neo4j:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))
        )
        
        elapsed = time.time() - start_time
        print(f"✅ Optimized LongTermMemoryManager initialized in {elapsed:.2f}s")

    async def initialize(self):
        """Async initialization to set up connection pools and ensure readiness."""
        print("🔌 Initializing async connections...")
        start_time = time.time()
        
        try:
            # Initialize the PgVector connection pool
            await self.pg_store._get_pool()
            
            elapsed = time.time() - start_time
            print(f"✅ Async connections initialized in {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Failed to initialize async connections in {elapsed:.2f}s: {e}")
            raise

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
        Optimized retrieval of a holon's metadata from PgVector by its ID.
        """
        try:
            logger.info(f"[{self.__class__.__name__}] Querying Mlt for holon_id: {holon_id}")
            
            # Use the optimized backend
            result = self.pg_store.get_by_id_sync(holon_id)
            
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
        Async version of query_holon_by_id using optimized backend.
        """
        try:
            logger.info(f"[{self.__class__.__name__}] (async) Querying Mlt for holon_id: {holon_id}")
            result = await self.pg_store.get_by_id(holon_id)
            
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
            print(f"❌ Error querying holon by ID '{holon_id}': {e}")
            return None

    async def query_holons_by_similarity(self, embedding: list, limit: int = 5) -> list:
        """
        Optimized similarity search using vector embeddings.
        """
        try:
            print(f"🔍 Querying holons by similarity (limit: {limit})")
            
            # Convert embedding to numpy array
            query_embedding = np.array(embedding)
            
            # Use optimized backend
            results = await self.pg_store.search(query_embedding, limit)
            
            print("✅ Similarity search completed")
            return results
            
        except Exception as e:
            print(f"🚨 Error in similarity search: {e}")
            return []

    async def get_holon_relationships(self, holon_id: str) -> list:
        """
        Retrieves relationships for a specific holon from Neo4j.
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

    async def insert_holon_async(self, holon_data: dict) -> bool:
        """
        Async version of insert_holon that properly handles async operations.
        """
        try:
            print(f"📝 Inserting holon (async): {holon_data['vector']['id']}")
            start_time = time.time()
            
            # Create a Holon object for PgVector
            from .backends.pgvector_backend_optimized import Holon
            holon = Holon(
                uuid=holon_data['vector']['id'],
                embedding=np.array(holon_data['vector']['embedding']),
                meta=holon_data['vector']['meta']
            )
            
            # Insert into PgVector using optimized backend - properly await the async operation
            success = await self.pg_store.upsert(holon)
            
            # Insert graph relationships into Neo4j if present
            if success and 'graph' in holon_data:
                graph_data = holon_data['graph']
                self.neo4j_graph.upsert_edge(
                    graph_data['src_uuid'],
                    graph_data['rel'],
                    graph_data['dst_uuid']
                )
            
            elapsed = time.time() - start_time
            print(f"✅ Successfully inserted holon (async): {holon_data['vector']['id']} in {elapsed:.2f}s")
            return success
            
        except Exception as e:
            print(f"❌ Error inserting holon (async): {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            return False

    def insert_holon(self, holon_data: dict) -> bool:
        """
        Optimized insertion of a holon into the Long-Term Memory database.
        """
        try:
            print(f"📝 Inserting holon: {holon_data['vector']['id']}")
            start_time = time.time()
            
            # Create a Holon object for PgVector
            from .backends.pgvector_backend_optimized import Holon
            holon = Holon(
                uuid=holon_data['vector']['id'],
                embedding=np.array(holon_data['vector']['embedding']),
                meta=holon_data['vector']['meta']
            )
            
            # Insert into PgVector using optimized backend
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, use asyncio.run_coroutine_threadsafe
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.pg_store.upsert(holon))
                    success = future.result()
            except RuntimeError:
                # No event loop running, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                success = loop.run_until_complete(self.pg_store.upsert(holon))
                loop.close()
            
            # Insert graph relationships into Neo4j if present
            if success and 'graph' in holon_data:
                graph_data = holon_data['graph']
                self.neo4j_graph.upsert_edge(
                    graph_data['src_uuid'],
                    graph_data['rel'],
                    graph_data['dst_uuid']
                )
            
            elapsed = time.time() - start_time
            print(f"✅ Successfully inserted holon: {holon_data['vector']['id']} in {elapsed:.2f}s")
            return success
            
        except Exception as e:
            print(f"❌ Error inserting holon: {e}")
            return False

    async def close(self):
        """Close all connections."""
        if hasattr(self, 'pg_store'):
            await self.pg_store.close() 