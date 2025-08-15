#!/usr/bin/env python3
import asyncio
import asyncpg

async def check_database():
    dsn = "postgresql://postgres:CHANGE_ME@postgresql:5432/postgres"
    
    try:
        conn = await asyncpg.connect(dsn)
        
        # Check total count
        count = await conn.fetchval("SELECT COUNT(*) FROM holons")
        print(f"Total records in holons table: {count}")
        
        # Check for the specific UUID from the scenario
        target_uuid = "dbe0fde2-bdcc-4f0e-ba25-c248b43afa04"
        result = await conn.fetchrow("SELECT uuid, meta FROM holons WHERE uuid = $1", target_uuid)
        
        if result:
            print(f"✅ Found UUID {target_uuid} in database")
            print(f"Meta: {result['meta']}")
        else:
            print(f"❌ UUID {target_uuid} NOT found in database")
            
            # Show a few sample UUIDs
            samples = await conn.fetch("SELECT uuid FROM holons LIMIT 5")
            print("Sample UUIDs in database:")
            for row in samples:
                print(f"  - {row['uuid']}")
        
        await conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_database()) 