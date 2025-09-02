"""
Graph processing module for SeedCore.

This module provides:
- Neo4j to DGL graph loading
- Graph neural network models (GraphSAGE)
- Ray-based graph embedding computation
- pgvector integration for graph embeddings
"""

from .loader import GraphLoader
from .models import SAGE
from .embeddings import GraphEmbedder, upsert_embeddings

__all__ = [
    "GraphLoader",
    "SAGE", 
    "GraphEmbedder",
    "upsert_embeddings"
]
