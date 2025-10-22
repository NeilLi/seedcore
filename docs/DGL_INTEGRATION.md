# DGL Integration for SeedCore

This document describes the Deep Graph Library (DGL) integration in SeedCore, which provides graph neural network capabilities for processing knowledge graphs stored in Neo4j.

## Overview

The DGL integration consists of several components:

1. **GraphLoader**: Pulls k-hop neighborhoods from Neo4j and converts them to DGL graphs
2. **SAGE Model**: GraphSAGE implementation for node embedding generation
3. **Embedding Pipeline**: Ray-based computation and pgvector storage
4. **GraphDispatcher**: Task dispatcher for graph-related operations

## Architecture

```
Neo4j → GraphLoader → DGL Graph → SAGE Model → Embeddings → pgvector
   ↓           ↓           ↓          ↓           ↓          ↓
Cypher    k-hop      Homogeneous  128-dim    Ray Tasks   Vector DB
Query   Neighborhood   Graph      Features   Parallel    Storage
```

## Components

### 1. GraphLoader (`src/seedcore/graph/loader.py`)

The `GraphLoader` class provides a bridge between Neo4j and DGL:

- **k-hop neighborhood extraction**: Pulls nodes within k hops of starting nodes
- **Homogeneous graph construction**: Creates DGL graphs with consistent node/edge types
- **Feature generation**: Creates deterministic node features from graph structure
- **ID mapping**: Maintains mapping between Neo4j IDs and graph indices

**Usage:**
```python
from seedcore.graph.loader import GraphLoader

loader = GraphLoader()
g, idx_map, X = loader.load_k_hop(
    start_ids=[123, 456],  # Neo4j node IDs
    k=2,                   # 2-hop neighborhood
    limit_nodes=5000,      # Max nodes to load
    limit_rels=20000       # Max relationships to load
)
loader.close()
```

### 2. SAGE Model (`src/seedcore/graph/gnn_models.py`)

A GraphSAGE implementation for inductive node representation learning:

- **Multi-layer architecture**: Configurable number of layers
- **Mean aggregation**: Uses mean pooling for neighbor aggregation
- **L2 normalization**: Outputs unit vectors for cosine similarity
- **ReLU activation**: Non-linear transformations between layers

**Usage:**
```python
from seedcore.graph.gnn_models import SAGE

model = SAGE(in_feats=10, h_feats=128, layers=2)
model.eval()
with torch.no_grad():
    embeddings = model(g, X)  # [N, 128] normalized vectors
```

### 3. Embedding Pipeline (`src/seedcore/graph/embeddings.py`)

Ray-based parallel processing for graph embeddings:

- **`compute_graph_embeddings`**: Ray task that loads graphs and computes embeddings
- **`upsert_embeddings`**: Ray task that stores embeddings in pgvector
- **Batch processing**: Handles multiple nodes efficiently
- **Error handling**: Graceful fallbacks and retries

### 4. GraphDispatcher (`src/seedcore/dispatcher/graph_dispatcher.py`)

Task dispatcher for graph operations:

- **`graph_embed`**: Compute and store embeddings for k-hop neighborhoods
- **`graph_rag_query`**: Expand neighborhoods and find similar nodes via vector search
- **Task management**: Integrates with the existing task queue system
- **Health monitoring**: Built-in health checks and monitoring

## Database Schema

The `graph_embeddings` table stores computed node embeddings:

```sql
CREATE TABLE graph_embeddings (
    node_id BIGINT PRIMARY KEY,      -- Neo4j node ID
    label TEXT NULL,                 -- Node label(s)
    props JSONB NULL,                -- Node properties
    emb VECTOR(128) NOT NULL,        -- 128-dimensional embedding
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Indexes:**
- Primary key on `node_id`
- IVFFlat index on `emb` for approximate nearest neighbor search

## Configuration

### Environment Variables

```bash
# Neo4j connection
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# PostgreSQL connection
SEEDCORE_PG_DSN=postgresql://postgres:postgres@postgresql:5432/seedcore

