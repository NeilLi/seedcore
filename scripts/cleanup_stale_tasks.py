#!/usr/bin/env python3
"""
Emergency cleanup script for stale RUNNING tasks.
This script can be used to manually requeue tasks that are stuck in RUNNING status.
"""

import os
import sys
import argparse
import logging
import datetime
from pathlib import Path

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[1]  # /app
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger("cleanup_stale_tasks")

def cleanup_stale_tasks(dsn: str, stale_minutes: int = 15, max_attempts: int = 3, dry_run: bool = False):
    """
    Clean up stale RUNNING tasks.
    
    Args:
        dsn: PostgreSQL connection string
        stale_minutes: Consider tasks stale if older than this many minutes
        max_attempts: Maximum number of attempts before marking as failed
        dry_run: If True, only show what would be done without making changes
    """
    try:
        with psycopg2.connect(dsn) as con, con.cursor(cursor_factory=RealDictCursor) as cur:
            # First, show current task status distribution
            cur.execute("""
                SELECT 
                    status,
                    COUNT(*) as count,
                    CASE 
                        WHEN status = 'running' THEN '🔄'
                        WHEN status = 'queued' THEN '⏳'
                        WHEN status = 'completed' THEN '✅'
                        WHEN status = 'failed' THEN '❌'
                        WHEN status = 'retry' THEN '🔄'
                        WHEN status = 'created' THEN '📝'
                        WHEN status = 'cancelled' THEN '❌'
                        ELSE '❓'
                    END as status_emoji
                FROM tasks 
                GROUP BY status 
                ORDER BY count DESC;
            """)
            
            print("📊 Current task status distribution:")
            for row in cur.fetchall():
                print(f"   {row['status_emoji']} {row['status']}: {row['count']}")
            print()
            
            # Find stale RUNNING tasks
            cur.execute("""
                SELECT 
                    id, 
                    type, 
                    description, 
                    attempts, 
                    owner_id, 
                    locked_by,
                    updated_at,
                    last_heartbeat,
                    lease_expires_at,
                    EXTRACT(EPOCH FROM (NOW() - updated_at))/60 as age_minutes
                FROM tasks 
                WHERE status = 'running' 
                  AND updated_at < NOW() - INTERVAL %s minutes
                ORDER BY updated_at ASC;
            """, (stale_minutes,))
            
            stale_tasks = cur.fetchall()
            
            if not stale_tasks:
                print(f"✅ No stale RUNNING tasks found (older than {stale_minutes} minutes)")
                return
            
            print(f"🚨 Found {len(stale_tasks)} stale RUNNING tasks (older than {stale_minutes} minutes):")
            for task in stale_tasks:
                print(f"   📋 {task['id']} ({task['type']}): {task['description']}")
                print(f"      Age: {task['age_minutes']:.1f} minutes, Attempts: {task['attempts']}")
                print(f"      Owner: {task['owner_id'] or 'None'}, Locked by: {task['locked_by'] or 'None'}")
                print()
            
            if dry_run:
                print("🔍 DRY RUN: No changes would be made")
                return
            
            # Requeue tasks that haven't exceeded max attempts
            cur.execute("""
                UPDATE tasks
                SET status = 'queued',
                    attempts = attempts + 1,
                    owner_id = NULL,
                    lease_expires_at = NULL,
                    updated_at = NOW(),
                    error = COALESCE(error,'') || ' | requeued by admin: stale RUNNING'
                WHERE status = 'running'
                  AND updated_at < NOW() - INTERVAL %s minutes
                  AND (attempts IS NULL OR attempts < %s);
            """, (stale_minutes, max_attempts))
            
            requeued_count = cur.rowcount
            
            # Mark as failed if max attempts exceeded
            cur.execute("""
                UPDATE tasks
                SET status = 'failed',
                    error = COALESCE(error,'') || ' | failed by admin: max requeues exceeded',
                    updated_at = NOW()
                WHERE status = 'running'
                  AND updated_at < NOW() - INTERVAL %s minutes
                  AND attempts >= %s;
            """, (stale_minutes, max_attempts))
            
            failed_count = cur.rowcount
            
            print(f"✅ Cleanup completed:")
            print(f"   🔄 Requeued: {requeued_count} tasks")
            print(f"   ❌ Failed: {failed_count} tasks (max attempts exceeded)")
            
            # Show updated status distribution
            cur.execute("""
                SELECT 
                    status,
                    COUNT(*) as count
                FROM tasks 
                GROUP BY status 
                ORDER BY count DESC;
            """)
            
            print("\n📊 Updated task status distribution:")
            for row in cur.fetchall():
                emoji = {
                    'running': '🔄', 'queued': '⏳', 'completed': '✅', 
                    'failed': '❌', 'retry': '🔄', 'created': '📝', 'cancelled': '❌'
                }.get(row['status'], '❓')
                print(f"   {emoji} {row['status']}: {row['count']}")
                
    except Exception as e:
        log.error(f"Failed to cleanup stale tasks: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Emergency cleanup of stale RUNNING tasks")
    parser.add_argument("--dsn", default=os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore")),
                       help="PostgreSQL connection string")
    parser.add_argument("--stale-minutes", type=int, default=15,
                       help="Consider tasks stale if older than this many minutes (default: 15)")
    parser.add_argument("--max-attempts", type=int, default=3,
                       help="Maximum number of attempts before marking as failed (default: 3)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without making changes")
    
    args = parser.parse_args()
    
    print("🧹 Stale Task Cleanup Tool")
    print(f"🔧 DSN: {args.dsn}")
    print(f"⏰ Stale threshold: {args.stale_minutes} minutes")
    print(f"🔄 Max attempts: {args.max_attempts}")
    if args.dry_run:
        print("🔍 Mode: DRY RUN")
    print()
    
    cleanup_stale_tasks(args.dsn, args.stale_minutes, args.max_attempts, args.dry_run)

if __name__ == "__main__":
    main()
