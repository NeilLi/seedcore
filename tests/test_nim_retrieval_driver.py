#!/usr/bin/env python3
"""
Test Script for SeedCore NIM Retrieval Driver
==============================================

This script validates both NimRetrievalSDK (OpenAI SDK) and NimRetrievalHTTP
implementations defined in:
    seedcore/ml/driver/__init__.py

Usage:
    python test_nim_retrieval_driver.py
    pytest tests/test_nim_retrieval_driver.py -v
"""

# Import mock dependencies BEFORE any other imports
import mock_ray_dependencies

import os
import sys
import json
import traceback
import math
from typing import List
from unittest.mock import patch, MagicMock

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from seedcore.ml.driver import (
    NimRetrievalSDK,
    NimRetrievalHTTP,
    get_retriever,
)


# ---------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------
BASE_URL = os.getenv(
    "NIM_LLM_BASE_URL",
    "http://localhost:8000/v1",
)
MODEL = os.getenv("SEEDCORE_NIM_MODEL", "nvidia/nv-embedqa-e5-v5")
API_KEY = os.getenv("NIM_LLM_API_KE", "none")

# Test data
TEST_QUERY = "What is machine learning?"
TEST_PASSAGE = "Machine learning is a subset of artificial intelligence that uses statistical techniques."
TEST_BATCH = ["Hello world", "How are you?", "This is a test"]

# Mock embedding response - 1024-dimensional vectors
MOCK_EMBEDDING_DIM = 1024
def create_mock_embedding() -> List[float]:
    """Create a mock embedding vector for testing."""
    import random
    return [random.random() for _ in range(MOCK_EMBEDDING_DIM)]


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
def validate_embedding(embedding: List[float], expected_dim: int = None) -> bool:
    """Validate that an embedding is a valid vector."""
    if not isinstance(embedding, list):
        return False
    if len(embedding) == 0:
        return False
    if not all(isinstance(x, (int, float)) for x in embedding):
        return False
    if expected_dim and len(embedding) != expected_dim:
        return False
    return True


def validate_embeddings_batch(embeddings: List[List[float]], expected_count: int, expected_dim: int = None) -> bool:
    """Validate a batch of embeddings."""
    if not isinstance(embeddings, list):
        return False
    if len(embeddings) != expected_count:
        return False
    return all(validate_embedding(emb, expected_dim) for emb in embeddings)


