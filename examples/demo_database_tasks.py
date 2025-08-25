#!/usr/bin/env python3
"""
Demo script for the database-backed task management system.

This script demonstrates how to create, manage, and monitor tasks
using the new database-backed system.
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

async def demo_task_lifecycle():
    """Demonstrate the complete task lifecycle."""
    try:
        from seedcore.database import get_async_pg_session_factory
        from seedcore.models.task import Task, TaskStatus
        from sqlalchemy import select
        
        print("🚀 Database Task Management Demo")
        print("=" * 50)
        
        # Get session factory
        async_session_factory = get_async_pg_session_factory()
        
        async with async_session_factory() as session:
            print("\n📝 Creating a new task...")
            
            # Create a demo task
            demo_task = Task(
                type="demo_analysis",
                description="Demonstration task for the new system",
                params={
                    "input_data": "sample_dataset.csv",
                    "analysis_type": "classification",
                    "model": "random_forest"
                },
                domain="machine_learning",
                drift_score=0.25
            )
            
            session.add(demo_task)
            await session.commit()
            await session.refresh(demo_task)
            
            print(f"✅ Task created with ID: {demo_task.id}")
            print(f"   Status: {demo_task.status.value}")
            print(f"   Type: {demo_task.type}")
            print(f"   Domain: {demo_task.domain}")
            
            # Simulate task execution
            print("\n🔄 Simulating task execution...")
            
            # Update status to running
            demo_task.status = TaskStatus.RUNNING
            await session.commit()
            print(f"   Status updated to: {demo_task.status.value}")
            
            # Simulate some processing time
            await asyncio.sleep(1)
            
            # Complete the task
            demo_task.status = TaskStatus.COMPLETED
            demo_task.result = {
                "accuracy": 0.94,
                "training_time": "2.3s",
                "model_size": "1.2MB",
                "success": True
            }
            await session.commit()
            
            print(f"   Task completed successfully!")
            print(f"   Final status: {demo_task.status.value}")
            print(f"   Result accuracy: {demo_task.result['accuracy']}")
            
            # Query all tasks
            print("\n📊 Querying all tasks...")
            result = await session.execute(select(Task).order_by(Task.created_at.desc()))
            all_tasks = result.scalars().all()
            
            print(f"   Total tasks in database: {len(all_tasks)}")
            for task in all_tasks:
                print(f"   - {task.id}: {task.type} ({task.status.value})")
            
            # Clean up demo task
            print("\n🧹 Cleaning up demo task...")
            await session.delete(demo_task)
            await session.commit()
            print("   Demo task removed from database")
            
        print("\n🎉 Demo completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        return False

async def demo_bulk_operations():
    """Demonstrate bulk task operations."""
    try:
        from seedcore.database import get_async_pg_session_factory
        from seedcore.models.task import Task, TaskStatus
        
        print("\n📦 Bulk Task Operations Demo")
        print("=" * 40)
        
        async_session_factory = get_async_pg_session_factory()
        
        async with async_session_factory() as session:
            # Create multiple tasks
            print("   Creating multiple tasks...")
            
            task_types = ["data_cleaning", "feature_engineering", "model_training", "evaluation"]
            tasks = []
            
            for i, task_type in enumerate(task_types):
                task = Task(
                    type=task_type,
                    description=f"Bulk demo task {i+1}: {task_type}",
                    params={"batch_id": f"batch_{i+1}", "priority": "normal"},
                    domain="data_pipeline",
                    drift_score=0.1 * (i + 1)
                )
                tasks.append(task)
            
            session.add_all(tasks)
            await session.commit()
            
            print(f"   Created {len(tasks)} tasks")
            
            # Update all tasks to queued
            print("   Updating all tasks to queued status...")
            for task in tasks:
                task.status = TaskStatus.QUEUED
            await session.commit()
            
            print("   All tasks marked as queued")
            
            # Clean up
            print("   Cleaning up bulk tasks...")
            for task in tasks:
                await session.delete(task)
            await session.commit()
            
            print("   Bulk tasks cleaned up")
            
        return True
        
    except Exception as e:
        print(f"❌ Bulk operations demo failed: {e}")
        return False

async def main():
    """Run the demo."""
    print("🚀 SeedCore Database Task Management Demo")
    print("=" * 60)
    
    # Check database connectivity first
    try:
        from seedcore.database import check_pg_health
        
        print("🔍 Checking database connectivity...")
        if not await check_pg_health():
            print("❌ Database is not accessible. Please check your configuration.")
            return 1
            
        print("✅ Database is accessible")
        
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return 1
    
    # Run demos
    demos = [
        ("Task Lifecycle", demo_task_lifecycle),
        ("Bulk Operations", demo_bulk_operations),
    ]
    
    results = []
    
    for demo_name, demo_func in demos:
        print(f"\n📋 Running: {demo_name}")
        print("-" * 40)
        
        try:
            result = await demo_func()
            results.append((demo_name, result))
        except Exception as e:
            print(f"❌ Demo {demo_name} crashed: {e}")
            results.append((demo_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Demo Results Summary")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for demo_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {demo_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Overall: {passed}/{total} demos passed")
    
    if passed == total:
        print("🎉 All demos completed successfully!")
        print("\n💡 The database-backed task management system is working correctly.")
        print("   You can now integrate this into your main application.")
        return 0
    else:
        print("⚠️  Some demos failed. Please review the issues above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