# Ray configuration
RAY_NAMESPACE=seedcore-dev
SEEDCORE_GRAPH_DISPATCHERS=1
```

### Dependencies

The following packages are required:

```txt
dgl>=1.1.0          # Deep Graph Library
dglgo>=0.1.0        # DGL Go utilities
torch>=2.0.0        # PyTorch backend
neo4j-driver        # Neo4j Python driver
pgvector            # PostgreSQL vector extension
```

## Usage Examples

### 1. Compute Node Embeddings

```python
import ray
from seedcore.dispatcher import GraphDispatcher

# Get GraphDispatcher reference
dispatcher = ray.get_actor("seedcore_graph_dispatcher_0")

# Compute embeddings for specific nodes
result = ray.get(dispatcher._process.remote({
    "id": "task_123",
    "type": "graph_embed",
    "params": json.dumps({
        "start_ids": [123, 456, 789],
        "k": 2
    })
}))
```

### 2. Graph RAG Query

```python
# Query similar nodes for RAG augmentation
result = ray.get(dispatcher._process.remote({
    "id": "task_124",
    "type": "graph_rag_query",
    "params": json.dumps({
        "start_ids": [123],
        "k": 2,
        "topk": 10
    })
}))
```

### 3. Direct API Usage

```python
from seedcore.graph.embeddings import compute_graph_embeddings, upsert_embeddings

# Compute embeddings
emb_map = ray.get(compute_graph_embeddings.remote([123, 456], k=2))

# Store in database
count = ray.get(upsert_embeddings.remote(emb_map))
print(f"Stored {count} embeddings")
```

## Performance Considerations

### Memory Usage

- **Graph size limits**: Default 5000 nodes, 20000 relationships
- **Batch processing**: Ray tasks handle memory efficiently
- **Feature compression**: 10-dimensional features (2 degrees + 8 label hash)

### Scalability

- **Parallel processing**: Ray tasks distribute work across cluster
- **Vector search**: pgvector provides efficient similarity search
- **Caching**: Embeddings are stored persistently for reuse

### Optimization Tips

1. **Adjust k-hop depth**: Balance coverage vs. computation cost
2. **Limit graph size**: Use `limit_nodes` and `limit_rels` parameters
3. **Batch operations**: Process multiple neighborhoods together
4. **Index tuning**: Adjust pgvector index parameters for your data size

## Troubleshooting

### Common Issues

1. **Neo4j connection failures**: Check URI, credentials, and network connectivity
2. **Memory errors**: Reduce `limit_nodes` and `limit_rels` parameters
3. **pgvector errors**: Ensure PostgreSQL has the vector extension installed
4. **Ray task failures**: Check Ray cluster health and resource allocation

### Debugging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check task status:

```python
# Query task status from database
SELECT * FROM tasks WHERE type IN ('graph_embed', 'graph_rag_query');
```

### Health Checks

Monitor GraphDispatcher health:

```python
dispatcher = ray.get_actor("seedcore_graph_dispatcher_0")
status = ray.get(dispatcher.ping.remote())
print(f"Status: {status}")  # Should return "pong"
```

## Future Enhancements

### Planned Features

1. **Heterogeneous graphs**: Support for multiple node/edge types
2. **Advanced GNN models**: GAT, Graph Transformer, etc.
3. **Dynamic graphs**: Temporal graph processing
4. **Graph visualization**: Interactive graph exploration tools

### Extensibility

The modular design allows easy extension:

- Add new GNN models in `gnn_models.py`
- Implement custom feature extractors in `loader.py`
- Create specialized dispatchers for different graph operations
- Integrate with other vector databases (Pinecone, Weaviate, etc.)

## Contributing

When adding new features:

1. Follow the existing code structure and patterns
2. Add comprehensive docstrings and type hints
3. Include unit tests for new functionality
4. Update this documentation
5. Consider performance implications for large graphs

## References

- [DGL Documentation](https://docs.dgl.ai/)
- [GraphSAGE Paper](https://arxiv.org/abs/1706.02216)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [Ray Documentation](https://docs.ray.io/)
