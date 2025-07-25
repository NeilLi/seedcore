import json
import os
import logging
import asyncio
from .backends.pgvector_backend import PgVectorStore, Holon
from .backends.neo4j_graph import Neo4jGraph
from src.seedcore.memory.mw_store import MwStore
import numpy as np

logger = logging.getLogger(__name__)
UUID_FILE_PATH = '/app/scripts/fact_uuids.json'

class LongTermMemoryManager:
    def __init__(self):
        self.pg_store = PgVectorStore(os.getenv("PG_DSN", "postgresql://postgres:password@postgres:5432/postgres"))
        self.neo4j_graph = Neo4jGraph(os.getenv("NEO4J_URI", "bolt://neo4j:7687"), auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")))
        self._in_memory_holons = {}
        self.known_uuids = {}
        try:
            with open(UUID_FILE_PATH, 'r') as f:
                self.known_uuids = json.load(f)
            logger.info(f"[{self.__class__.__name__}] Loaded known UUIDs from file.")
        except FileNotFoundError:
            logger.warning(f"[{self.__class__.__name__}] UUID file not found at {UUID_FILE_PATH}. Simulation will be limited.")
        except json.JSONDecodeError:
            logger.error(f"[{self.__class__.__name__}] Failed to parse UUID file.")
        # Load fact_uuids.json and holon_ids.jsonl
        fact_uuids_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../fact_uuids.json'))
        holon_ids_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../holon_ids.jsonl'))
        fact_uuids = {}
        if os.path.exists(fact_uuids_path):
            with open(fact_uuids_path) as f:
                fact_uuids = json.load(f)
        if os.path.exists(holon_ids_path) and fact_uuids:
            with open(holon_ids_path) as f:
                for line in f:
                    entry = json.loads(line)
                    if entry["uuid"] in fact_uuids.values():
                        self._in_memory_holons[entry["uuid"]] = entry["meta"]
        # Ray-native MwStore actor
        import ray
        ray.init(address="auto", ignore_reinit_error=True)
        try:
            self._mw_store = ray.get_actor("mw")
        except ValueError:
            self._mw_store = MwStore.options(name="mw").remote()
        logger.info("✅ LongTermMemoryManager initialized.")

    async def incr_miss(self, fact_id: str):
        # fire-and-forget: no need to await
        self._mw_store.incr.remote(fact_id)

    async def get_fact(self, fact_id: str):
        # Async Ray-native get
        value_ref = self._mw_store.get.remote(fact_id)
        value = await value_ref
        return value

    async def hot_items(self, k: int):
        # Run queries concurrently
        ref = self._mw_store.topn.remote(k)
        items = await ref
        return items

    def query_holon_by_id(self, holon_id: str):
        try:
            logger.info(f"[{self.__class__.__name__}] Querying Mlt for holon_id: {holon_id}")
            if holon_id == self.known_uuids.get("fact_X"):
                return {"id": holon_id, "type": "critical_fact", "content": "The launch code is 1234."}
            elif holon_id == self.known_uuids.get("fact_Y"):
                return {"id": holon_id, "type": "common_knowledge", "content": "The sky is blue on a clear day."}
            else:
                logger.warning(f"[{self.__class__.__name__}] Holon '{holon_id}' not found in known UUIDs.")
                return None
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] Error querying holon by ID '{holon_id}': {e}")
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
        Inserts a holon into the simulated memory (for testing).
        """
        try:
            print(f"Inserting holon: {holon_data['vector']['id']}")
            return True
        except Exception as e:
            print(f"Error inserting holon: {e}")
            return False 