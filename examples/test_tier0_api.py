#!/usr/bin/env python3
"""
Test script for Tier 0 API functionality.
"""

import requests
import json
import time
import random

API_BASE = "http://localhost:8000"

def test_tier0_api():
    """Test the Tier 0 API endpoints."""
    print("🧪 Testing Tier 0 API Endpoints")
    print("=" * 40)
    
    # 1. Create agents
    print("\n1️⃣ Creating agents...")
    
    agent_configs = [
        {"agent_id": "agent_alpha", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}},
        {"agent_id": "agent_beta", "role_probs": {"E": 0.2, "S": 0.7, "O": 0.1}},
        {"agent_id": "agent_gamma", "role_probs": {"E": 0.3, "S": 0.3, "O": 0.4}}
    ]
    
    response = requests.post(f"{API_BASE}/tier0/agents/create_batch", 
                           json={"agent_configs": agent_configs})
    result = response.json()
    print(f"✅ Created agents: {result}")
    
    # 2. List agents
    print("\n2️⃣ Listing agents...")
    response = requests.get(f"{API_BASE}/tier0/agents")
    result = response.json()
    print(f"✅ Agents: {result}")
    
    # 3. Execute tasks
    print("\n3️⃣ Executing tasks...")
    
    task_types = [
        {"type": "data_analysis", "complexity": 0.8},
        {"type": "pattern_recognition", "complexity": 0.6},
        {"type": "optimization", "complexity": 0.9},
        {"type": "classification", "complexity": 0.5},
        {"type": "prediction", "complexity": 0.7}
    ]
    
    for i in range(5):
        task_type = random.choice(task_types)
        task_data = {
            "task_id": f"task_{i+1}",
            "type": task_type["type"],
            "complexity": task_type["complexity"],
            "payload": f"Sample data for {task_type['type']}"
        }
        
        response = requests.post(f"{API_BASE}/tier0/agents/execute_random", 
                               json={"task_data": task_data})
        result = response.json()
        
        if result["success"]:
            task_result = result["result"]
            print(f"  ✅ Task {i+1}: {task_result['agent_id']} "
                  f"(success={task_result['success']}, quality={task_result['quality']:.3f})")
        else:
            print(f"  ❌ Task {i+1} failed: {result['message']}")
        
        time.sleep(0.5)
    
    # 4. Get system summary
    print("\n4️⃣ System summary...")
    response = requests.get(f"{API_BASE}/tier0/summary")
    result = response.json()
    
    if result["success"]:
        summary = result["summary"]
        print(f"✅ Summary: {summary['total_agents']} agents, "
              f"{summary['total_tasks_processed']} tasks, "
              f"avg_cap={summary['average_capability_score']:.3f}")
    else:
        print(f"❌ Summary failed: {result['message']}")
    
    # 5. Get agent heartbeats
    print("\n5️⃣ Agent heartbeats...")
    response = requests.get(f"{API_BASE}/tier0/agents/heartbeats")
    result = response.json()
    
    if result["success"]:
        heartbeats = result["heartbeats"]
        print(f"✅ Heartbeats: {len(heartbeats)} agents")
        for agent_id, heartbeat in heartbeats.items():
            perf = heartbeat.get("performance_metrics", {})
            print(f"  {agent_id}: capability={perf.get('capability_score_c', 0):.3f}, "
                  f"tasks={perf.get('tasks_processed', 0)}")
    else:
        print(f"❌ Heartbeats failed: {result['message']}")
    
    # 6. Execute task on specific agent
    print("\n6️⃣ Execute task on specific agent...")
    task_data = {
        "task_id": "specific_task",
        "type": "special_analysis",
        "complexity": 0.9,
        "payload": "High-priority analysis task"
    }
    
    response = requests.post(f"{API_BASE}/tier0/agents/agent_alpha/execute", 
                           json={"task_data": task_data})
    result = response.json()
    
    if result["success"]:
        task_result = result["result"]
        print(f"✅ Specific task: {task_result['agent_id']} "
              f"(success={task_result['success']}, quality={task_result['quality']:.3f})")
    else:
        print(f"❌ Specific task failed: {result['message']}")
    
    print(f"\n🎉 Tier 0 API test completed!")

if __name__ == "__main__":
    test_tier0_api() 