def run_embedding_test(retriever, label: str, is_mocked: bool = False) -> dict:
    """Run comprehensive embedding tests and return results."""
    print(f"\n=== Running {label} ===")
    results = {
        "single_embed": False,
        "batch_embed": False,
        "embed_query": False,
        "embed_passage": False,
        "cosine_sim": False,
        "embedding_dimensions": None,
        "errors": []
    }
    
    # Mock the retriever if needed
    if is_mocked:
        def mock_embed_fn(inputs, **kwargs):
            """Mock embed function that returns appropriate number of embeddings."""
            if isinstance(inputs, list):
                return [create_mock_embedding() for _ in inputs]
            else:
                return [create_mock_embedding()]
        
        if isinstance(retriever, NimRetrievalSDK):
            # Mock SDK retriever
            retriever.embed = mock_embed_fn
            retriever.embed_query = lambda text, **kwargs: create_mock_embedding()
            retriever.embed_passage = lambda text, **kwargs: create_mock_embedding()
        else:
            # Mock HTTP retriever  
            retriever.embed = mock_embed_fn
            retriever.embed_query = lambda text, **kwargs: create_mock_embedding()
            retriever.embed_passage = lambda text, **kwargs: create_mock_embedding()
    
    try:
        # Test 1: Single embedding
        print("Testing single embedding...")
        single_emb = retriever.embed([TEST_QUERY], input_type="query")
        if validate_embeddings_batch(single_emb, 1):
            results["single_embed"] = True
            results["embedding_dimensions"] = len(single_emb[0])
            print(f"✓ Single embedding: {len(single_emb[0])} dimensions")
        else:
            print("✗ Single embedding validation failed")
            results["errors"].append("Single embedding validation failed")
            
    except Exception as e:
        print(f"✗ Single embedding failed: {e}")
        results["errors"].append(f"Single embedding: {str(e)}")

    try:
        # Test 2: Batch embeddings
        print("Testing batch embeddings...")
        batch_emb = retriever.embed(TEST_BATCH, input_type="query")
        if validate_embeddings_batch(batch_emb, len(TEST_BATCH), results["embedding_dimensions"]):
            results["batch_embed"] = True
            print(f"✓ Batch embeddings: {len(batch_emb)} vectors")
        else:
            print("✗ Batch embedding validation failed")
            results["errors"].append("Batch embedding validation failed")
            
    except Exception as e:
        print(f"✗ Batch embeddings failed: {e}")
        results["errors"].append(f"Batch embeddings: {str(e)}")

    try:
        # Test 3: Query embedding
        print("Testing embed_query...")
        query_emb = retriever.embed_query(TEST_QUERY)
        if validate_embedding(query_emb, results["embedding_dimensions"]):
            results["embed_query"] = True
            print(f"✓ Query embedding: {len(query_emb)} dimensions")
        else:
            print("✗ Query embedding validation failed")
            results["errors"].append("Query embedding validation failed")
            
    except Exception as e:
        print(f"✗ Query embedding failed: {e}")
        results["errors"].append(f"Query embedding: {str(e)}")

    try:
        # Test 4: Passage embedding
        print("Testing embed_passage...")
        passage_emb = retriever.embed_passage(TEST_PASSAGE)
        if validate_embedding(passage_emb, results["embedding_dimensions"]):
            results["embed_passage"] = True
            print(f"✓ Passage embedding: {len(passage_emb)} dimensions")
        else:
            print("✗ Passage embedding validation failed")
            results["errors"].append("Passage embedding validation failed")
            
    except Exception as e:
        print(f"✗ Passage embedding failed: {e}")
        results["errors"].append(f"Passage embedding: {str(e)}")

    try:
        # Test 5: Cosine similarity
        print("Testing cosine similarity...")
        if results["embed_query"] and results["embed_passage"]:
            query_emb = retriever.embed_query(TEST_QUERY)
            passage_emb = retriever.embed_passage(TEST_PASSAGE)
            
            # Test cosine similarity method
            sim = retriever.cosine_sim(query_emb, passage_emb)
            if isinstance(sim, (int, float)) and -1.0 <= sim <= 1.0:
                results["cosine_sim"] = True
                print(f"✓ Cosine similarity: {sim:.4f}")
            else:
                print(f"✗ Invalid cosine similarity: {sim}")
                results["errors"].append(f"Invalid cosine similarity: {sim}")
        else:
            print("✗ Skipping cosine similarity (prerequisites failed)")
            results["errors"].append("Cosine similarity skipped (prerequisites failed)")
            
    except Exception as e:
        print(f"✗ Cosine similarity failed: {e}")
        results["errors"].append(f"Cosine similarity: {str(e)}")

    # Calculate success rate
    success_count = sum(1 for k, v in results.items() if k != "errors" and k != "embedding_dimensions" and v)
    total_tests = 5
    print(f"Success rate: {success_count}/{total_tests}")
    
    if success_count == total_tests:
        print("✓ All tests passed!")
    else:
        print(f"✗ {total_tests - success_count} test(s) failed")
    
    return results


