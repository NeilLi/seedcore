"""
Ray actor pattern example with database connection pooling.

This module demonstrates how to use the connection pooling system
with Ray actors for distributed database operations.
"""

import ray
import asyncio
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text

from seedcore.database import (
    get_async_pg_engine,
    get_async_mysql_engine,
    get_sync_pg_engine,
    get_sync_mysql_engine,
    get_neo4j_driver,
)


@ray.remote
class DatabaseWorkerActor:
    """
    Ray actor that maintains database connections for distributed processing.
    
    This actor demonstrates the recommended pattern for using database
    connection pools with Ray actors. Each actor process maintains its
    own set of database engines and session factories.
    """
    
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        
        # Initialize async engines and session factories
        self.pg_engine = get_async_pg_engine()
        self.mysql_engine = get_async_mysql_engine()
        
        # Create session factories for this actor
        self.pg_session_factory = async_sessionmaker(
            bind=self.pg_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        
        self.mysql_session_factory = async_sessionmaker(
            bind=self.mysql_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        
        # Initialize Neo4j driver
        self.neo4j_driver = get_neo4j_driver()
        
        print(f"DatabaseWorkerActor {worker_id} initialized with connection pools")
    
    async def query_postgresql(self, query: str) -> Dict[str, Any]:
        """
        Execute a PostgreSQL query using the actor's connection pool.
        
        Args:
            query: SQL query to execute
            
        Returns:
            Dict containing query results
        """
        try:
            async with self.pg_session_factory() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                
                return {
                    "worker_id": self.worker_id,
                    "database": "postgresql",
                    "query": query,
                    "results": [dict(row._mapping) for row in rows],
                    "row_count": len(rows)
                }
        except Exception as e:
            return {
                "worker_id": self.worker_id,
                "database": "postgresql",
                "error": str(e),
                "query": query
            }
    
    async def query_mysql(self, query: str) -> Dict[str, Any]:
        """
        Execute a MySQL query using the actor's connection pool.
        
        Args:
            query: SQL query to execute
            
        Returns:
            Dict containing query results
        """
        try:
            async with self.mysql_session_factory() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                
                return {
                    "worker_id": self.worker_id,
                    "database": "mysql",
                    "query": query,
                    "results": [dict(row._mapping) for row in rows],
                    "row_count": len(rows)
                }
        except Exception as e:
            return {
                "worker_id": self.worker_id,
                "database": "mysql",
                "error": str(e),
                "query": query
            }
    
    async def query_neo4j(self, query: str) -> Dict[str, Any]:
        """
        Execute a Neo4j query using the actor's connection pool.
        
        Args:
            query: Cypher query to execute
            
        Returns:
            Dict containing query results
        """
        try:
            session = self.neo4j_driver.session()
            result = await session.run(query)
            records = await result.data()
            await session.close()
            
            return {
                "worker_id": self.worker_id,
                "database": "neo4j",
                "query": query,
                "results": records,
                "record_count": len(records)
            }
        except Exception as e:
            return {
                "worker_id": self.worker_id,
                "database": "neo4j",
                "error": str(e),
                "query": query
            }
    
    async def batch_query_postgresql(self, queries: List[str]) -> List[Dict[str, Any]]:
        """
        Execute multiple PostgreSQL queries in batch.
        
        Args:
            queries: List of SQL queries to execute
            
        Returns:
            List of query results
        """
        results = []
        async with self.pg_session_factory() as session:
            for query in queries:
                try:
                    result = await session.execute(text(query))
                    rows = result.fetchall()
                    results.append({
                        "worker_id": self.worker_id,
                        "database": "postgresql",
                        "query": query,
                        "results": [dict(row._mapping) for row in rows],
                        "row_count": len(rows)
                    })
                except Exception as e:
                    results.append({
                        "worker_id": self.worker_id,
                        "database": "postgresql",
                        "error": str(e),
                        "query": query
                    })
        return results
    
    def get_worker_info(self) -> Dict[str, Any]:
        """
        Get information about this worker actor.
        
        Returns:
            Dict containing worker information
        """
        return {
            "worker_id": self.worker_id,
            "actor_type": "DatabaseWorkerActor",
            "databases": ["postgresql", "mysql", "neo4j"],
            "connection_pools": "initialized"
        }


@ray.remote
class SyncDatabaseWorkerActor:
    """
    Ray actor for sync database operations with connection pooling.
    
    This actor demonstrates how to use sync database connections
    with Ray actors for CPU-bound operations.
    """
    
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        
        # Initialize sync engines
        self.pg_engine = get_sync_pg_engine()
        self.mysql_engine = get_sync_mysql_engine()
        
        print(f"SyncDatabaseWorkerActor {worker_id} initialized with sync connection pools")
    
    def query_postgresql_sync(self, query: str) -> Dict[str, Any]:
        """
        Execute a PostgreSQL query using sync connection pool.
        
        Args:
            query: SQL query to execute
            
        Returns:
            Dict containing query results
        """
        try:
            with self.pg_engine.connect() as connection:
                result = connection.execute(text(query))
                rows = result.fetchall()
                
                return {
                    "worker_id": self.worker_id,
                    "database": "postgresql",
                    "query": query,
                    "results": [dict(row._mapping) for row in rows],
                    "row_count": len(rows),
                    "connection_type": "sync"
                }
        except Exception as e:
            return {
                "worker_id": self.worker_id,
                "database": "postgresql",
                "error": str(e),
                "query": query,
                "connection_type": "sync"
            }
    
    def query_mysql_sync(self, query: str) -> Dict[str, Any]:
        """
        Execute a MySQL query using sync connection pool.
        
        Args:
            query: SQL query to execute
            
        Returns:
            Dict containing query results
        """
        try:
            with self.mysql_engine.connect() as connection:
                result = connection.execute(text(query))
                rows = result.fetchall()
                
                return {
                    "worker_id": self.worker_id,
                    "database": "mysql",
                    "query": query,
                    "results": [dict(row._mapping) for row in rows],
                    "row_count": len(rows),
                    "connection_type": "sync"
                }
        except Exception as e:
            return {
                "worker_id": self.worker_id,
                "database": "mysql",
                "error": str(e),
                "query": query,
                "connection_type": "sync"
            }


# =============================================================================
# Example Usage Functions
# =============================================================================

async def example_distributed_database_operations():
    """
    Example of using Ray actors for distributed database operations.
    
    This function demonstrates how to create multiple database worker
    actors and execute queries across them.
    """
    # Create multiple database worker actors
    actors = [
        DatabaseWorkerActor.remote(f"worker-{i}")
        for i in range(3)
    ]
    
    # Example queries to execute
    pg_queries = [
        "SELECT version() as db_version",
        "SELECT current_database() as current_db",
        "SELECT count(*) as table_count FROM information_schema.tables"
    ]
    
    mysql_queries = [
        "SELECT VERSION() as db_version",
        "SELECT DATABASE() as current_db",
        "SELECT COUNT(*) as table_count FROM information_schema.tables"
    ]
    
    neo4j_queries = [
        "RETURN 'Neo4j is working!' as message",
        "RETURN 1 + 1 as calculation"
    ]
    
    # Execute queries across all actors
    tasks = []
    
    # PostgreSQL queries
    for i, query in enumerate(pg_queries):
        actor = actors[i % len(actors)]
        tasks.append(actor.query_postgresql.remote(query))
    
    # MySQL queries
    for i, query in enumerate(mysql_queries):
        actor = actors[i % len(actors)]
        tasks.append(actor.query_mysql.remote(query))
    
    # Neo4j queries
    for i, query in enumerate(neo4j_queries):
        actor = actors[i % len(actors)]
        tasks.append(actor.query_neo4j.remote(query))
    
    # Wait for all results
    results = await asyncio.gather(*[ray.get(task) for task in tasks])
    
    return results


def example_sync_distributed_operations():
    """
    Example of using sync Ray actors for distributed database operations.
    """
    # Create sync database worker actors
    sync_actors = [
        SyncDatabaseWorkerActor.remote(f"sync-worker-{i}")
        for i in range(2)
    ]
    
    # Example queries
    queries = [
        "SELECT version() as db_version",
        "SELECT current_database() as current_db"
    ]
    
    # Execute queries
    tasks = []
    for i, query in enumerate(queries):
        actor = sync_actors[i % len(sync_actors)]
        tasks.append(actor.query_postgresql_sync.remote(query))
    
    # Get results
    results = ray.get(tasks)
    return results


# =============================================================================
# Utility Functions
# =============================================================================

def create_database_worker_pool(num_workers: int = 3) -> List[ray.actor.ActorHandle]:
    """
    Create a pool of database worker actors.
    
    Args:
        num_workers: Number of worker actors to create
        
    Returns:
        List of actor handles
    """
    return [
        DatabaseWorkerActor.remote(f"worker-{i}")
        for i in range(num_workers)
    ]


async def execute_distributed_batch_query(
    actors: List[ray.actor.ActorHandle],
    queries: List[str],
    database: str = "postgresql"
) -> List[Dict[str, Any]]:
    """
    Execute a batch of queries distributed across multiple actors.
    
    Args:
        actors: List of database worker actors
        queries: List of queries to execute
        database: Target database ("postgresql", "mysql", or "neo4j")
        
    Returns:
        List of query results
    """
    tasks = []
    
    for i, query in enumerate(queries):
        actor = actors[i % len(actors)]
        
        if database == "postgresql":
            tasks.append(actor.query_postgresql.remote(query))
        elif database == "mysql":
            tasks.append(actor.query_mysql.remote(query))
        elif database == "neo4j":
            tasks.append(actor.query_neo4j.remote(query))
        else:
            raise ValueError(f"Unsupported database: {database}")
    
    results = await asyncio.gather(*[ray.get(task) for task in tasks])
    return results 