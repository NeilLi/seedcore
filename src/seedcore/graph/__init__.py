"""
Graph processing module for SeedCore.

This module provides:
- Neo4j to DGL graph loading
- Graph neural network models (GraphSAGE)
- Ray-based graph embedding computation
- pgvector integration for graph embeddings
"""

# Import GraphTaskRepository first as it's needed by coordinator
from .graph_task_repository import GraphTaskRepository

# Make DGL-dependent imports optional to avoid import errors during testing
try:
    # Import DGL-dependent modules
    from .loader import GraphLoader
    from .models import SAGE
    from .embeddings import GraphEmbedder, upsert_embeddings
    
    __all__ = [
        "GraphTaskRepository",
        "GraphLoader",
        "SAGE", 
        "GraphEmbedder",
        "upsert_embeddings"
    ]
except (ImportError, FileNotFoundError) as e:
    # If DGL is not available, only export GraphTaskRepository
    __all__ = ["GraphTaskRepository"]
