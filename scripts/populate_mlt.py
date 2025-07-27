#!/usr/bin/env python3
"""
Script to populate Long-Term Memory (Mlt) with critical information for scenarios.
This script inserts sample facts into the Long-Term Memory so they can be retrieved
during the collaborative task scenarios.
"""

import os
import sys
import uuid
import json
# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.seedcore.memory.long_term_memory import LongTermMemoryManager

# Save UUIDs to artifacts directory for inspection
UUID_FILE_PATH = '/data/fact_uuids.json'  # Mounted volume in docker-compose

# Valid dummy UUID for health check
DUMMY_UUID = "00000000-0000-0000-0000-000000000000"

def populate_all_facts():
    print("Connecting to Long-Term Memory...")
    mlt = LongTermMemoryManager()
    
    # Check if data already exists to prevent double-seeding
    try:
        # Simple check: try to query for a known fact using valid UUID
        test_result = mlt.query_holon_by_id(DUMMY_UUID)
        if test_result is not None:
            print("✅ Data already exists in Long-Term Memory. Skipping population.")
            return
    except Exception:
        pass  # Continue with population if check fails
    
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
    
    fact_x_data = {
        "vector": {
            "id": fact_x_uuid,
            "embedding": [0.1] * 768,
            "meta": {"type": "critical_fact", "content": "The launch code is 1234."}
        }, "graph": {"src_uuid": "task-alpha", "rel": "REQUIRES", "dst_uuid": fact_x_uuid}
    }
    print(f"Inserting 'fact_X' with UUID {fact_x_uuid}...")
    mlt.insert_holon(fact_x_data)
    
    fact_y_data = {
        "vector": {
            "id": fact_y_uuid,
            "embedding": [0.2] * 768,
            "meta": {"type": "common_knowledge", "content": "The sky is blue on a clear day."}
        }, "graph": {"src_uuid": "general-knowledge", "rel": "CONTAINS", "dst_uuid": fact_y_uuid}
    }
    print(f"Inserting 'fact_Y' with UUID {fact_y_uuid}...")
    mlt.insert_holon(fact_y_data)
    
    print("✅ Successfully populated Long-Term Memory with all facts.")

if __name__ == "__main__":
    populate_all_facts() 