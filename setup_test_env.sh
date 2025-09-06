#!/bin/bash
# Setup script for database testing environment
# This script sets the correct environment variables for testing with port-forwarded databases

echo "Setting up database test environment..."

# Set database hosts to localhost (for port-forwarding)
export POSTGRES_HOST=localhost
export MYSQL_HOST=localhost
export NEO4J_HOST=localhost

# Update DSNs to use localhost
export PG_DSN=postgresql://postgres:password@localhost:5432/seedcore
export MYSQL_DSN=mysql+pymysql://seedcore:password@localhost:3306/seedcore
export NEO4J_URI=bolt://localhost:7687

# Keep other variables as they were
export POSTGRES_DB=postgres
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=password
export POSTGRES_PORT=5432

export MYSQL_DB=seedcore
export MYSQL_USER=seedcore
export MYSQL_PASSWORD=password
export MYSQL_PORT=3306

export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
export NEO4J_BOLT_PORT=7687
export NEO4J_HTTP_PORT=7474

echo "Environment variables set for localhost testing"
echo "Clearing cached database engines..."

# Clear cached engines to pick up new environment variables
python -c "
import sys
sys.path.insert(0, 'src')
from seedcore.database import get_sync_pg_engine, get_async_pg_engine, get_sync_mysql_engine, get_async_mysql_engine, get_neo4j_driver
get_sync_pg_engine.cache_clear()
get_async_pg_engine.cache_clear() 
get_sync_mysql_engine.cache_clear()
get_async_mysql_engine.cache_clear()
get_neo4j_driver.cache_clear()
print('Cleared all cached database engines')
"

echo ""
echo "Make sure your port-forwarding is active:"
echo "  kubectl port-forward svc/postgresql 5432:5432"
echo "  kubectl port-forward svc/mysql 3306:3306" 
echo "  kubectl port-forward svc/neo4j 7687:7687"
echo ""
echo "You can now run: pytest tests/test_database_pooling.py"
