#!/usr/bin/env python3
"""
Diagnostic script to investigate dispatcher database connection issues.
This script helps diagnose why tasks are stuck in QUEUED status.

Usage:
    python scripts/diagnose_dispatcher_db.py

This script will:
1. Check Ray cluster status and dispatcher actors
2. Test database connectivity
3. Verify the CLAIM_BATCH_SQL query
4. Check dispatcher logs for errors
5. Provide actionable recommendations
"""

import os
import sys
import logging
import time
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

try:
    import ray
    from ray import serve
except ImportError as e:
    logger.error(f"❌ Ray not available: {e}")
    logger.error("Please install Ray: pip install ray[serve]")
    sys.exit(1)

try:
    import asyncpg
except ImportError as e:
    logger.error(f"❌ asyncpg not available: {e}")
    logger.error("Please install asyncpg: pip install asyncpg")
    sys.exit(1)

# Configuration
RAY_NS = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))

# SQL query from dispatcher
CLAIM_BATCH_SQL = """
WITH c AS (
  SELECT id
  FROM tasks
  WHERE status IN ('queued','retry')
    AND (run_after IS NULL OR run_after <= NOW())
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT $1
)
UPDATE tasks t
SET status='running',
    locked_by=$2,
    locked_at=NOW(),
    attempts = t.attempts + 1
FROM c
WHERE t.id = c.id
RETURNING t.id, t.type, t.description, t.params, t.domain, t.drift_score, t.attempts;
"""

