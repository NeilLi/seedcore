#!/usr/bin/env python3
"""
Script to clean up existing organs and recreate them with the new 1-agent-per-organ configuration.
"""

import ray
import asyncio
import time

async def cleanup_and_recreate_organs():
    """Clean up existing organs and recreate them with new configuration."""
    
    print("🔧 Cleaning up existing organs...")
    
    # Initialize Ray
    if not ray.is_initialized():
        ray.init(address="ray://ray-head:10001", namespace="seedcore")
    
    # List of organ names to clean up
    organ_names = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
    
    for organ_name in organ_names:
        try:
            # Try to get the existing organ
            existing_organ = ray.get_actor(organ_name)
            print(f"Found existing organ: {organ_name}")
            
            # Try to terminate the organ (this will kill all its agents)
            try:
                ray.kill(existing_organ)
                print(f"✅ Terminated organ: {organ_name}")
            except Exception as e:
                print(f"⚠️  Could not terminate organ {organ_name}: {e}")
                
        except ValueError:
            print(f"Organ {organ_name} not found")
        except Exception as e:
            print(f"Error with organ {organ_name}: {e}")
    
    print("⏳ Waiting for cleanup to complete...")
    await asyncio.sleep(5)
    
    print("✅ Cleanup complete. Restart the API container to recreate organs with new configuration.")

if __name__ == "__main__":
    asyncio.run(cleanup_and_recreate_organs()) 