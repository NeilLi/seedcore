#!/usr/bin/env python3
"""
Script to populate Long-Term Memory (Mlt) with critical information for Scenario 1.
This script inserts a sample 'fact_X' into the Long-Term Memory so it can be retrieved
during the collaborative task scenario.
"""

import os
import sys
import uuid
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.seedcore.memory.long_term_memory import LongTermMemoryManager

UUID_FILE_PATH = os.path.join(os.path.dirname(__file__), 'fact_uuids.json')

def populate_all_facts():
    mlt = LongTermMemoryManager()
    fact_x_uuid = str(uuid.uuid4())
    fact_y_uuid = str(uuid.uuid4())
    uuids_to_save = {"fact_X": fact_x_uuid, "fact_Y": fact_y_uuid}
    with open(UUID_FILE_PATH, 'w') as f:
        json.dump(uuids_to_save, f, indent=2)
    fact_x_data = {
        "vector": {
            "id": fact_x_uuid,
            "embedding": [0.1] * 768,
            "meta": {"type": "critical_fact", "content": "The launch code is 1234."}
        }, "graph": {"src_uuid": "task-alpha", "rel": "REQUIRES", "dst_uuid": fact_x_uuid}
    }
    mlt.insert_holon(fact_x_data)
    fact_y_data = {
        "vector": {
            "id": fact_y_uuid,
            "embedding": [0.2] * 768,
            "meta": {"type": "common_knowledge", "content": "The sky is blue on a clear day."}
        }, "graph": {"src_uuid": "general-knowledge", "rel": "CONTAINS", "dst_uuid": fact_y_uuid}
    }
    mlt.insert_holon(fact_y_data)

if __name__ == "__main__":
    populate_all_facts() 