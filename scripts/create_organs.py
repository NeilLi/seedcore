#!/usr/bin/env python3
"""
Script to create COA organs if they don't exist.
Useful for testing and development when the main application hasn't started yet.
"""

import os
import ray
import time
from typing import List, Dict, Any

def create_organs():
    """Create the basic COA organs if they don't exist."""
    print("🏗️  Creating COA Organs")
    print("=" * 50)
    
    # Initialize Ray connection
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_address = f"ray://{ray_host}:{ray_port}"
    
    print(f"🔗 Connecting to Ray at: {ray_address}")
    print(f"🏷️ Using namespace: {ray_namespace}")
    
    try:
        from seedcore.utils.ray_utils import ensure_ray_initialized
        if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
            print("❌ Failed to connect to Ray cluster")
            return False
        print("✅ Ray connection established successfully!")
    except Exception as e:
        print(f"❌ Failed to connect to Ray: {e}")
        return False
    
    # Check what organs already exist
    existing_organs = []
    organ_names = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
    
    print(f"\n🔍 Checking existing organs...")
    for organ_name in organ_names:
        try:
            actor = ray.get_actor(organ_name)
            existing_organs.append(organ_name)
            print(f"✅ {organ_name}: Already exists")
        except ValueError:
            print(f"❌ {organ_name}: Not found")
        except Exception as e:
            print(f"⚠️ {organ_name}: Error - {e}")
    
    if len(existing_organs) == len(organ_names):
        print(f"\n🎉 All organs already exist! No need to create anything.")
        return True
    
    print(f"\n📊 Summary: {len(existing_organs)}/{len(organ_names)} organs exist")
    
    # Try to create missing organs
    print(f"\n🚀 Attempting to create missing organs...")
    
    try:
        # Import the OrganismManager
        from src.seedcore.organs.organism_manager import OrganismManager
        
        # Create organism manager
        print("🔧 Creating OrganismManager...")
        organism_manager = OrganismManager()
        
        # Check if organs were created
        time.sleep(2)  # Give some time for creation
        
        print(f"\n🔍 Re-checking organs after creation...")
        newly_created = 0
        
        for organ_name in organ_names:
            try:
                actor = ray.get_actor(organ_name)
                if organ_name not in existing_organs:
                    print(f"✅ {organ_name}: Newly created")
                    newly_created += 1
                else:
                    print(f"✅ {organ_name}: Still exists")
            except ValueError:
                print(f"❌ {organ_name}: Still not found")
            except Exception as e:
                print(f"⚠️ {organ_name}: Error - {e}")
        
        print(f"\n📊 Creation Summary:")
        print(f"  - Organs that existed: {len(existing_organs)}")
        print(f"  - Newly created: {newly_created}")
        print(f"  - Total organs now: {len(existing_organs) + newly_created}")
        
        if newly_created > 0:
            print(f"\n🎉 Successfully created {newly_created} new organs!")
            return True
        else:
            print(f"\n⚠️  No new organs were created. This might mean:")
            print(f"    • The OrganismManager needs additional configuration")
            print(f"    • There are permission issues")
            print(f"    • The organ creation logic needs to be triggered differently")
            return False
            
    except ImportError as e:
        print(f"❌ Could not import OrganismManager: {e}")
        print(f"   Make sure you're running from the project root directory")
        return False
    except Exception as e:
        print(f"❌ Error creating organs: {e}")
        return False

def check_organ_status():
    """Check the status of all organs."""
    print(f"\n🔍 ORGAN STATUS CHECK:")
    print("-" * 30)
    
    organ_names = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
    
    for organ_name in organ_names:
        try:
            actor = ray.get_actor(organ_name)
            print(f"✅ {organ_name}: Found")
            
            # Try to get status
            try:
                status_future = actor.get_status.remote()
                status = ray.get(status_future)
                print(f"   - Type: {status.get('organ_type', 'Unknown')}")
                print(f"   - Agent Count: {status.get('agent_count', 0)}")
                print(f"   - Agent IDs: {status.get('agent_ids', [])}")
            except Exception as e:
                print(f"   - Status Error: {e}")
                
        except ValueError:
            print(f"❌ {organ_name}: Not Found")
        except Exception as e:
            print(f"⚠️ {organ_name}: Error - {e}")

def main():
    """Main function to create and check organs."""
    print("🏗️  COA Organ Creation Script")
    print("=" * 50)
    
    success = create_organs()
    
    if success:
        check_organ_status()
    
    print(f"\n{'='*50}")
    if success:
        print("🎉 Organ creation completed successfully!")
    else:
        print("❌ Organ creation encountered issues. Check the logs above.")
    
    # Clean up
    try:
        ray.shutdown()
        print("✅ Ray connection closed")
    except:
        pass
    
    return success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
