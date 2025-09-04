#!/usr/bin/env python3
"""
Demo script showing how to use the Task Table Helper

This script demonstrates the various features of the task table helper:
- Listing tasks with different filters
- Showing detailed task information
- Displaying task statistics
- Task ID printing functionality
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.task_table_helper import TaskTableHelper, TaskStatus

async def demo_task_helper():
    """Demonstrate the task table helper functionality."""
    
    print("🚀 Task Table Helper Demo")
    print("=" * 50)
    
    # Initialize the helper
    helper = TaskTableHelper()
    
    try:
        async with helper:
            print("\n1️⃣  Task Statistics")
            print("-" * 30)
            stats = await helper.get_task_statistics()
            helper.print_statistics(stats)
            
            print("\n2️⃣  List Recent Tasks (Last 10)")
            print("-" * 30)
            recent_tasks = await helper.list_tasks(limit=10)
            if recent_tasks:
                helper.print_task_header()
                for task in recent_tasks:
                    helper.print_task_row(task)
            else:
                print("No tasks found.")
            
            print("\n3️⃣  List Running Tasks")
            print("-" * 30)
            running_tasks = await helper.list_tasks(status="running")
            if running_tasks:
                helper.print_task_header()
                for task in running_tasks:
                    helper.print_task_row(task)
            else:
                print("No running tasks found.")
            
            print("\n4️⃣  List Failed Tasks")
            print("-" * 30)
            failed_tasks = await helper.list_tasks(status="failed", limit=5)
            if failed_tasks:
                helper.print_task_header()
                for task in failed_tasks:
                    helper.print_task_row(task)
            else:
                print("No failed tasks found.")
            
            print("\n5️⃣  Show Task ID Printing")
            print("-" * 30)
            if recent_tasks:
                first_task = recent_tasks[0]
                print("Task ID printing examples:")
                helper.print_task_id(first_task.id)
                helper.print_task_id(first_task.id, "🆔 ID: ")
                helper.print_task_id(first_task.id, "📋 Task: ")
                
                print("\n6️⃣  Show Detailed Task Information")
                print("-" * 30)
                helper.print_task_details(first_task)
            else:
                print("No tasks available for detailed view.")
            
            print("\n7️⃣  Filter by Task Type")
            print("-" * 30)
            # Get unique task types from recent tasks
            task_types = list(set(task.type for task in recent_tasks[:5]))
            for task_type in task_types[:3]:  # Show first 3 types
                type_tasks = await helper.list_tasks(task_type=task_type, limit=3)
                if type_tasks:
                    print(f"\nTasks of type '{task_type}':")
                    helper.print_task_header()
                    for task in type_tasks:
                        helper.print_task_row(task)
    
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        print("Make sure the database is running and accessible.")

def print_usage_examples():
    """Print usage examples for the task helper."""
    print("\n📚 Usage Examples")
    print("=" * 50)
    print("""
Command Line Usage:

1. List all tasks:
   python scripts/task_table_helper.py list

2. List running tasks:
   python scripts/task_table_helper.py list --status running

3. List tasks by type:
   python scripts/task_table_helper.py list --type graph_embed

4. List tasks by domain:
   python scripts/task_table_helper.py list --domain user_123

5. Show detailed task info:
   python scripts/task_table_helper.py show <task_id>

6. Show task statistics:
   python scripts/task_table_helper.py stats

7. Show statistics as JSON:
   python scripts/task_table_helper.py stats --json

8. List with full task IDs:
   python scripts/task_table_helper.py list --full-id

9. Limit results:
   python scripts/task_table_helper.py list --limit 20

Programmatic Usage:

```python
from scripts.task_table_helper import TaskTableHelper

async def example():
    async with TaskTableHelper() as helper:
        # List tasks
        tasks = await helper.list_tasks(status="running")
        
        # Get specific task
        task = await helper.get_task_by_id("task-uuid-here")
        
        # Print task details
        helper.print_task_details(task)
        
        # Get statistics
        stats = await helper.get_task_statistics()
        helper.print_statistics(stats)
```
""")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print_usage_examples()
    else:
        asyncio.run(demo_task_helper())
        print_usage_examples()


