#!/usr/bin/env python3
"""
Simple test script to verify DGL integration works.
Run with: python tests/test_dgl_integration.py
"""

import sys
import os
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

def test_dgl_imports():
    """Test that DGL and related modules can be imported."""
    try:
        import dgl
        import torch
        print("✅ DGL and PyTorch imports successful")
        print(f"   DGL version: {dgl.__version__}")
        print(f"   PyTorch version: {torch.__version__}")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_graph_loader():
    """Test that GraphLoader can be imported and instantiated."""
    try:
        from seedcore.graph.loader import GraphLoader
        print("✅ GraphLoader import successful")
        
        # Test instantiation (without connecting to Neo4j)
        loader = GraphLoader(uri="bolt://localhost:7687", user="test", password="test")
        print("✅ GraphLoader instantiation successful")
        return True
    except Exception as e:
        print(f"❌ GraphLoader test failed: {e}")
        return False

def test_sage_model():
    """Test that SAGE model can be imported and instantiated."""
    try:
        from seedcore.graph.models import SAGE
        print("✅ SAGE model import successful")
        
        # Test instantiation
        model = SAGE(in_feats=10, h_feats=128, layers=2)
        print("✅ SAGE model instantiation successful")
        print(f"   Model parameters: {sum(p.numel() for p in model.parameters())}")
        return True
    except Exception as e:
        print(f"❌ SAGE model test failed: {e}")
        return False

def test_embeddings_module():
    """Test that embeddings module can be imported."""
    try:
        from seedcore.graph.embeddings import compute_graph_embeddings, upsert_embeddings
        print("✅ Embeddings module import successful")
        return True
    except Exception as e:
        print(f"❌ Embeddings module test failed: {e}")
        return False

def test_graph_dispatcher():
    """Test that GraphDispatcher can be imported."""
    try:
        from seedcore.agents.graph_dispatcher import GraphDispatcher
        print("✅ GraphDispatcher import successful")
        return True
    except Exception as e:
        print(f"❌ GraphDispatcher test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🧪 Testing DGL integration...")
    print("=" * 50)
    
    tests = [
        test_dgl_imports,
        test_graph_loader,
        test_sage_model,
        test_embeddings_module,
        test_graph_dispatcher,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
        print()
    
    print("=" * 50)
    print(f"📊 Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed! DGL integration is working correctly.")
        return 0
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
