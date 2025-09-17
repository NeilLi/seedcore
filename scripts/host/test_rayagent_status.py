#!/usr/bin/env python3
"""
Test script to verify RayAgent has get_status() method
"""

import sys
import os
from pathlib import Path

# Add src to path for imports
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import ray
from seedcore.agents.ray_actor import RayAgent

def test_rayagent_status():
    """Test that RayAgent has get_status() method and returns proper data."""
    print("🧪 Testing RayAgent get_status() method...")
    
    # Initialize Ray
    ray.init(ignore_reinit_error=True)
    
    try:
        # Create a RayAgent
        agent = RayAgent.remote(
            agent_id="test_agent_1",
            organ_id="test_organ_1",
            initial_role_probs={'E': 0.8, 'S': 0.2, 'O': 0.0}
        )
        
        # Test get_status() method
        status = ray.get(agent.get_status.remote())
        
        print("✅ RayAgent.get_status() method exists and works!")
        print(f"📊 Status data: {status}")
        
        # Verify expected fields
        expected_fields = [
            "agent_id", "organ_id", "instance_id", "uptime_s", "status",
            "lifecycle_state", "capability_score", "memory_utilization",
            "tasks_processed", "successful_tasks", "success_rate"
        ]
        
        missing_fields = [field for field in expected_fields if field not in status]
        if missing_fields:
            print(f"⚠️ Missing fields: {missing_fields}")
        else:
            print("✅ All expected fields present in status")
        
        # Verify data types and values
        assert status["agent_id"] == "test_agent_1"
        assert status["organ_id"] == "test_organ_1"
        assert status["status"] == "healthy"
        assert isinstance(status["uptime_s"], (int, float))
        assert isinstance(status["capability_score"], (int, float))
        assert isinstance(status["tasks_processed"], int)
        
        print("✅ All assertions passed!")
        
    except AttributeError as e:
        print(f"❌ RayAgent missing get_status() method: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing RayAgent: {e}")
        return False
    finally:
        ray.shutdown()
    
    return True

if __name__ == "__main__":
    success = test_rayagent_status()
    sys.exit(0 if success else 1)

