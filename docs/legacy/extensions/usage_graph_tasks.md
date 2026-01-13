# Graph Tasks Usage Guide

## Quick Start

### 1. Create Graph Embedding Task
```sql
-- Embed 2-hop neighborhood around node 123
SELECT create_graph_embed_task(
    ARRAY[123], 
    2, 
    'Embed neighborhood around user node 123'
);

-- Multiple starting nodes
SELECT create_graph_embed_task(
    ARRAY[123, 456, 789], 
    3, 
    'Embed extended neighborhood around multiple nodes'
);
```

### 2. Create RAG Query Task
```sql
-- RAG query with 2-hop neighborhood, top 15 results
SELECT create_graph_rag_task(
    ARRAY[123], 
    2, 
    15, 
    'Find similar nodes to user 123 for RAG augmentation'
);
```

### 3. Monitor Tasks
```sql
-- View all graph tasks
SELECT * FROM graph_tasks ORDER BY updated_at DESC LIMIT 10;

-- View specific task types
SELECT * FROM graph_tasks WHERE type = 'graph_embed';

-- Check task status
SELECT id, type, status, attempts, error, updated_at 
FROM graph_tasks 
WHERE status IN ('queued', 'running', 'failed');
```

### 4. Check Results
```sql
-- View completed tasks with results
SELECT id, type, params, result, created_at, updated_at
FROM tasks 
WHERE type IN ('graph_embed', 'graph_rag_query')
  AND status = 'completed'
ORDER BY updated_at DESC;

-- Check for errors
SELECT id, type, params, error, attempts, updated_at
FROM tasks 
WHERE type IN ('graph_embed', 'graph_rag_query')
  AND status = 'failed'
ORDER BY updated_at DESC;
```

## Task Parameters

### graph_embed
- `start_ids`: Array of Neo4j node IDs
- `k`: Number of hops for neighborhood expansion
- `description`: Human-readable task description

### graph_rag_query
- `start_ids`: Array of Neo4j node IDs
- `k`: Number of hops for neighborhood expansion
- `topk`: Number of similar nodes to return
- `description`: Human-readable task description

## Monitoring Commands

### Check Ray Actors
```bash
ray list actors | grep graph_dispatcher
```

### Check Database Status
```sql
-- Count tasks by status
SELECT status, COUNT(*) as count
FROM tasks 
WHERE type IN ('graph_embed', 'graph_rag_query')
GROUP BY status;

-- Recent activity
SELECT 
    type,
    status,
    COUNT(*) as count,
    MAX(updated_at) as last_updated
FROM tasks 
WHERE type IN ('graph_embed', 'graph_rag_query')
  AND updated_at > NOW() - INTERVAL '1 hour'
GROUP BY type, status;
```

## Troubleshooting

### Common Issues
1. **Task stuck in QUEUED**: Check if GraphDispatcher is running
2. **Task failed**: Check error message and retry count
3. **Memory issues**: Reduce k-hop depth or node limits

### Debug Commands
```sql
-- Check task details
SELECT * FROM tasks WHERE id = 'your-task-id';

-- Force retry failed task
UPDATE tasks 
SET status = 'queued', attempts = 0, error = NULL
WHERE id = 'your-task-id' AND status = 'failed';
```
