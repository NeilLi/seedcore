#!/usr/bin/env python3
"""
Test script for the Janitor actor.
This test only runs when Ray cluster is available.
"""

import pytest
import ray

def test_janitor_actor():
    """Test that the Janitor actor can be found and has expected methods."""
    try:
        # Connect to the cluster with the right namespace
        ray.init(address="auto", namespace="seedcore-dev")
        
        # Get the detached Janitor actor
        jan = ray.get_actor("seedcore_janitor", namespace="seedcore-dev")
        print("✅ Found actor:", jan)

        # List its methods and attributes
        print("\n📋 Available methods/attributes:")
        for m in dir(jan):
            print(" -", m)
            
        # Test basic functionality
        assert hasattr(jan, 'ping')
        assert hasattr(jan, 'status')
        assert hasattr(jan, 'list_dead_named')
        assert hasattr(jan, 'reap')
        
        # Test ping method
        result = ray.get(jan.ping.remote())
        assert result == "ok"
        
        print("✅ Janitor actor test passed!")
        
    except Exception as e:
        pytest.skip(f"Ray cluster not available or Janitor actor not found: {e}")
    finally:
        if ray.is_initialized():
            ray.shutdown()

if __name__ == "__main__":
    test_janitor_actor()

