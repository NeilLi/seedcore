# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import asyncio
from seedcore.memory.backends.pgvector_backend import PgVectorStore, Holon
from seedcore.memory.backends.neo4j_graph import Neo4jGraph
from seedcore.memory.holon_fabric import HolonFabric

# Get database connections from environment variables
PG_DSN = os.getenv('PG_DSN')
NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USER = os.getenv('NEO4J_USER')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

if not all([PG_DSN, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD]):
    print("Error: Required environment variables not set:")
    print("  PG_DSN, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD")
    print("Please set these environment variables before running the experiment.")
    exit(1)

async def run_experiment():
    """Run the PGVector + Neo4j experiment."""
    print("Starting PGVector + Neo4j experiment...")
    
    # Initialize backends
    vec_store = PgVectorStore(PG_DSN)
    graph = Neo4jGraph(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    fabric = HolonFabric(vec_store, graph)
    
    # Create sample holon
    import numpy as np
    sample_embedding = np.random.randn(768).astype(np.float32)
    holon = Holon(embedding=sample_embedding, meta={"test": True})
    
    # Insert holon
    await fabric.insert_holon(holon)
    print(f"Inserted holon with UUID: {holon.uuid}")
    
    # Query holon
    result = await fabric.query_exact(holon.uuid)
    print(f"Query result: {result}")
    
    # Fuzzy search
    search_embedding = np.random.randn(768).astype(np.float32)
    fuzzy_results = await fabric.query_fuzzy(search_embedding, k=5)
    print(f"Fuzzy search results: {fuzzy_results}")
    
    # Get stats
    stats = await fabric.get_stats()
    print(f"Fabric stats: {stats}")
    
    print("Experiment completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_experiment()) 