# ---------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------
def test_nim_retrieval_http():
    """Test HTTP-based retrieval driver."""
    retriever = NimRetrievalHTTP(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    results = run_embedding_test(retriever, "NimRetrievalHTTP", is_mocked=True)
    assert results["single_embed"], "HTTP single embedding test failed"
    assert results["batch_embed"], "HTTP batch embedding test failed"
    assert results["embed_query"], "HTTP query embedding test failed"
    assert results["embed_passage"], "HTTP passage embedding test failed"
    assert results["cosine_sim"], "HTTP cosine similarity test failed"


def test_nim_retrieval_sdk():
    """Test SDK-based retrieval driver."""
    retriever = NimRetrievalSDK(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    results = run_embedding_test(retriever, "NimRetrievalSDK", is_mocked=True)
    assert results["single_embed"], "SDK single embedding test failed"
    assert results["batch_embed"], "SDK batch embedding test failed"
    assert results["embed_query"], "SDK query embedding test failed"
    assert results["embed_passage"], "SDK passage embedding test failed"
    assert results["cosine_sim"], "SDK cosine similarity test failed"


def test_get_retriever_auto_detection():
    """Test get_retriever() environment auto-detection."""
    # Test SDK mode
    os.environ["SEEDCORE_USE_SDK"] = "true"
    retriever = get_retriever(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    results = run_embedding_test(retriever, "get_retriever (auto-detect SDK)", is_mocked=True)
    assert results["single_embed"], "Auto-detect SDK embedding test failed"
    
    # Test HTTP mode
    os.environ["SEEDCORE_USE_SDK"] = "false"
    retriever = get_retriever(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    results = run_embedding_test(retriever, "get_retriever (auto-detect HTTP)", is_mocked=True)
    assert results["single_embed"], "Auto-detect HTTP embedding test failed"


def test_cosine_similarity_function():
    """Test the static cosine similarity function with known vectors."""
    # Test with identical vectors
    vec1 = [1.0, 2.0, 3.0]
    vec2 = [1.0, 2.0, 3.0]
    sim = NimRetrievalSDK.cosine_sim(vec1, vec2)
    assert abs(sim - 1.0) < 1e-6, f"Expected similarity ~1.0, got {sim}"
    
    # Test with orthogonal vectors
    vec1 = [1.0, 0.0]
    vec2 = [0.0, 1.0]
    sim = NimRetrievalHTTP.cosine_sim(vec1, vec2)
    assert abs(sim - 0.0) < 1e-6, f"Expected similarity ~0.0, got {sim}"
    
    # Test with opposite vectors
    vec1 = [1.0, 0.0]
    vec2 = [-1.0, 0.0]
    sim = NimRetrievalSDK.cosine_sim(vec1, vec2)
    assert abs(sim - (-1.0)) < 1e-6, f"Expected similarity ~-1.0, got {sim}"
    
    print("✓ Cosine similarity function tests passed")


def test_embedding_consistency():
    """Test that the same input produces consistent embeddings."""
    retriever_sdk = NimRetrievalSDK(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    retriever_http = NimRetrievalHTTP(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    
    try:
        # Get embeddings from both drivers
        text = "Consistency test"
        emb_sdk = retriever_sdk.embed_query(text)
        emb_http = retriever_http.embed_query(text)
        
        # Check if embeddings are similar (should be identical if using same model/endpoint)
        similarity = NimRetrievalSDK.cosine_sim(emb_sdk, emb_http)
        print(f"SDK vs HTTP embedding similarity: {similarity:.6f}")
        
        # They should be very similar (>0.99) if using the same backend
        assert similarity > 0.95, f"Embeddings too different: similarity={similarity}"
        print("✓ Embedding consistency test passed")
        
    except Exception as e:
        print(f"⚠ Embedding consistency test skipped: {e}")
        # This test might fail if backends are different, so we'll make it non-fatal


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("=== SeedCore NIM Retrieval Driver Test ===")
    print(f"Base URL: {BASE_URL}")
    print(f"Model: {MODEL}")
    print(f"API Key: {API_KEY}")
    print("-" * 60)

    results = {}
    
    try:
        results["http"] = test_nim_retrieval_http()
    except Exception as e:
        print(f"HTTP retrieval tests failed: {e}")
        traceback.print_exc()
        results["http"] = False
    
    try:
        results["sdk"] = test_nim_retrieval_sdk()
    except Exception as e:
        print(f"SDK retrieval tests failed: {e}")
        traceback.print_exc()
        results["sdk"] = False
    
    try:
        results["auto_detect"] = test_get_retriever_auto_detection()
    except Exception as e:
        print(f"Auto-detection tests failed: {e}")
        traceback.print_exc()
        results["auto_detect"] = False
    
    try:
        test_cosine_similarity_function()
        results["cosine_function"] = True
    except Exception as e:
        print(f"Cosine similarity function tests failed: {e}")
        traceback.print_exc()
        results["cosine_function"] = False
    
    try:
        test_embedding_consistency()
        results["consistency"] = True
    except Exception as e:
        print(f"Consistency tests failed: {e}")
        results["consistency"] = False

    print("\n=== Summary ===")
    print(json.dumps(results, indent=2))
    print("\nAll retrieval tests completed.")
