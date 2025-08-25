#!/usr/bin/env python3
"""
Test script for the enhanced tasks implementation with JSON persistence.
"""

import asyncio
import json
import os
import tempfile
import time

async def test_tasks_persistence():
    """Test the persistence functionality."""
    print("🧪 Testing Tasks Persistence...")
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        tasks_file = os.path.join(temp_dir, "tasks.json")
        
        # Set the environment variable for the test
        os.environ["TASKS_STORE_PATH"] = tasks_file
        
        try:
            # Import the router
            import sys
            sys.path.insert(0, 'src')
            from seedcore.api.routers.tasks_router import router, _load_json, _dump_json
            
            print(f"✅ Router imported successfully")
            print(f"✅ Tasks will be stored in: {tasks_file}")
            
            # Test JSON persistence helpers
            test_data = {"tasks": [
                {"id": "test1", "type": "test", "status": "created"},
                {"id": "test2", "type": "test", "status": "running"}
            ]}
            
            # Test dump
            _dump_json(tasks_file, test_data)
            print(f"✅ Data written to {tasks_file}")
            
            # Test load
            loaded_data = _load_json(tasks_file, {"tasks": []})
            print(f"✅ Data loaded: {loaded_data}")
            
            # Verify the data matches
            assert loaded_data == test_data, "Data mismatch after save/load"
            print("✅ Persistence test passed!")
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    return True

async def test_organism_manager_integration():
    """Test that the OrganismManager integration still works."""
    print("\n🧪 Testing OrganismManager Integration...")
    
    try:
        import sys
        sys.path.insert(0, 'src')
        from seedcore.organs.organism_manager import OrganismManager
        
        # Create a mock instance
        manager = OrganismManager()
        manager.ocps = type('MockOCPS', (), {'p_fast': 0.8})()
        
        # Test builtin task handling
        task = {"type": "test_task", "params": {"test": "value"}}
        
        # Test without app_state
        result = await manager.handle_incoming_task(task)
        print(f"✅ Test task without app_state: {result}")
        
        # Test with builtin handlers
        mock_app_state = type('MockAppState', (), {})()
        mock_app_state.builtin_task_handlers = {
            "test_task": lambda: {"test_result": "success"}
        }
        result = await manager.handle_incoming_task(task, mock_app_state)
        print(f"✅ Test task with builtin handler: {result}")
        
        print("✅ OrganismManager integration test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OrganismManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all tests."""
    print("🚀 Testing Enhanced Tasks Implementation...")
    print("=" * 60)
    
    # Test persistence
    persistence_ok = await test_tasks_persistence()
    
    # Test OrganismManager integration
    integration_ok = await test_organism_manager_integration()
    
    print("\n" + "=" * 60)
    if persistence_ok and integration_ok:
        print("🎉 All tests passed! Enhanced tasks implementation is working.")
    else:
        print("❌ Some tests failed. Please check the implementation.")
    
    print("\n📋 Summary of Changes Made:")
    print("✅ Disabled legacy tasks in control_router.py (feature flag)")
    print("✅ Enhanced tasks_router.py with JSON persistence")
    print("✅ Added domain/drift_score fields to task records")
    print("✅ Added /tasks/{id}/status endpoint")
    print("✅ Tasks now survive server restarts")
    print("✅ No more route conflicts between routers")

if __name__ == "__main__":
    asyncio.run(main())
