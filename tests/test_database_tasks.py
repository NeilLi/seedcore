#!/usr/bin/env python3
"""
Test script for the refactored database-backed task management system.

This script tests the new Task model and database operations to ensure
the refactoring was successful.
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_task_model():
    """Test the Task model creation and serialization."""
    try:
        from seedcore.models.task import Task, TaskStatus
        
        print("🧪 Testing Task model...")
        
        # Create a test task
        task = Task(
            type="test_task",
            description="A test task for validation",
            params={"param1": "value1", "param2": 42},
            domain="test_domain",
            drift_score=0.5
        )
        
        # Test serialization
        task_dict = task.to_dict()
        
        # Verify required fields
        assert "id" in task_dict, "Task should have an ID"
        assert task_dict["type"] == "test_task", "Task type should match"
        assert task_dict["status"] == TaskStatus.CREATED.value, "Default status should be created"
        assert task_dict["params"]["param1"] == "value1", "Params should be preserved"
        
        print("✅ Task model test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Task model test failed: {e}")
        return False

async def test_database_connection():
    """Test database connectivity."""
    try:
        from seedcore.database import check_pg_health
        
        print("🧪 Testing database connection...")
        
        is_healthy = await check_pg_health()
        if not is_healthy:
            print("❌ Database health check failed")
            return False
            
        print("✅ Database connection test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Database connection test failed: {e}")
        return False

async def test_database_operations():
    """Test basic database operations with the Task model."""
    try:
        from seedcore.database import get_async_pg_session_factory
        from seedcore.models.task import Task, TaskStatus
        from sqlalchemy import select
        
        print("🧪 Testing database operations...")
        
        # Get session factory
        async_session_factory = get_async_pg_session_factory()
        
        async with async_session_factory() as session:
            # Create a test task
            test_task = Task(
                type="db_test_task",
                description="Database operation test",
                params={"test": True},
                domain="test",
                drift_score=0.0
            )
            
            # Add to database
            session.add(test_task)
            await session.commit()
            await session.refresh(test_task)
            
            # Verify it was saved
            assert test_task.id is not None, "Task should have an ID after commit"
            
            # Query the task
            result = await session.execute(select(Task).where(Task.id == test_task.id))
            retrieved_task = result.scalar_one_or_none()
            
            assert retrieved_task is not None, "Should be able to retrieve the task"
            assert retrieved_task.type == "db_test_task", "Retrieved task type should match"
            
            # Update the task
            retrieved_task.status = TaskStatus.QUEUED
            await session.commit()
            
            # Verify update
            await session.refresh(retrieved_task)
            assert retrieved_task.status == TaskStatus.QUEUED, "Status should be updated"
            
            # Clean up
            await session.delete(retrieved_task)
            await session.commit()
            
        print("✅ Database operations test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Database operations test failed: {e}")
        return False

async def test_task_router_integration():
    """Test that the task router can be imported and configured."""
    try:
        from seedcore.api.routers.tasks_router import router, _task_worker
        
        print("🧪 Testing task router integration...")
        
        # Verify router exists and has endpoints
        assert router is not None, "Router should exist"
        
        # Check that the worker function exists
        assert _task_worker is not None, "Worker function should exist"
        
        print("✅ Task router integration test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Task router integration test failed: {e}")
        return False

async def main():
    """Run all tests."""
    print("🚀 SeedCore Database Task Management Tests")
    print("=" * 60)
    
    tests = [
        ("Task Model", test_task_model),
        ("Database Connection", test_database_connection),
        ("Database Operations", test_database_operations),
        ("Task Router Integration", test_task_router_integration),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n📋 Running: {test_name}")
        print("-" * 40)
        
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The refactoring was successful.")
        return 0
    else:
        print("⚠️  Some tests failed. Please review the issues above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
