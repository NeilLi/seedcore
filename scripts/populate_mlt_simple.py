#!/usr/bin/env python3
"""
Simple and reliable script to populate Long-Term Memory (Mlt) with critical information.
This version avoids async/sync conflicts and connection pool issues.
"""

import os
import sys
import uuid
import json
import time
import asyncio
import asyncpg

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Save UUIDs to artifacts directory for inspection
UUID_FILE_PATH = '/data/fact_uuids.json'  # Mounted volume in docker-compose

# Valid dummy UUID for health check
DUMMY_UUID = "00000000-0000-0000-0000-000000000000"

# Fixed UUIDs for scenario testing - these should always be created
SCENARIO_FACT_X_UUID = "99277688-f616-4388-ac9b-31d7288c6497"
SCENARIO_FACT_Y_UUID = "dbe0fde2-bdcc-4f0e-ba25-c248b43afa04"

async def check_existing_data(dsn: str) -> bool:
    """Check if our specific scenario data already exists."""
    print("🔍 Checking for scenario test data...")
    start_time = time.time()
    
    try:
        conn = await asyncpg.connect(dsn)
        try:
            # Check if our specific scenario UUIDs exist
            result = await conn.fetchrow("SELECT COUNT(*) as count FROM holons WHERE uuid IN ($1, $2)", 
                                       SCENARIO_FACT_X_UUID, SCENARIO_FACT_Y_UUID)
            count = result['count'] if result else 0
            elapsed = time.time() - start_time
            print(f"✅ Data check completed in {elapsed:.2f}s (found {count}/2 scenario records)")
            
            if count == 2:
                print("✅ Scenario test data already exists. Skipping population.")
                return True
            else:
                print(f"📝 Missing scenario data ({count}/2 found). Proceeding with population.")
                return False
        finally:
            await conn.close()
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"⚠️ Data check failed in {elapsed:.2f}s: {e}")
        print("📝 Proceeding with population anyway...")
        return False

async def insert_holon_simple(conn: asyncpg.Connection, holon_id: str, embedding: list, meta: dict) -> bool:
    """Simple holon insertion using direct connection."""
    try:
        q = """INSERT INTO holons (uuid, embedding, meta)
               VALUES ($1,$2::vector,$3)
               ON CONFLICT (uuid) DO UPDATE SET embedding=$2, meta=$3"""
        
        vec_str = '[' + ','.join(str(x) for x in embedding) + ']'
        await conn.execute(q, holon_id, vec_str, json.dumps(meta))
        return True
    except Exception as e:
        print(f"❌ Error inserting holon {holon_id}: {e}")
        return False

async def populate_all_facts_async():
    """Async version of fact population using direct database connections."""
    print("🚀 Starting simple Long-Term Memory population...")
    total_start_time = time.time()
    
    # Database connection string
    dsn = os.getenv("PG_DSN", "postgresql://postgres:CHANGE_ME@postgresql:5432/postgres")
    
    # Check if our specific scenario data already exists
    if await check_existing_data(dsn):
        return
    
    # Use fixed UUIDs for scenario testing
    print("🆔 Using fixed UUIDs for scenario testing...")
    fact_x_uuid = SCENARIO_FACT_X_UUID
    fact_y_uuid = SCENARIO_FACT_Y_UUID
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
        "id": fact_x_uuid,
        "embedding": [0.1] * 768,
        "meta": {"type": "critical_fact", "content": "The launch code is 1234."}
    }
    
    fact_y_data = {
        "id": fact_y_uuid,
        "embedding": [0.2] * 768,
        "meta": {"type": "common_knowledge", "content": "The sky is blue on a clear day."}
    }
    
    # Insert facts with single connection
    print("📝 Inserting scenario test facts...")
    insert_start = time.time()
    
    try:
        conn = await asyncpg.connect(dsn)
        try:
            print(f"  → Inserting 'fact_X' with UUID {fact_x_uuid}...")
            fact_x_start = time.time()
            success_x = await insert_holon_simple(conn, fact_x_uuid, fact_x_data["embedding"], fact_x_data["meta"])
            fact_x_time = time.time() - fact_x_start
            print(f"  {'✅' if success_x else '❌'} fact_X inserted in {fact_x_time:.2f}s")
            
            print(f"  → Inserting 'fact_Y' with UUID {fact_y_uuid}...")
            fact_y_start = time.time()
            success_y = await insert_holon_simple(conn, fact_y_uuid, fact_y_data["embedding"], fact_y_data["meta"])
            fact_y_time = time.time() - fact_y_start
            print(f"  {'✅' if success_y else '❌'} fact_Y inserted in {fact_y_time:.2f}s")
            
        finally:
            await conn.close()
            
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        success_x = False
        success_y = False
        fact_x_time = 0
        fact_y_time = 0
    
    insert_time = time.time() - insert_start
    total_time = time.time() - total_start_time
    
    print(f"✅ Population completed in {total_time:.2f}s total")
    print(f"  - Insertions: {insert_time:.2f}s")
    print(f"  - fact_X: {fact_x_time:.2f}s ({'success' if success_x else 'failed'})")
    print(f"  - fact_Y: {fact_y_time:.2f}s ({'success' if success_y else 'failed'})")
    
    if success_x and success_y:
        print("🎉 Successfully populated Long-Term Memory with scenario test facts.")
    else:
        print("⚠️ Some facts failed to insert. Check logs for details.")

def populate_all_facts():
    """Main entry point that runs the async function."""
    asyncio.run(populate_all_facts_async())

if __name__ == "__main__":
    populate_all_facts() 