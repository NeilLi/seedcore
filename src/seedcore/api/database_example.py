"""
Example FastAPI integration with database connection pooling.

This module demonstrates how to use the new connection pooling system
in FastAPI endpoints for both async and sync operations.
"""

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import text

from seedcore.database import (
    get_async_pg_session,
    get_async_mysql_session,
    get_sync_pg_session,
    get_sync_mysql_session,
    get_neo4j_session,
    check_pg_health,
    check_mysql_health,
    check_neo4j_health,
    get_pg_pool_stats,
    get_mysql_pool_stats,
)

app = FastAPI(title="SeedCore Database API", version="1.0.0")


# =============================================================================
# Async PostgreSQL Endpoints
# =============================================================================

@app.get("/async/pg/health")
async def async_pg_health():
    """Check async PostgreSQL connection health."""
    is_healthy = await check_pg_health()
    if not is_healthy:
        raise HTTPException(status_code=503, detail="PostgreSQL connection unhealthy")
    return {"status": "healthy", "database": "postgresql"}


@app.get("/async/pg/test")
async def async_pg_test(session: AsyncSession = Depends(get_async_pg_session)):
    """Test async PostgreSQL connection with a simple query."""
    try:
        result = await session.execute(text("SELECT version()"))
        version = result.scalar()
        return {"database": "postgresql", "version": version, "connection": "async"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# =============================================================================
# Async MySQL Endpoints
# =============================================================================

@app.get("/async/mysql/health")
async def async_mysql_health():
    """Check async MySQL connection health."""
    is_healthy = await check_mysql_health()
    if not is_healthy:
        raise HTTPException(status_code=503, detail="MySQL connection unhealthy")
    return {"status": "healthy", "database": "mysql"}


@app.get("/async/mysql/test")
async def async_mysql_test(session: AsyncSession = Depends(get_async_mysql_session)):
    """Test async MySQL connection with a simple query."""
    try:
        result = await session.execute(text("SELECT VERSION()"))
        version = result.scalar()
        return {"database": "mysql", "version": version, "connection": "async"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# =============================================================================
# Sync PostgreSQL Endpoints
# =============================================================================

@app.get("/sync/pg/test")
def sync_pg_test():
    """Test sync PostgreSQL connection with a simple query."""
    try:
        session = get_sync_pg_session()
        result = session.execute(text("SELECT version()"))
        version = result.scalar()
        session.close()
        return {"database": "postgresql", "version": version, "connection": "sync"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# =============================================================================
# Sync MySQL Endpoints
# =============================================================================

@app.get("/sync/mysql/test")
def sync_mysql_test():
    """Test sync MySQL connection with a simple query."""
    try:
        session = get_sync_mysql_session()
        result = session.execute(text("SELECT VERSION()"))
        version = result.scalar()
        session.close()
        return {"database": "mysql", "version": version, "connection": "sync"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# =============================================================================
# Neo4j Endpoints
# =============================================================================

@app.get("/neo4j/health")
async def neo4j_health():
    """Check Neo4j connection health."""
    is_healthy = await check_neo4j_health()
    if not is_healthy:
        raise HTTPException(status_code=503, detail="Neo4j connection unhealthy")
    return {"status": "healthy", "database": "neo4j"}


@app.get("/neo4j/test")
async def neo4j_test():
    """Test Neo4j connection with a simple query."""
    try:
        async with get_neo4j_session() as session:
            result = await session.run("RETURN 'Neo4j is working!' as message")
            record = await result.single()
            return {"database": "neo4j", "message": record["message"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# =============================================================================
# Pool Statistics Endpoints
# =============================================================================

@app.get("/stats/pg")
def pg_pool_stats():
    """Get PostgreSQL connection pool statistics."""
    try:
        stats = get_pg_pool_stats()
        return {
            "database": "postgresql",
            "pool_stats": stats,
            "utilization_percent": round((stats["checked_out"] / stats["size"]) * 100, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting pool stats: {str(e)}")


@app.get("/stats/mysql")
def mysql_pool_stats():
    """Get MySQL connection pool statistics."""
    try:
        stats = get_mysql_pool_stats()
        return {
            "database": "mysql",
            "pool_stats": stats,
            "utilization_percent": round((stats["checked_out"] / stats["size"]) * 100, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting pool stats: {str(e)}")


# =============================================================================
# Combined Health Check
# =============================================================================

@app.get("/health/all")
async def all_databases_health():
    """Check health of all databases."""
    results = {
        "postgresql": await check_pg_health(),
        "mysql": await check_mysql_health(),
        "neo4j": await check_neo4j_health(),
    }
    
    all_healthy = all(results.values())
    status_code = 200 if all_healthy else 503
    
    return {
        "status": "healthy" if all_healthy else "unhealthy",
        "databases": results,
        "all_healthy": all_healthy
    }


# =============================================================================
# Example Business Logic Endpoint
# =============================================================================

@app.get("/example/complex-query")
async def complex_query_example(
    pg_session: AsyncSession = Depends(get_async_pg_session),
    mysql_session: AsyncSession = Depends(get_async_mysql_session)
):
    """
    Example of using multiple database connections in a single endpoint.
    
    This demonstrates how the connection pooling system handles multiple
    concurrent database operations efficiently.
    """
    try:
        # PostgreSQL query
        pg_result = await pg_session.execute(text("SELECT COUNT(*) FROM information_schema.tables"))
        pg_count = pg_result.scalar()
        
        # MySQL query
        mysql_result = await mysql_session.execute(text("SELECT COUNT(*) FROM information_schema.tables"))
        mysql_count = mysql_result.scalar()
        
        return {
            "postgresql_tables": pg_count,
            "mysql_tables": mysql_count,
            "total_tables": pg_count + mysql_count,
            "message": "Successfully queried both databases using connection pools"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Complex query error: {str(e)}") 