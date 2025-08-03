#!/usr/bin/env python3
"""
Basic Ray connectivity test to verify the cluster is working properly.
"""

import sys
import os
import ray
import time

def test_ray_basic():
    """Test basic Ray operations."""
    print("🧪 Testing Basic Ray Operations")
    print("=" * 40)
    
    try:
        # Check if Ray is initialized
        if not ray.is_initialized():
            print("❌ Ray is not initialized")
            return False
        
        print("✅ Ray is initialized")
        
        # Test basic Ray operation
        @ray.remote
        def simple_task():
            return "Hello from Ray!"
        
        print("🔧 Testing remote function...")
        result = ray.get(simple_task.remote())
        print(f"✅ Remote function result: {result}")
        
        # Test Ray Data
        print("🔧 Testing Ray Data...")
        dataset = ray.data.range(100)
        count = dataset.count()
        print(f"✅ Ray Data count: {count}")
        
        # Test Ray cluster info
        print("🔧 Testing cluster info...")
        nodes = ray.nodes()
        print(f"✅ Ray nodes: {len(nodes)}")
        for node in nodes:
            print(f"   - {node.get('NodeManagerAddress', 'unknown')}: {node.get('Alive', False)}")
        
        print("✅ All basic Ray operations passed!")
        return True
        
    except Exception as e:
        print(f"❌ Basic Ray test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ray_data_operations():
    """Test Ray Data operations specifically."""
    print("\n🔧 Testing Ray Data Operations")
    print("=" * 40)
    
    try:
        # Create a simple dataset
        import pandas as pd
        import numpy as np
        
        # Create sample data
        data = {
            'feature_1': np.random.randn(1000),
            'feature_2': np.random.randn(1000),
            'target': np.random.randint(0, 2, 1000)
        }
        df = pd.DataFrame(data)
        
        print("📊 Creating Ray Dataset from pandas...")
        dataset = ray.data.from_pandas(df)
        print(f"✅ Dataset created with {dataset.count()} rows")
        
        # Test basic operations
        print("🔧 Testing dataset operations...")
        schema = dataset.schema()
        print(f"✅ Dataset schema: {schema}")
        
        # Test sampling
        sample = dataset.take(5)
        print(f"✅ Sample data: {len(sample)} rows")
        
        print("✅ All Ray Data operations passed!")
        return True
        
    except Exception as e:
        print(f"❌ Ray Data test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function."""
    print("🚀 Starting Basic Ray Connectivity Tests")
    print("=" * 50)
    
    # Set up environment
    sys.path.insert(0, '/app')
    sys.path.insert(0, '/app/src')
    
    # Check environment
    print("🔍 Environment Check:")
    print(f"   PYTHONPATH: {os.getenv('PYTHONPATH', 'Not set')}")
    print(f"   RAY_ADDRESS: {os.getenv('RAY_ADDRESS', 'Not set')}")
    print(f"   Working Directory: {os.getcwd()}")
    
    # Run tests
    basic_ok = test_ray_basic()
    data_ok = test_ray_data_operations()
    
    print("\n📊 Test Summary")
    print("=" * 20)
    print(f"Basic Ray Operations: {'✅ PASSED' if basic_ok else '❌ FAILED'}")
    print(f"Ray Data Operations: {'✅ PASSED' if data_ok else '❌ FAILED'}")
    
    if basic_ok and data_ok:
        print("\n🎉 All basic Ray tests passed!")
        return True
    else:
        print("\n⚠️ Some Ray tests failed.")
        return False

if __name__ == "__main__":
    main() 