#!/usr/bin/env python3
"""
Test script to verify datetime handling in the reaper.
"""

import datetime
import os
import sys
from pathlib import Path

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[1]  # /app
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import psycopg2
from psycopg2.extras import RealDictCursor

def test_datetime_handling():
    """Test datetime handling with sample data."""
    
    # Test the datetime logic from the reaper
    def _now():
        """Get current UTC time with timezone info."""
        return datetime.datetime.now(datetime.timezone.utc)
    
    now = _now()
    print(f"Current time (UTC): {now}")
    print(f"Timezone info: {now.tzinfo}")
    
    # Test with naive datetime (from database)
    naive_dt = datetime.datetime(2025, 8, 31, 21, 30, 0)  # No timezone info
    print(f"Naive datetime: {naive_dt}")
    print(f"Timezone info: {naive_dt.tzinfo}")
    
    # Make it timezone-aware
    aware_dt = naive_dt.replace(tzinfo=datetime.timezone.utc)
    print(f"Timezone-aware datetime: {aware_dt}")
    print(f"Timezone info: {aware_dt.tzinfo}")
    
    # Calculate age
    age_s = (now - aware_dt).total_seconds()
    print(f"Age in seconds: {age_s}")
    print(f"Age in minutes: {age_s / 60}")
    
    # Test staleness (15 minutes = 900 seconds)
    stale = age_s >= 900
    print(f"Is stale (>15 min): {stale}")

def test_database_datetime():
    """Test datetime handling with actual database data."""
    dsn = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))
    
    try:
        with psycopg2.connect(dsn) as con, con.cursor(cursor_factory=RealDictCursor) as cur:
            # Get a few sample tasks to test datetime handling
            cur.execute("""
                SELECT id, status, updated_at, last_heartbeat, lease_expires_at
                FROM tasks
                WHERE status = 'running'
                LIMIT 3
            """)
            
            rows = cur.fetchall()
            print(f"Found {len(rows)} running tasks")
            
            for row in rows:
                print(f"\nTask {row['id']}:")
                print(f"  Status: {row['status']}")
                print(f"  Updated at: {row['updated_at']} (tzinfo: {row['updated_at'].tzinfo if row['updated_at'] else 'None'})")
                print(f"  Last heartbeat: {row['last_heartbeat']} (tzinfo: {row['last_heartbeat'].tzinfo if row['last_heartbeat'] else 'None'})")
                print(f"  Lease expires: {row['lease_expires_at']} (tzinfo: {row['lease_expires_at'].tzinfo if row['lease_expires_at'] else 'None'})")
                
                # Test the staleness logic
                last_ts = row.get("last_heartbeat") or row.get("lease_expires_at") or row.get("updated_at")
                if last_ts:
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=datetime.timezone.utc)
                    
                    now = datetime.datetime.now(datetime.timezone.utc)
                    age_s = (now - last_ts).total_seconds()
                    stale = age_s >= 900  # 15 minutes
                    
                    print(f"  Age: {age_s:.1f} seconds ({age_s/60:.1f} minutes)")
                    print(f"  Stale: {stale}")
                else:
                    print(f"  No timestamp available")
                    
    except Exception as e:
        print(f"Database test failed: {e}")

if __name__ == "__main__":
    print("🧪 Testing datetime handling...")
    print("=" * 50)
    
    test_datetime_handling()
    
    print("\n" + "=" * 50)
    print("🗄️ Testing with database data...")
    test_database_datetime()
    
    print("\n✅ DateTime handling test completed")
