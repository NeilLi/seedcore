"""
Database Configuration Example
============================

This file demonstrates the proper configuration for database connections,
especially for async MySQL support with aiomysql driver.

Environment Variables Setup:
---------------------------

# PostgreSQL
export POSTGRES_HOST="postgresql"
export POSTGRES_PORT="5432"
export POSTGRES_DB="postgres"
export POSTGRES_USER="postgres"
export POSTGRES_PASSWORD="your_password"
export PG_DSN="postgresql://postgres:your_password@postgresql:5432/seedcore"

# MySQL - Sync (PyMySQL driver)
export MYSQL_HOST="mysql"
export MYSQL_PORT="3306"
export MYSQL_DB="seedcore"
export MYSQL_USER="seedcore"
export MYSQL_PASSWORD="your_password"
export MYSQL_DSN="mysql+pymysql://seedcore:your_password@mysql:3306/seedcore"

# MySQL - Async (aiomysql driver) - OPTION 1: Separate variable
export MYSQL_DSN_ASYNC="mysql+aiomysql://seedcore:your_password@mysql:3306/seedcore"

# MySQL - Async (aiomysql driver) - OPTION 2: Auto-conversion
# If you only set MYSQL_DSN, the system will automatically convert
# mysql+pymysql:// to mysql+aiomysql:// for async connections

# Connection Pool Settings
export MYSQL_POOL_SIZE="10"
export MYSQL_POOL_MAX_OVERFLOW="20"
export MYSQL_POOL_TIMEOUT="30"
export MYSQL_POOL_RECYCLE="1800"
export MYSQL_POOL_PRE_PING="true"

# Neo4j
export NEO4J_URI="neo4j://neo4j:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your_password"
export NEO4J_POOL_SIZE="10"

Usage Examples:
--------------

1. Sync MySQL Connection:
   from seedcore.database import get_sync_mysql_session
   
   session = get_sync_mysql_session()
   try:
       result = session.execute(text("SELECT 1"))
       print(result.scalar())
   finally:
       session.close()

2. Async MySQL Connection:
   from seedcore.database import get_async_mysql_session
   
   async with get_async_mysql_session() as session:
       try:
           result = await session.execute(text("SELECT 1"))
           print(result.scalar())
       finally:
           await session.close()

3. Engine Creation:
   from seedcore.database import get_async_mysql_engine, get_sync_mysql_engine
   
   # These are cached singletons
   async_engine = get_async_mysql_engine()
   sync_engine = get_sync_mysql_engine()

4. Pool Statistics:
   from seedcore.database import get_mysql_pool_stats
   
   stats = get_mysql_pool_stats()
   print(f"Pool size: {stats['size']}")
   print(f"Checked out: {stats['checked_out']}")
   print(f"Checked in: {stats['checked_in']}")
   print(f"Overflow: {stats['overflow']}")

Troubleshooting:
---------------

1. "pymysql is not async" error:
   - Ensure MYSQL_DSN_ASYNC uses mysql+aiomysql://
   - Or let the system auto-convert MYSQL_DSN

2. "cryptography package is required" error:
   - Install: pip install cryptography
   - Or change MySQL user to use mysql_native_password:
     ALTER USER 'seedcore'@'%' IDENTIFIED WITH mysql_native_password BY 'password';

3. Pool statistics errors:
   - The system now uses safe pool stats collection
   - Missing attributes will return None instead of crashing

4. Connection timeout issues:
   - Increase MYSQL_POOL_TIMEOUT
   - Check network connectivity
   - Verify MySQL server is running and accessible
"""

# This file is for documentation purposes only
# Import the actual database functions from seedcore.database

