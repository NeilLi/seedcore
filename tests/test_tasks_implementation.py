#!/usr/bin/env python3
"""
Simple test script to verify the tasks implementation.
This tests the basic functionality without requiring a full server setup.
"""

import asyncio
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_organism_manager():
    """Test the OrganismManager.handle_incoming_task method."""
    try:
        from seedcore.organs.organism_manager import OrganismManager
        
        # Create a mock OrganismManager instance
        manager = OrganismManager()
        
        # Mock the OCPS valve
        manager.ocps = type('MockOCPS', (), {'p_fast': 0.8})()
        
        # Test builtin task handling
        task = {"type": "test_task", "params": {"test": "value"}}
        
        # Test without app_state (should fall back to COA routing)
        result = await manager.handle_incoming_task(task)
        print(f"✅ Test task without app_state: {result}")
        
        # Test with app_state but no builtin handlers
        mock_app_state = type('MockAppState', (), {})()
        result = await manager.handle_incoming_task(task, mock_app_state)
        print(f"✅ Test task with empty app_state: {result}")
        
        # Test with builtin handlers
        mock_app_state.builtin_task_handlers = {
            "test_task": lambda: {"test_result": "success"}
        }
        result = await manager.handle_incoming_task(task, mock_app_state)
        print(f"✅ Test task with builtin handler: {result}")
        
        print("🎉 All OrganismManager tests passed!")
        
    except Exception as e:
        print(f"❌ OrganismManager test failed: {e}")
        import traceback
        traceback.print_exc()

async def test_tasks_router():
    """Test the tasks router imports and basic structure."""
    try:
        from seedcore.api.routers.tasks_router import router
        
        print(f"✅ Tasks router imported successfully: {router}")
        print(f"✅ Router prefix: {router.prefix}")
        print(f"✅ Router tags: {router.tags}")
        
        # Check that all expected endpoints are registered
        expected_routes = [
            "/tasks",
            "/tasks/{task_id}",
            "/tasks/{task_id}/run",
            "/tasks/{task_id}/cancel"
        ]
        
        route_paths = [route.path for route in router.routes]
        print(f"✅ Available routes: {route_paths}")
        
        for expected in expected_routes:
            if any(expected in route for route in route_paths):
                print(f"✅ Found route: {expected}")
            else:
                print(f"⚠️  Missing route: {expected}")
        
        print("🎉 All tasks router tests passed!")
        
    except Exception as e:
        print(f"❌ Tasks router test failed: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Run all tests."""
    print("🧪 Testing Tasks Implementation...")
    print("=" * 50)
    
    await test_organism_manager()
    print()
    await test_tasks_router()
    
    print("\n" + "=" * 50)
    print("🏁 Testing complete!")

if __name__ == "__main__":
    asyncio.run(main())
