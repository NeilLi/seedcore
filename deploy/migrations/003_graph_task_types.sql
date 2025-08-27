-- Migration: Add graph task types and examples
-- This migration adds support for graph_embed and graph_rag_query task types

-- Add comments for graph task types
COMMENT ON COLUMN tasks.type IS 'Type/category of the task (e.g., graph_embed, graph_rag_query)';

-- Create a view for easier task monitoring
CREATE OR REPLACE VIEW graph_tasks AS
SELECT 
    id,
    type,
    status,
    attempts,
    locked_by,
    locked_at,
    run_after,
    params,
    result,
    error,
    created_at,
    updated_at,
    CASE 
        WHEN status = 'completed' THEN '✅'
        WHEN status = 'running' THEN '🔄'
        WHEN status = 'queued' THEN '⏳'
        WHEN status = 'failed' THEN '❌'
        ELSE '❓'
    END as status_emoji
FROM tasks 
WHERE type IN ('graph_embed', 'graph_rag_query')
ORDER BY updated_at DESC;

-- Add comments for the view
COMMENT ON VIEW graph_tasks IS 'View for monitoring graph-related tasks';
COMMENT ON COLUMN graph_tasks.status_emoji IS 'Visual status indicator';

-- Create function to insert graph embedding tasks
CREATE OR REPLACE FUNCTION create_graph_embed_task(
    start_node_ids INTEGER[],
    k_hops INTEGER DEFAULT 2,
    description TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    task_id UUID;
BEGIN
    INSERT INTO tasks (
        type, 
        status, 
        description,
        params
    ) VALUES (
        'graph_embed',
        'queued',
        COALESCE(description, format('Embed %s-hop neighborhood around nodes %s', k_hops, array_to_string(start_node_ids, ', '))),
        jsonb_build_object(
            'start_ids', start_node_ids,
            'k', k_hops
        )
    ) RETURNING id INTO task_id;
    
    RETURN task_id;
END;
$$ LANGUAGE plpgsql;

-- Create function to insert graph RAG query tasks
CREATE OR REPLACE FUNCTION create_graph_rag_task(
    start_node_ids INTEGER[],
    k_hops INTEGER DEFAULT 2,
    top_k INTEGER DEFAULT 10,
    description TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    task_id UUID;
BEGIN
    INSERT INTO tasks (
        type, 
        status, 
        description,
        params
    ) VALUES (
        'graph_rag_query',
        'queued',
        COALESCE(description, format('RAG query %s-hop neighborhood around nodes %s, top %s', k_hops, array_to_string(start_node_ids, ', '), top_k)),
        jsonb_build_object(
            'start_ids', start_node_ids,
            'k', k_hops,
            'topk', top_k
        )
    ) RETURNING id INTO task_id;
    
    RETURN task_id;
END;
$$ LANGUAGE plpgsql;

-- Add comments for the functions
COMMENT ON FUNCTION create_graph_embed_task IS 'Helper function to create graph embedding tasks';
COMMENT ON FUNCTION create_graph_rag_task IS 'Helper function to create graph RAG query tasks';

-- Create example tasks for demonstration
-- Note: These are commented out to avoid creating actual tasks during migration
-- Uncomment and modify as needed for testing

/*
-- Example 1: Embed 2-hop neighborhood around node 123
SELECT create_graph_embed_task(
    ARRAY[123], 
    2, 
    'Embed neighborhood around user node 123'
);

-- Example 2: RAG query with 2-hop neighborhood, top 15 results
SELECT create_graph_rag_task(
    ARRAY[123], 
    2, 
    15, 
    'Find similar nodes to user 123 for RAG augmentation'
);

-- Example 3: Multiple starting nodes
SELECT create_graph_embed_task(
    ARRAY[123, 456, 789], 
    3, 
    'Embed extended neighborhood around multiple user nodes'
);
*/
