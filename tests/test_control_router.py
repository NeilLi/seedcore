#!/usr/bin/env python3
"""
Test script for the refactored database-backed control router.

This script tests the new Fact model and control router operations to ensure
the refactoring was successful.
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_fact_model():
    """Test the Fact model creation and serialization."""
    try:
        from seedcore.models.fact import Fact
        
        print("🧪 Testing Fact model...")
        
        # Create a test fact
        fact = Fact(
            text="This is a test fact for validation",
            tags=["test", "validation", "demo"],
            meta_data={"source": "test_script", "priority": "high"}
        )
        
        # Test serialization
        fact_dict = fact.to_dict()
        
        # Verify required fields
        assert "id" in fact_dict, "Fact should have an ID"
        assert fact_dict["text"] == "This is a test fact for validation", "Fact text should match"
        assert "test" in fact_dict["tags"], "Tags should be preserved"
        assert fact_dict["meta_data"]["source"] == "test_script", "Meta data should be preserved"
        
        print("✅ Fact model test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Fact model test failed: {e}")
        return False

async def test_database_operations():
    """Test basic database operations with the Fact model."""
    try:
        from seedcore.database import get_async_pg_session_factory
        from seedcore.models.fact import Fact
        from sqlalchemy import select
        
        print("🧪 Testing database operations...")
        
        # Get session factory
        async_session_factory = get_async_pg_session_factory()
        
        async with async_session_factory() as session:
            # Create a test fact
            test_fact = Fact(
                text="Database operation test fact",
                tags=["db_test", "fact"],
                meta_data={"test": True, "operation": "create"}
            )
            
            # Add to database
            session.add(test_fact)
            await session.commit()
            await session.refresh(test_fact)
            
            # Verify it was saved
            assert test_fact.id is not None, "Fact should have an ID after commit"
            
            # Query the fact
            result = await session.execute(select(Fact).where(Fact.id == test_fact.id))
            retrieved_fact = result.scalar_one_or_none()
            
            assert retrieved_fact is not None, "Should be able to retrieve the fact"
            assert retrieved_fact.text == "Database operation test fact", "Retrieved fact text should match"
            
            # Update the fact
            retrieved_fact.text = "Updated fact text"
            await session.commit()
            
            # Verify update
            await session.refresh(retrieved_fact)
            assert retrieved_fact.text == "Updated fact text", "Text should be updated"
            
            # Test search functionality
            search_result = await session.execute(
                select(Fact).where(Fact.text.ilike("%Updated%"))
            )
            search_facts = search_result.scalars().all()
            assert len(search_facts) > 0, "Search should find the updated fact"
            
            # Test tag filtering
            tag_result = await session.execute(
                select(Fact).where(Fact.tags.any("db_test"))
            )
            tag_facts = tag_result.scalars().all()
            assert len(tag_facts) > 0, "Tag filter should find facts"
            
            # Clean up
            await session.delete(retrieved_fact)
            await session.commit()
            
        print("✅ Database operations test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Database operations test failed: {e}")
        return False

async def test_control_router_integration():
    """Test that the control router can be imported and configured."""
    try:
        from seedcore.api.routers.control_router import router
        
        print("🧪 Testing control router integration...")
        
        # Verify router exists and has endpoints
        assert router is not None, "Router should exist"
        
        # Check that the router has the expected routes
        routes = [route.path for route in router.routes]
        expected_routes = [
            "/facts",
            "/facts/{fact_id}",
        ]
        
        for expected_route in expected_routes:
            assert any(expected_route in route for route in routes), f"Route {expected_route} should exist"
        
        print("✅ Control router integration test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Control router integration test failed: {e}")
        return False

async def main():
    """Run all tests."""
    print("🚀 SeedCore Control Router Tests")
    print("=" * 50)
    
    tests = [
        ("Fact Model", test_fact_model),
        ("Database Operations", test_database_operations),
        ("Control Router Integration", test_control_router_integration),
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
    print("\n" + "=" * 50)
    print("📊 Test Results Summary")
    print("=" * 50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The control router refactoring was successful.")
        return 0
    else:
        print("⚠️  Some tests failed. Please review the issues above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
