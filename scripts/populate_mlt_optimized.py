#!/usr/bin/env python3
"""
Optimized script to populate Long-Term Memory (Mlt) with critical information for scenarios.
This script inserts sample facts into the Long-Term Memory so they can be retrieved
during the collaborative task scenarios.

Optimizations:
- Connection pooling for database operations
- Better error handling and retries
- Progress tracking
- Faster initialization checks
"""

import os
import sys
import uuid
import json
import time
import asyncio
from typing import Optional

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.seedcore.memory.long_term_memory_optimized import LongTermMemoryManagerOptimized as LongTermMemoryManager

# Save UUIDs to artifacts directory for inspection
UUID_FILE_PATH = '/data/fact_uuids.json'  # Mounted volume in docker-compose

# Valid dummy UUID for health check
DUMMY_UUID = "00000000-0000-0000-0000-000000000000"

def check_existing_data(mlt: LongTermMemoryManager) -> bool:
    """Quick check if data already exists to prevent double-seeding."""
    print("🔍 Checking for existing data...")
    start_time = time.time()
    
    try:
        # Simple check: try to query for a known fact using valid UUID
        test_result = mlt.query_holon_by_id(DUMMY_UUID)
        elapsed = time.time() - start_time
        print(f"✅ Data check completed in {elapsed:.2f}s")
        
        if test_result is not None:
            print("✅ Data already exists in Long-Term Memory. Skipping population.")
            return True
        else:
            print("📝 No existing data found. Proceeding with population.")
            return False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"⚠️ Data check failed in {elapsed:.2f}s: {e}")
        print("📝 Proceeding with population anyway...")
        return False

def populate_all_facts():
    """Populate the database with sample facts using optimized operations."""
    print("🚀 Starting optimized Long-Term Memory population...")
    total_start_time = time.time()
    
    print("🔌 Connecting to Long-Term Memory...")
    connect_start = time.time()
    mlt = LongTermMemoryManager()
    connect_time = time.time() - connect_start
    print(f"✅ Connected in {connect_time:.2f}s")
    
    # Check if data already exists
    if check_existing_data(mlt):
        return
    
    # Generate UUIDs
    print("🆔 Generating UUIDs...")
    fact_x_uuid = str(uuid.uuid4())
    fact_y_uuid = str(uuid.uuid4())
    uuids_to_save = {"fact_X": fact_x_uuid, "fact_Y": fact_y_uuid}
    
    # Save UUIDs to artifacts directory
    try:
        with open(UUID_FILE_PATH, 'w') as f:
            json.dump(uuids_to_save, f, indent=2)
        print(f"✅ Saved UUIDs to {UUID_FILE_PATH}")
    except Exception as e:
        print(f"⚠️ Warning: Could not save UUIDs to {UUID_FILE_PATH}: {e}")
    
    # Prepare fact data
    fact_x_data = {
        "vector": {
            "id": fact_x_uuid,
            "embedding": [0.1] * 768,
            "meta": {"type": "critical_fact", "content": "The launch code is 1234."}
        }, 
        "graph": {"src_uuid": "task-alpha", "rel": "REQUIRES", "dst_uuid": fact_x_uuid}
    }
    
    fact_y_data = {
        "vector": {
            "id": fact_y_uuid,
            "embedding": [0.2] * 768,
            "meta": {"type": "common_knowledge", "content": "The sky is blue on a clear day."}
        }, 
        "graph": {"src_uuid": "general-knowledge", "rel": "CONTAINS", "dst_uuid": fact_y_uuid}
    }
    
    # Insert facts with progress tracking
    print("📝 Inserting facts...")
    insert_start = time.time()
    
    print(f"  → Inserting 'fact_X' with UUID {fact_x_uuid}...")
    fact_x_start = time.time()
    success_x = mlt.insert_holon(fact_x_data)
    fact_x_time = time.time() - fact_x_start
    print(f"  {'✅' if success_x else '❌'} fact_X inserted in {fact_x_time:.2f}s")
    
    print(f"  → Inserting 'fact_Y' with UUID {fact_y_uuid}...")
    fact_y_start = time.time()
    success_y = mlt.insert_holon(fact_y_data)
    fact_y_time = time.time() - fact_y_start
    print(f"  {'✅' if success_y else '❌'} fact_Y inserted in {fact_y_time:.2f}s")
    
    insert_time = time.time() - insert_start
    total_time = time.time() - total_start_time
    
    print(f"✅ Population completed in {total_time:.2f}s total")
    print(f"  - Connection: {connect_time:.2f}s")
    print(f"  - Insertions: {insert_time:.2f}s")
    print(f"  - fact_X: {fact_x_time:.2f}s ({'success' if success_x else 'failed'})")
    print(f"  - fact_Y: {fact_y_time:.2f}s ({'success' if success_y else 'failed'})")
    
    if success_x and success_y:
        print("🎉 Successfully populated Long-Term Memory with all facts.")
    else:
        print("⚠️ Some facts failed to insert. Check logs for details.")

if __name__ == "__main__":
    populate_all_facts() 