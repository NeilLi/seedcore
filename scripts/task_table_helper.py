#!/usr/bin/env python3
"""
Task Table Helper - Comprehensive task management and monitoring utility

This script provides utilities for:
- Displaying task information with task_id printing
- Filtering tasks by status, type, domain, etc.
- Monitoring task statistics and health
- Database connection management
- Task lifecycle tracking

Usage:
    python scripts/task_table_helper.py --help
    python scripts/task_table_helper.py list --status running
    python scripts/task_table_helper.py stats
    python scripts/task_table_helper.py show <task_id>
"""

import os
import sys
import argparse
import asyncio
import json
import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import asyncpg
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError as e:
    print(f"❌ Missing required dependencies: {e}")
    print("Please install: pip install asyncpg psycopg2-binary")
    sys.exit(1)

# Configuration
DEFAULT_DSN = os.getenv("PG_DSN") or os.getenv("SEEDCORE_PG_DSN", "postgresql://postgres:postgres@localhost:5432/seedcore")
DEFAULT_LIMIT = 50

class TaskStatus(Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"

@dataclass
class TaskInfo:
    """Represents a task with all its information."""
    id: str
    status: str
    type: str
    description: Optional[str]
    domain: Optional[str]
    drift_score: float
    attempts: int
    locked_by: Optional[str]
    locked_at: Optional[datetime.datetime]
    run_after: Optional[datetime.datetime]
    params: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime

class TaskTableHelper:
    """Main helper class for task table operations."""
    
    def __init__(self, dsn: str = DEFAULT_DSN):
        self.dsn = dsn
        self.pool = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_pool()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.pool:
            await self.pool.close()
    
    async def _ensure_pool(self):
        """Ensure database connection pool is available."""
        if self.pool is None:
            try:
                print(f"🔌 Connecting to database: {self.dsn.split('@')[-1] if '@' in self.dsn else self.dsn}")
                self.pool = await asyncpg.create_pool(
                    dsn=self.dsn,
                    min_size=1,
                    max_size=4,
                    command_timeout=30.0
                )
                print("✅ Database connection pool created successfully")
                
                # Test the connection
                await self._test_connection()
                
            except Exception as e:
                print(f"❌ Failed to create database connection pool: {e}")
                print(f"💡 Try setting PG_DSN environment variable or check your database connection")
                print(f"💡 Example: export PG_DSN='postgresql://user:pass@localhost:5432/dbname'")
                print(f"💡 Common connection strings:")
                print(f"   - Local: postgresql://postgres:postgres@localhost:5432/seedcore")
                print(f"   - Docker: postgresql://postgres:postgres@postgresql:5432/seedcore")
                print(f"   - Kubernetes: postgresql://postgres:postgres@postgresql-service:5432/seedcore")
                raise
    
    async def _test_connection(self):
        """Test database connection and show basic info."""
        try:
            async with self.pool.acquire() as conn:
                # Test basic connectivity
                version = await conn.fetchval("SELECT version()")
                print(f"📊 Database version: {version.split()[1] if version else 'Unknown'}")
                
                # Check if tasks table exists
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'tasks'
                    )
                """)
                
                if table_exists:
                    # Get task count
                    task_count = await conn.fetchval("SELECT COUNT(*) FROM tasks")
                    print(f"📋 Tasks table found with {task_count} tasks")
                else:
                    print("⚠️  Tasks table not found - this may be a new database")
                    
        except Exception as e:
            print(f"⚠️  Connection test failed: {e}")
            # Don't raise here, just warn
    
    def _format_datetime(self, dt: Optional[datetime.datetime]) -> str:
        """Format datetime for display."""
        if dt is None:
            return "N/A"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    def _format_duration(self, start: datetime.datetime, end: Optional[datetime.datetime] = None) -> str:
        """Format duration between two timestamps."""
        if end is None:
            end = datetime.datetime.now(datetime.timezone.utc)
        
        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=datetime.timezone.utc)
        
        duration = end - start
        total_seconds = int(duration.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            return f"{total_seconds // 60}m {total_seconds % 60}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    
    def _truncate_text(self, text: str, max_length: int = 50) -> str:
        """Truncate text to specified length."""
        if not text:
            return "N/A"
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + "..."
    
    def _get_status_emoji(self, status: str) -> str:
        """Get emoji for task status."""
        status_emojis = {
            "created": "🆕",
            "queued": "⏳",
            "running": "🏃",
            "completed": "✅",
            "failed": "❌",
            "cancelled": "🚫",
            "retry": "🔄"
        }
        return status_emojis.get(status, "❓")
    
    def print_task_id(self, task_id: str, prefix: str = "Task ID: ") -> None:
        """Print task ID with formatting."""
        print(f"{prefix}{task_id}")
    
    def print_task_header(self) -> None:
        """Print table header for task listing."""
        print("\n" + "="*120)
        print(f"{'ID':<8} {'Status':<10} {'Type':<15} {'Description':<30} {'Domain':<12} {'Attempts':<8} {'Updated':<20}")
        print("="*120)
    
    def print_task_row(self, task: TaskInfo, show_full_id: bool = False) -> None:
        """Print a single task row with formatting."""
        task_id = task.id if show_full_id else task.id[:8]
        status_emoji = self._get_status_emoji(task.status)
        status = f"{status_emoji} {task.status}"
        task_type = self._truncate_text(task.type, 15)
        description = self._truncate_text(task.description or "N/A", 30)
        domain = self._truncate_text(task.domain or "N/A", 12)
        attempts = str(task.attempts)
        updated = self._format_datetime(task.updated_at)
        
        print(f"{task_id:<8} {status:<10} {task_type:<15} {description:<30} {domain:<12} {attempts:<8} {updated:<20}")
    
    def print_task_details(self, task: TaskInfo) -> None:
        """Print detailed task information."""
        print("\n" + "="*80)
        print(f"📋 TASK DETAILS")
        print("="*80)
        
        # Basic info
        self.print_task_id(task.id, "🆔 Task ID: ")
        print(f"📊 Status: {self._get_status_emoji(task.status)} {task.status}")
        print(f"🏷️  Type: {task.type}")
        print(f"📝 Description: {task.description or 'N/A'}")
        print(f"🌐 Domain: {task.domain or 'N/A'}")
        print(f"📈 Drift Score: {task.drift_score}")
        print(f"🔄 Attempts: {task.attempts}")
        
        # Timing info
        print(f"\n⏰ TIMING:")
        print(f"   Created: {self._format_datetime(task.created_at)}")
        print(f"   Updated: {self._format_datetime(task.updated_at)}")
        
        if task.locked_at:
            print(f"   Locked: {self._format_datetime(task.locked_at)}")
            if task.status == "running":
                duration = self._format_duration(task.locked_at)
                print(f"   Running for: {duration}")
        
        if task.run_after:
            print(f"   Run After: {self._format_datetime(task.run_after)}")
        
        # Locking info
        if task.locked_by:
            print(f"\n🔒 LOCKING:")
            print(f"   Locked By: {task.locked_by}")
        
        # Parameters
        if task.params:
            print(f"\n⚙️  PARAMETERS:")
            try:
                params_str = json.dumps(task.params, indent=2)
                if len(params_str) > 200:
                    params_str = params_str[:200] + "..."
                print(f"   {params_str}")
            except Exception:
                print(f"   {str(task.params)[:200]}")
        
        # Result or Error
        if task.result:
            print(f"\n✅ RESULT:")
            try:
                result_str = json.dumps(task.result, indent=2)
                if len(result_str) > 300:
                    result_str = result_str[:300] + "..."
                print(f"   {result_str}")
            except Exception:
                print(f"   {str(task.result)[:300]}")
        
        if task.error:
            print(f"\n❌ ERROR:")
            print(f"   {task.error}")
        
        print("="*80)
    
    async def get_task_by_id(self, task_id: str) -> Optional[TaskInfo]:
        """Get a single task by ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, status, type, description, domain, drift_score, attempts,
                       locked_by, locked_at, run_after, params, result, error,
                       created_at, updated_at
                FROM tasks
                WHERE id = $1
            """, task_id)
            
            if not row:
                return None
            
            return TaskInfo(
                id=str(row['id']),
                status=row['status'],
                type=row['type'],
                description=row['description'],
                domain=row['domain'],
                drift_score=float(row['drift_score'] or 0.0),
                attempts=int(row['attempts'] or 0),
                locked_by=row['locked_by'],
                locked_at=row['locked_at'],
                run_after=row['run_after'],
                params=row['params'] or {},
                result=row['result'],
                error=row['error'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
    
    async def list_tasks(self, 
                        status: Optional[str] = None,
                        task_type: Optional[str] = None,
                        domain: Optional[str] = None,
                        limit: int = DEFAULT_LIMIT,
                        show_full_id: bool = False) -> List[TaskInfo]:
        """List tasks with optional filtering."""
        query = """
            SELECT id, status, type, description, domain, drift_score, attempts,
                   locked_by, locked_at, run_after, params, result, error,
                   created_at, updated_at
            FROM tasks
            WHERE 1=1
        """
        params = []
        param_count = 0
        
        if status:
            param_count += 1
            query += f" AND status = ${param_count}"
            params.append(status)
        
        if task_type:
            param_count += 1
            query += f" AND type = ${param_count}"
            params.append(task_type)
        
        if domain:
            param_count += 1
            query += f" AND domain = ${param_count}"
            params.append(domain)
        
        query += " ORDER BY updated_at DESC"
        
        if limit > 0:
            param_count += 1
            query += f" LIMIT ${param_count}"
            params.append(limit)
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            
            tasks = []
            for row in rows:
                tasks.append(TaskInfo(
                    id=str(row['id']),
                    status=row['status'],
                    type=row['type'],
                    description=row['description'],
                    domain=row['domain'],
                    drift_score=float(row['drift_score'] or 0.0),
                    attempts=int(row['attempts'] or 0),
                    locked_by=row['locked_by'],
                    locked_at=row['locked_at'],
                    run_after=row['run_after'],
                    params=row['params'] or {},
                    result=row['result'],
                    error=row['error'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                ))
            
            return tasks
    
    async def get_task_statistics(self) -> Dict[str, Any]:
        """Get comprehensive task statistics."""
        async with self.pool.acquire() as conn:
            # Status counts
            status_counts = await conn.fetch("""
                SELECT status, COUNT(*) as count
                FROM tasks
                GROUP BY status
                ORDER BY count DESC
            """)
            
            # Type counts
            type_counts = await conn.fetch("""
                SELECT type, COUNT(*) as count
                FROM tasks
                GROUP BY type
                ORDER BY count DESC
                LIMIT 10
            """)
            
            # Domain counts
            domain_counts = await conn.fetch("""
                SELECT domain, COUNT(*) as count
                FROM tasks
                WHERE domain IS NOT NULL
                GROUP BY domain
                ORDER BY count DESC
                LIMIT 10
            """)
            
            # Recent activity
            recent_activity = await conn.fetch("""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as created_count,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_count
                FROM tasks
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """)
            
            # Long running tasks
            long_running = await conn.fetch("""
                SELECT id, type, locked_by, locked_at, attempts
                FROM tasks
                WHERE status = 'running'
                  AND locked_at < NOW() - INTERVAL '10 minutes'
                ORDER BY locked_at ASC
                LIMIT 10
            """)
            
            # Failed tasks with high attempts
            high_attempts = await conn.fetch("""
                SELECT id, type, attempts, error, updated_at
                FROM tasks
                WHERE attempts >= 3
                ORDER BY attempts DESC, updated_at DESC
                LIMIT 10
            """)
            
            return {
                "status_counts": {row['status']: row['count'] for row in status_counts},
                "type_counts": {row['type']: row['count'] for row in type_counts},
                "domain_counts": {row['domain']: row['count'] for row in domain_counts},
                "recent_activity": [dict(row) for row in recent_activity],
                "long_running": [dict(row) for row in long_running],
                "high_attempts": [dict(row) for row in high_attempts]
            }
    
    def print_statistics(self, stats: Dict[str, Any]) -> None:
        """Print formatted statistics."""
        print("\n" + "="*80)
        print("📊 TASK STATISTICS")
        print("="*80)
        
        # Status summary
        print("\n📈 STATUS SUMMARY:")
        total_tasks = sum(stats['status_counts'].values())
        for status, count in stats['status_counts'].items():
            emoji = self._get_status_emoji(status)
            percentage = (count / total_tasks * 100) if total_tasks > 0 else 0
            print(f"   {emoji} {status:<12}: {count:>6} ({percentage:5.1f}%)")
        print(f"   {'📊 Total':<12}: {total_tasks:>6}")
        
        # Top task types
        if stats['type_counts']:
            print("\n🏷️  TOP TASK TYPES:")
            for task_type, count in list(stats['type_counts'].items())[:5]:
                print(f"   {task_type:<20}: {count:>6}")
        
        # Top domains
        if stats['domain_counts']:
            print("\n🌐 TOP DOMAINS:")
            for domain, count in list(stats['domain_counts'].items())[:5]:
                print(f"   {domain:<20}: {count:>6}")
        
        # Recent activity
        if stats['recent_activity']:
            print("\n📅 RECENT ACTIVITY (7 days):")
            for activity in stats['recent_activity'][:7]:
                date = activity['date']
                created = activity['created_count']
                completed = activity['completed_count']
                failed = activity['failed_count']
                print(f"   {date}: Created {created}, Completed {completed}, Failed {failed}")
        
        # Long running tasks
        if stats['long_running']:
            print("\n⏰ LONG RUNNING TASKS (>10 min):")
            for task in stats['long_running']:
                task_id = task['id'][:8]
                locked_at = self._format_datetime(task['locked_at'])
                duration = self._format_duration(task['locked_at'])
                print(f"   {task_id} [{task['type']}] - {duration} (locked by {task['locked_by']})")
        
        # High attempt tasks
        if stats['high_attempts']:
            print("\n🔄 HIGH ATTEMPT TASKS (≥3 attempts):")
            for task in stats['high_attempts']:
                task_id = task['id'][:8]
                updated = self._format_datetime(task['updated_at'])
                error = self._truncate_text(task['error'] or "N/A", 40)
                print(f"   {task_id} [{task['type']}] - {task['attempts']} attempts, {updated}")
                if task['error']:
                    print(f"      Error: {error}")
        
        print("="*80)

async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Task Table Helper - Comprehensive task management utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s test                           # Test database connection
  %(prog)s list                           # List all tasks
  %(prog)s list --status running          # List running tasks
  %(prog)s list --type graph_embed        # List graph embedding tasks
  %(prog)s list --domain user_123         # List tasks for specific domain
  %(prog)s show <task_id>                 # Show detailed task info
  %(prog)s stats                          # Show task statistics
  %(prog)s stats --json                   # Show statistics as JSON
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List tasks')
    list_parser.add_argument('--status', choices=[s.value for s in TaskStatus], 
                           help='Filter by task status')
    list_parser.add_argument('--type', help='Filter by task type')
    list_parser.add_argument('--domain', help='Filter by domain')
    list_parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT,
                           help=f'Limit number of results (default: {DEFAULT_LIMIT})')
    list_parser.add_argument('--full-id', action='store_true',
                           help='Show full task IDs instead of truncated')
    list_parser.add_argument('--dsn', default=DEFAULT_DSN,
                           help='Database connection string')
    
    # Show command
    show_parser = subparsers.add_parser('show', help='Show detailed task information')
    show_parser.add_argument('task_id', help='Task ID to show')
    show_parser.add_argument('--dsn', default=DEFAULT_DSN,
                           help='Database connection string')
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show task statistics')
    stats_parser.add_argument('--json', action='store_true',
                            help='Output statistics as JSON')
    stats_parser.add_argument('--dsn', default=DEFAULT_DSN,
                            help='Database connection string')
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Test database connection')
    test_parser.add_argument('--dsn', default=DEFAULT_DSN,
                           help='Database connection string')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        async with TaskTableHelper(args.dsn) as helper:
            if args.command == 'list':
                tasks = await helper.list_tasks(
                    status=args.status,
                    task_type=args.type,
                    domain=args.domain,
                    limit=args.limit,
                    show_full_id=args.full_id
                )
                
                if not tasks:
                    print("No tasks found matching the criteria.")
                    return
                
                helper.print_task_header()
                for task in tasks:
                    helper.print_task_row(task, show_full_id=args.full_id)
                
                print(f"\n📊 Found {len(tasks)} tasks")
                
            elif args.command == 'show':
                task = await helper.get_task_by_id(args.task_id)
                if not task:
                    print(f"❌ Task not found: {args.task_id}")
                    return
                
                helper.print_task_details(task)
                
            elif args.command == 'stats':
                stats = await helper.get_task_statistics()
                if args.json:
                    print(json.dumps(stats, indent=2, default=str))
                else:
                    helper.print_statistics(stats)
            
            elif args.command == 'test':
                print("✅ Database connection test completed successfully")
                print("💡 You can now use other commands like 'list', 'show', or 'stats'")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        print(f"\n💡 Troubleshooting tips:")
        print(f"   1. Check if PostgreSQL is running")
        print(f"   2. Verify your connection string with: ./task_table_helper.py test --dsn 'your_connection_string'")
        print(f"   3. Set PG_DSN environment variable: export PG_DSN='your_connection_string'")
        print(f"   4. For Docker: postgresql://postgres:postgres@localhost:5432/seedcore")
        print(f"   5. For local: postgresql://postgres:postgres@localhost:5432/seedcore")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
