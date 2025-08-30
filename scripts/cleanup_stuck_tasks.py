#!/usr/bin/env python3
"""
Cleanup script to fix stuck RETRY tasks and prevent infinite retry loops.
This script will:
1. Mark tasks that have exceeded max attempts as FAILED
2. Cancel duplicate tasks
3. Reset stuck tasks to a clean state
"""

import os
import sys
import asyncio
import asyncpg
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Configuration
PG_DSN = os.getenv("PG_DSN") or os.getenv("SEEDCORE_PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore")
MAX_ATTEMPTS = int(os.getenv("MAX_TASK_ATTEMPTS", "3"))

async def cleanup_stuck_tasks():
    """Clean up stuck tasks in the database."""
    print("🧹 Starting cleanup of stuck tasks...")
    
    try:
        # Connect to database
        conn = await asyncpg.connect(PG_DSN)
        print("✅ Connected to database")
        
        # 1. Mark tasks that have exceeded max attempts as FAILED
        print("\n📊 Checking for tasks that have exceeded max attempts...")
        result = await conn.fetch("""
            SELECT COUNT(*) as count
            FROM tasks 
            WHERE status = 'retry' 
              AND attempts >= $1
        """, MAX_ATTEMPTS)
        
        stuck_count = result[0]['count']
        print(f"Found {stuck_count} tasks with {MAX_ATTEMPTS}+ attempts")
        
        if stuck_count > 0:
            await conn.execute("""
                UPDATE tasks 
                SET status = 'failed', 
                    error = 'Max attempts exceeded - marked as failed by cleanup script',
                    updated_at = NOW()
                WHERE status = 'retry' 
                  AND attempts >= $1
            """, MAX_ATTEMPTS)
            print(f"✅ Marked {stuck_count} tasks as FAILED")
        
        # 2. Cancel duplicate tasks (keep only the oldest one)
        print("\n🔍 Checking for duplicate tasks...")
        duplicates = await conn.fetch("""
            WITH duplicates AS (
                SELECT 
                    type, description, params, domain,
                    COUNT(*) as count,
                    MIN(created_at) as oldest_created,
                    array_agg(id ORDER BY created_at) as task_ids
                FROM tasks 
                WHERE status IN ('queued', 'retry')
                  AND created_at > NOW() - INTERVAL '1 hour'
                GROUP BY type, description, params, domain
                HAVING COUNT(*) > 1
            )
            SELECT 
                type, description, count, 
                task_ids[1] as keep_id,
                task_ids[2:] as cancel_ids
            FROM duplicates
        """)
        
        print(f"Found {len(duplicates)} sets of duplicate tasks")
        
        for dup in duplicates:
            if dup['cancel_ids']:
                cancel_ids = dup['cancel_ids']
                await conn.execute("""
                    UPDATE tasks 
                    SET status = 'cancelled', 
                        error = 'Duplicate task cancelled by cleanup script',
                        updated_at = NOW()
                    WHERE id = ANY($1)
                """, cancel_ids)
                print(f"✅ Cancelled {len(cancel_ids)} duplicate tasks for '{dup['type']}: {dup['description']}'")
        
        # 3. Reset stuck RUNNING tasks that have been locked for too long
        print("\n🔄 Checking for stuck RUNNING tasks...")
        stuck_running = await conn.fetch("""
            SELECT COUNT(*) as count
            FROM tasks 
            WHERE status = 'running' 
              AND locked_at < NOW() - INTERVAL '5 minutes'
        """)
        
        stuck_count = stuck_running[0]['count']
        print(f"Found {stuck_count} stuck RUNNING tasks")
        
        if stuck_count > 0:
            await conn.execute("""
                UPDATE tasks 
                SET status = 'retry',
                    locked_by = NULL,
                    locked_at = NULL,
                    run_after = NOW() + INTERVAL '30 seconds',
                    updated_at = NOW()
                WHERE status = 'running' 
                  AND locked_at < NOW() - INTERVAL '5 minutes'
            """)
            print(f"✅ Reset {stuck_count} stuck RUNNING tasks to RETRY")
        
        # 4. Show current task status summary
        print("\n📈 Current task status summary:")
        status_summary = await conn.fetch("""
            SELECT 
                status,
                COUNT(*) as count,
                AVG(attempts) as avg_attempts,
                MAX(attempts) as max_attempts
            FROM tasks 
            GROUP BY status 
            ORDER BY count DESC
        """)
        
        for status in status_summary:
            print(f"  {status['status']}: {status['count']} tasks (avg attempts: {status['avg_attempts']:.1f}, max: {status['max_attempts']})")
        
        # 5. Show recent task activity
        print("\n🕒 Recent task activity (last 24 hours):")
        recent_activity = await conn.fetch("""
            SELECT 
                type,
                status,
                COUNT(*) as count,
                MAX(created_at) as last_created
            FROM tasks 
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY type, status
            ORDER BY count DESC, last_created DESC
            LIMIT 10
        """)
        
        for activity in recent_activity:
            print(f"  {activity['type']} ({activity['status']}): {activity['count']} tasks, last: {activity['last_created']}")
        
        await conn.close()
        print("\n✅ Cleanup completed successfully!")
        
    except Exception as e:
        print(f"❌ Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

async def main():
    """Main cleanup function."""
    print("🚀 SeedCore Task Cleanup Script")
    print("=" * 40)
    print(f"Database: {PG_DSN}")
    print(f"Max attempts: {MAX_ATTEMPTS}")
    print("=" * 40)
    
    await cleanup_stuck_tasks()

if __name__ == "__main__":
    asyncio.run(main())
