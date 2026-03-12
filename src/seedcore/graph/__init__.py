"""
Graph processing module for SeedCore.

This module provides:
- Neo4j to DGL graph loading
- Graph neural network models (GraphSAGE)
- Ray-based graph embedding computation
- pgvector integration for graph embeddings
"""

# Import TaskMetadataRepository first as it's needed by coordinator
from .task_metadata_repository import TaskMetadataRepository
from .agent_repository import AgentGraphRepository

_OPTIONAL_GRAPH_IMPORT_ERROR: Exception | None = None

# Make DGL-dependent imports optional to avoid import errors during testing
try:
    # Import DGL-dependent modules
    from .loader import GraphLoader
    from .gnn_models import SAGE
    from .embeddings import GraphEmbedder, NimRetrievalEmbedder, upsert_embeddings
    
    __all__ = [
        "TaskMetadataRepository",
        "AgentGraphRepository",
        "GraphLoader",
        "SAGE", 
        "GraphEmbedder",
        "NimRetrievalEmbedder",
        "upsert_embeddings"
    ]
except (ImportError, FileNotFoundError) as e:
    _OPTIONAL_GRAPH_IMPORT_ERROR = e
    # If DGL is not available, only export GraphTaskRepository and AgentGraphRepository
    __all__ = ["TaskMetadataRepository", "AgentGraphRepository"]


def __getattr__(name: str):
    if name in {"GraphLoader", "SAGE", "GraphEmbedder", "NimRetrievalEmbedder", "upsert_embeddings"}:
        raise ImportError(
            f"{name} requires optional graph dependencies that are not available: "
            f"{_OPTIONAL_GRAPH_IMPORT_ERROR}"
        ) from _OPTIONAL_GRAPH_IMPORT_ERROR
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
