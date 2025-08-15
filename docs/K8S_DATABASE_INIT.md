# Kubernetes Database Initialization Guide

## Problem
The SeedCore API is failing to start because the required database tables don't exist:
```
asyncpg.exceptions.UndefinedTableError: relation "holons" does not exist
```

## Solution
You need to initialize the database schemas by running the initialization scripts in your running database pods.

## Quick Fix (Manual Steps)

### 1. Initialize PostgreSQL (Required - Creates `holons` table)

```bash
# Find your PostgreSQL pod
kubectl get pods -n seedcore-dev -l app=postgresql

# Copy the initialization script to the pod
kubectl cp docker/setup/init_pgvector.sql seedcore-dev/[POSTGRES_POD_NAME]:/tmp/init_pgvector.sql

# Run the initialization script
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d postgres -f /tmp/init_pgvector.sql
```

### 2. Initialize MySQL (Optional)

```bash
# Find your MySQL pod
kubectl get pods -n seedcore-dev -l app=mysql

# Copy the initialization script to the pod
kubectl cp docker/setup/init_mysql.sql seedcore-dev/[MYSQL_POD_NAME]:/tmp/init_mysql.sql

# Run the initialization script
kubectl exec -n seedcore-dev [MYSQL_POD_NAME] -- mysql -u seedcore -ppassword seedcore < /tmp/init_mysql.sql
```

### 3. Initialize Neo4j (Optional)

```bash
# Find your Neo4j pod
kubectl get pods -n seedcore-dev -l app=neo4j

# Copy the initialization script to the pod
kubectl cp docker/setup/init_neo4j.cypher seedcore-dev/[NEO4J_POD_NAME]:/tmp/init_neo4j.cypher

# Run the initialization script
kubectl exec -n seedcore-dev [NEO4J_POD_NAME] -- cypher-shell -u neo4j -p password -f /tmp/init_neo4j.cypher
```

## Automated Fix

Use the provided script:

```bash
# Run the automated initialization script
./scripts/init_databases_k8s.sh

# Or specify a different namespace
./scripts/init_databases_k8s.sh your-namespace
```

## What the Scripts Create

### PostgreSQL (`init_pgvector.sql`)
- Enables the `vector` extension
- Creates the `holons` table with:
  - `id`: Serial primary key
  - `uuid`: Unique UUID for each holon
  - `embedding`: 768-dimensional vector for similarity search
  - `meta`: JSONB metadata
  - `created_at`: Timestamp
- Creates HNSW index for vector similarity search
- Inserts sample data

### MySQL (`init_mysql.sql`)
- Creates the `seedcore` database
- Creates example tables
- Creates `flashbulb_incidents` table for memory management

### Neo4j (`init_neo4j.cypher`)
- Creates constraints and indexes
- Creates sample Holon nodes
- Creates sample relationships

## Verification

After running the initialization scripts, verify the tables exist:

```bash
# Check PostgreSQL
kubectl exec -n seedcore-dev [POSTGRES_POD_NAME] -- psql -U postgres -d postgres -c "SELECT COUNT(*) FROM holons;"

# Check MySQL
kubectl exec -n seedcore-dev [MYSQL_POD_NAME] -- mysql -u seedcore -ppassword seedcore -e "SHOW TABLES;"

# Check Neo4j
kubectl exec -n seedcore-dev [NEO4J_POD_NAME] -- cypher-shell -u neo4j -p password -c "MATCH (h:Holon) RETURN COUNT(h) as count;"
```

## Next Steps

1. **Restart your seedcore-api pod** to pick up the new database schema
2. **Check the logs** to ensure no more database errors
3. **Verify the application** is working correctly

## Troubleshooting

### If the script fails:
- Make sure your database pods are running and healthy
- Check that you have the correct namespace
- Verify that kubectl has access to your cluster
- Check the pod labels match what the script expects

### If tables still don't exist:
- Check the database pod logs for errors
- Verify the initialization scripts ran successfully
- Ensure the database credentials are correct
- Check if there are permission issues

## Notes

- The `holons` table is **required** for the application to start
- MySQL and Neo4j are **optional** but recommended for full functionality
- Sample data is inserted to help with testing
- The scripts use `IF NOT EXISTS` so they're safe to run multiple times