class DispatcherDiagnostics:
    """Diagnostic class for dispatcher database issues."""
    
    def __init__(self):
        self.ray_initialized = False
        self.cluster_info = {}
        self.dispatchers = []
        self.db_pool = None
        
    async def initialize_ray(self):
        """Initialize Ray connection."""
        try:
            if not ray.is_initialized():
                ray.init(address="auto", namespace=RAY_NS, ignore_reinit_error=True)
                logger.info("✅ Ray initialized")
            else:
                logger.info("ℹ️ Ray already initialized")
            
            self.ray_initialized = True
            
            # Get cluster info
            try:
                self.cluster_info = ray.cluster_resources()
                logger.info(f"✅ Ray cluster resources: {self.cluster_info}")
            except Exception as e:
                logger.warning(f"⚠️ Could not get cluster resources: {e}")
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize Ray: {e}")
            return False
        return True
    
    async def check_dispatcher_actors(self):
        """Check dispatcher actors status."""
        if not self.ray_initialized:
            logger.error("❌ Ray not initialized")
            return False
            
        try:
            # Find dispatcher actors
            dispatcher_names = []
            for i in range(10):  # Check up to 10 dispatchers
                name = f"seedcore_dispatcher_{i}"
                try:
                    actor = ray.get_actor(name, namespace=RAY_NS)
                    dispatcher_names.append(name)
                    self.dispatchers.append(actor)
                except Exception:
                    break
            
            if not dispatcher_names:
                logger.error("❌ No dispatcher actors found")
                return False
                
            logger.info(f"✅ Found {len(dispatcher_names)} dispatcher(s): {dispatcher_names}")
            
            # Check dispatcher health
            for name, actor in zip(dispatcher_names, self.dispatchers):
                try:
                    # Ping test
                    ping_result = ray.get(actor.ping.remote(), timeout=5.0)
                    if ping_result == "pong":
                        logger.info(f"✅ {name}: ping successful")
                    else:
                        logger.warning(f"⚠️ {name}: ping returned '{ping_result}'")
                except Exception as e:
                    logger.error(f"❌ {name}: ping failed - {e}")
                
                # Get status
                try:
                    status = ray.get(actor.get_status.remote(), timeout=5.0)
                    logger.info(f"📊 {name} status: {json.dumps(status, indent=2)}")
                    
                    # Check for pool errors
                    if status.get("last_pool_error"):
                        logger.error(f"🚨 {name} pool error: {status['last_pool_error']}")
                    
                    if status.get("status") != "healthy":
                        logger.warning(f"⚠️ {name} health status: {status.get('status')}")
                        
                except Exception as e:
                    logger.error(f"❌ {name}: status check failed - {e}")
                    
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to check dispatcher actors: {e}")
            return False
    
    async def test_database_connectivity(self):
        """Test direct database connectivity."""
        try:
            logger.info(f"🔗 Testing database connection to: {PG_DSN}")
            
            # Create a test pool
            self.db_pool = await asyncpg.create_pool(
                dsn=PG_DSN,
                min_size=1,
                max_size=2,
                command_timeout=30.0
            )
            
            # Test basic connection
            async with self.db_pool.acquire() as conn:
                # Test basic query
                result = await conn.fetchval("SELECT 1")
                if result == 1:
                    logger.info("✅ Basic database query successful")
                else:
                    logger.error(f"❌ Unexpected query result: {result}")
                    return False
                
                # Check if tasks table exists
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'tasks'
                    )
                """)
                
                if table_exists:
                    logger.info("✅ Tasks table exists")
                else:
                    logger.error("❌ Tasks table does not exist")
                    return False
                
                # Check table structure
                columns = await conn.fetch("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'tasks'
                    ORDER BY ordinal_position
                """)
                
                logger.info("📊 Tasks table structure:")
                for col in columns:
                    logger.info(f"  - {col['column_name']}: {col['data_type']} (nullable: {col['is_nullable']})")
                
                # Check for queued tasks
                queued_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM tasks WHERE status = 'queued'
                """)
                logger.info(f"📊 Queued tasks count: {queued_count}")
                
                # Check for running tasks
                running_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM tasks WHERE status = 'running'
                """)
                logger.info(f"📊 Running tasks count: {running_count}")
                
                # Check for recent tasks
                recent_tasks = await conn.fetch("""
                    SELECT id, status, created_at, updated_at, locked_by, locked_at
                    FROM tasks
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                    ORDER BY created_at DESC
                    LIMIT 5
                """)
                
                if recent_tasks:
                    logger.info("📊 Recent tasks (last hour):")
                    for task in recent_tasks:
                        logger.info(f"  - ID: {task['id']}, Status: {task['status']}, Created: {task['created_at']}")
                        if task['locked_by']:
                            logger.info(f"    Locked by: {task['locked_by']}, Locked at: {task['locked_at']}")
                else:
                    logger.info("ℹ️ No recent tasks found")
                
            return True
            
        except Exception as e:
            logger.error(f"❌ Database connectivity test failed: {e}")
            return False
    
    async def test_claim_query(self):
        """Test the CLAIM_BATCH_SQL query manually."""
        if not self.db_pool:
            logger.error("❌ No database pool available")
            return False
            
        try:
            logger.info("🧪 Testing CLAIM_BATCH_SQL query manually...")
            
            async with self.db_pool.acquire() as conn:
                # Start a transaction
                async with conn.transaction():
                    # First, check what we have
                    queued_tasks = await conn.fetch("""
                        SELECT id, type, description, created_at
                        FROM tasks
                        WHERE status = 'queued'
                        ORDER BY created_at
                        LIMIT 3
                    """)
                    
                    if not queued_tasks:
                        logger.info("ℹ️ No queued tasks to test with")
                        return True
                    
                    logger.info(f"📊 Found {len(queued_tasks)} queued tasks to test with:")
                    for task in queued_tasks:
                        logger.info(f"  - ID: {task['id']}, Type: {task['type']}, Created: {task['created_at']}")
                    
                    # Test the claim query
                    logger.info("🔒 Testing claim query...")
                    claimed_tasks = await conn.fetch(CLAIM_BATCH_SQL, 1, "diagnostic_test")
                    
                    if claimed_tasks:
                        logger.info(f"✅ Claim query successful! Claimed {len(claimed_tasks)} tasks:")
                        for task in claimed_tasks:
                            logger.info(f"  - ID: {task['id']}, Type: {task['type']}")
                        
                        # Rollback to not actually claim the task
                        await conn.rollback()
                        logger.info("🔄 Rolled back transaction to restore task state")
                    else:
                        logger.info("ℹ️ Claim query returned no tasks (this might be normal)")
                        await conn.rollback()
                
            return True
            
        except Exception as e:
            logger.error(f"❌ Claim query test failed: {e}")
            return False
    
    async def check_serve_deployment(self):
        """Check Ray Serve deployment status."""
        try:
            logger.info("🔍 Checking Ray Serve deployment status...")
            
            # Check if OrganismManager is deployed
            try:
                handle = serve.get_deployment_handle("OrganismManager", app_name="organism")
                logger.info("✅ OrganismManager deployment found")
                
                # Test health endpoint
                try:
                    health = ray.get(handle.health.remote(), timeout=10.0)
                    logger.info(f"📊 OrganismManager health: {json.dumps(health, indent=2)}")
                except Exception as e:
                    logger.warning(f"⚠️ OrganismManager health check failed: {e}")
                    
            except Exception as e:
                logger.error(f"❌ OrganismManager deployment not found: {e}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Serve deployment check failed: {e}")
            return False
    
    async def run_diagnostics(self):
        """Run all diagnostic checks."""
        logger.info("🚀 Starting dispatcher database diagnostics...")
        logger.info(f"🔧 Configuration: namespace={RAY_NS}, dsn={PG_DSN}")
        
        # Initialize Ray
        if not await self.initialize_ray():
            return False
        
        # Check dispatcher actors
        if not await self.check_dispatcher_actors():
            logger.warning("⚠️ Dispatcher actor check failed")
        
        # Check Serve deployment
        if not await self.check_serve_deployment():
            logger.warning("⚠️ Serve deployment check failed")
        
        # Test database connectivity
        if not await self.test_database_connectivity():
            logger.error("❌ Database connectivity test failed")
            return False
        
        # Test claim query
        if not await self.test_claim_query():
            logger.warning("⚠️ Claim query test failed")
        
        # Summary and recommendations
        await self.print_recommendations()
        
        return True
    
    async def print_recommendations(self):
        """Print diagnostic summary and recommendations."""
        logger.info("\n" + "="*80)
        logger.info("📋 DIAGNOSTIC SUMMARY & RECOMMENDATIONS")
        logger.info("="*80)
        
        if not self.dispatchers:
            logger.error("❌ CRITICAL: No dispatcher actors found!")
            logger.info("💡 ACTION: Run bootstrap script to create dispatchers:")
            logger.info("   kubectl exec -it <ray-head-pod> -- python /app/scripts/bootstrap_dispatchers.py")
            return
        
        if not self.db_pool:
            logger.error("❌ CRITICAL: Database connection failed!")
            logger.info("💡 ACTION: Check database pod and connectivity:")
            logger.info("   kubectl get pods -l app=postgres")
            logger.info("   kubectl logs <postgres-pod>")
            return
        
        # Check for common issues
        issues_found = []
        
        for name, actor in zip([f"seedcore_dispatcher_{i}" for i in range(len(self.dispatchers))], self.dispatchers):
            try:
                status = ray.get(actor.get_status.remote(), timeout=5.0)
                
                if status.get("last_pool_error"):
                    issues_found.append(f"{name}: Database pool error - {status['last_pool_error']}")
                
                if status.get("status") != "healthy":
                    issues_found.append(f"{name}: Health status '{status.get('status')}'")
                    
            except Exception as e:
                issues_found.append(f"{name}: Status check failed - {e}")
        
        if issues_found:
            logger.warning("⚠️ ISSUES FOUND:")
            for issue in issues_found:
                logger.warning(f"  - {issue}")
        else:
            logger.info("✅ No obvious issues found with dispatcher actors")
        
        # General recommendations
        logger.info("\n💡 RECOMMENDATIONS:")
        logger.info("1. Check dispatcher logs for database errors:")
        logger.info("   kubectl exec -it <ray-worker-pod> -- tail -f /tmp/ray/session_latest/logs/*Dispatcher*.log")
        
        logger.info("2. Verify database connectivity from Ray worker pods:")
        logger.info("   kubectl exec -it <ray-worker-pod> -- psql -h postgresql -U postgres -d seedcore -c 'SELECT 1'")
        
        logger.info("3. Check if tasks table has proper indexes:")
        logger.info("   kubectl exec -it <postgres-pod> -- psql -U postgres -d seedcore -c '\\d+ tasks'")
        
        logger.info("4. Monitor dispatcher health in real-time:")
        logger.info("   kubectl exec -it <ray-head-pod> -- python -c \"import ray; ray.init(); print(ray.get_actor('seedcore_dispatcher_0', namespace='seedcore-dev').get_status.remote())\"")
        
        logger.info("5. If issues persist, restart dispatchers:")
        logger.info("   kubectl exec -it <ray-head-pod> -- python /app/scripts/bootstrap_dispatchers.py")
        
        logger.info("\n🔍 NEXT STEPS:")
        logger.info("- Check the specific error messages in dispatcher logs")
        logger.info("- Verify database connection string and credentials")
        logger.info("- Ensure database has proper permissions and is not locked")
        logger.info("- Check for any database maintenance or backup processes")
        
        logger.info("="*80)
    
    async def cleanup(self):
        """Clean up resources."""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("🧹 Database pool closed")

async def main():
    """Main diagnostic function."""
    diagnostics = DispatcherDiagnostics()
    
    try:
        success = await diagnostics.run_diagnostics()
        if success:
            logger.info("✅ Diagnostics completed successfully")
        else:
            logger.error("❌ Diagnostics completed with errors")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("🛑 Diagnostics interrupted by user")
    except Exception as e:
        logger.exception(f"❌ Diagnostics failed with exception: {e}")
        sys.exit(1)
    finally:
        await diagnostics.cleanup()

if __name__ == "__main__":
    asyncio.run(main())

