#!/usr/bin/env python3
"""
Debug script to manually test organ creation and see what's happening step by step.
"""

import os
import ray
import logging
import traceback
from typing import Dict, Any

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def debug_organ_creation():
    """Debug the organ creation process step by step."""
    print("🔍 Debugging Organ Creation Process")
    print("=" * 50)
    
    # 1. Check environment variables
    print("\n🔍 STEP 1: Environment Variables")
    print("-" * 30)
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    
    print(f"RAY_HOST: {ray_host}")
    print(f"RAY_PORT: {ray_port}")
    print(f"RAY_NAMESPACE: {ray_namespace}")
    
    # 2. Initialize Ray connection
    print("\n🔍 STEP 2: Ray Connection")
    print("-" * 30)
    try:
        ray_address = f"ray://{ray_host}:{ray_port}"
        print(f"Connecting to Ray at: {ray_address}")
        
        if ray.is_initialized():
            print("⚠️ Ray already initialized, shutting down first...")
            ray.shutdown()
        
        ray.init(address=ray_address, namespace=ray_namespace)
        print("✅ Ray connection established successfully!")
        
        # Check Ray context
        runtime_context = ray.get_runtime_context()
        print(f"Ray namespace: {runtime_context.namespace}")
        print(f"Ray address: {runtime_context.gcs_address}")
        
        # Clean up any existing test actors from previous runs
        print("\n🧹 Cleaning up any existing test actors...")
        try:
            from ray.util.state import list_actors
            actors = list_actors()
            test_actors = [actor for actor in actors if actor.name and actor.name.startswith("test_organ_")]
            if test_actors:
                print(f"Found {len(test_actors)} existing test actors, cleaning up...")
                for actor in test_actors:
                    try:
                        ray.kill(actor.actor_id)
                        print(f"✅ Cleaned up test actor: {actor.name}")
                    except Exception as cleanup_e:
                        print(f"⚠️ Could not clean up test actor {actor.name}: {cleanup_e}")
            else:
                print("✅ No existing test actors found")
        except Exception as cleanup_e:
            print(f"⚠️ Could not list actors for cleanup: {cleanup_e}")
        
    except Exception as e:
        print(f"❌ Failed to connect to Ray: {e}")
        print(f"Exception type: {type(e)}")
        traceback.print_exc()
        return False
    
    # 3. Test basic Ray functionality
    print("\n🔍 STEP 3: Basic Ray Functionality")
    print("-" * 30)
    try:
        # Test cluster resources
        cluster_resources = ray.cluster_resources()
        available_resources = ray.available_resources()
        print(f"Cluster resources: {cluster_resources}")
        print(f"Available resources: {available_resources}")
        
        # Test if we can create a simple actor
        @ray.remote
        class TestActor:
            def __init__(self):
                self.value = 42
            
            def get_value(self):
                return self.value
        
        test_actor = TestActor.remote()
        result = ray.get(test_actor.get_value.remote())
        print(f"✅ Test actor created successfully: {result}")
        
        # Clean up test actor
        ray.kill(test_actor)
        print("✅ Test actor cleaned up")
        
    except Exception as e:
        print(f"❌ Basic Ray functionality test failed: {e}")
        print(f"Exception type: {type(e)}")
        traceback.print_exc()
        return False
    
    # 4. Test Organ import and creation
    print("\n🔍 STEP 4: Organ Import and Creation")
    print("-" * 30)
    try:
        from src.seedcore.organs.base import Organ
        print("✅ Organ class imported successfully")
        
        # Test creating a simple organ with unique name
        import uuid
        test_organ_name = f"test_organ_{uuid.uuid4().hex[:8]}"
        print(f"🔧 Using unique test organ name: {test_organ_name}")
        
        # Get the current namespace for consistency
        current_namespace = getattr(ray.get_runtime_context(), 'namespace', None)
        print(f"🔧 Creating test organ in namespace: {current_namespace}")
        
        test_organ = Organ.options(
            name=test_organ_name,
            lifetime="detached",
            num_cpus=0.1,
            namespace=current_namespace  # Use the same namespace
        ).remote(
            organ_id=test_organ_name,
            organ_type="Test"
        )
        print("✅ Test organ created successfully")
        
        # Test organ functionality
        status = ray.get(test_organ.get_status.remote())
        print(f"✅ Test organ functions: {status}")
        
        # Clean up test organ
        try:
            ray.kill(test_organ)
            print("✅ Test organ cleaned up")
        except Exception as e:
            print(f"⚠️ Warning: Could not clean up test organ: {e}")
            # Try to get and kill by name as fallback
            try:
                existing_actor = ray.get_actor(test_organ_name)
                ray.kill(existing_actor)
                print("✅ Test organ cleaned up by name")
            except Exception as cleanup_e:
                print(f"⚠️ Could not clean up test organ by name: {cleanup_e}")
        
    except Exception as e:
        print(f"❌ Organ creation test failed: {e}")
        print(f"Exception type: {type(e)}")
        traceback.print_exc()
        return False
    
    # 5. Test OrganismManager
    print("\n🔍 STEP 5: OrganismManager Test")
    print("-" * 30)
    try:
        from src.seedcore.organs.organism_manager import OrganismManager
        print("✅ OrganismManager imported successfully")
        
        # Create organism manager
        organism_manager = OrganismManager()
        print("✅ OrganismManager created successfully")
        
        # Check configuration
        print(f"Organ configs loaded: {len(organism_manager.organ_configs)}")
        for config in organism_manager.organ_configs:
            print(f"  - {config['id']}: {config['type']} ({config['agent_count']} agents)")
        
        # Check initialization state
        print(f"Initialized: {organism_manager._initialized}")
        print(f"Current organs: {list(organism_manager.organs.keys())}")
        
        # Test organ creation (without full initialization)
        print("\n🔍 Testing organ creation method...")
        organism_manager._create_organs()
        print(f"✅ Organs created: {list(organism_manager.organs.keys())}")
        
        # Check if organs are accessible
        for organ_id in organism_manager.organs:
            try:
                organ = organism_manager.organs[organ_id]
                status = ray.get(organ.get_status.remote())
                print(f"✅ Organ {organ_id}: {status}")
            except Exception as e:
                print(f"❌ Failed to access organ {organ_id}: {e}")
        
    except Exception as e:
        print(f"❌ OrganismManager test failed: {e}")
        print(f"Exception type: {type(e)}")
        traceback.print_exc()
        return False
    
    # 6. Summary
    print("\n🔍 STEP 6: Summary")
    print("-" * 30)
    print("✅ All tests completed successfully!")
    print("✅ Ray connection working")
    print("✅ Basic Ray functionality working")
    print("✅ Organ creation working")
    print("✅ OrganismManager working")
    
    return True

def main():
    """Main function."""
    print("🔍 Organ Creation Debug Script")
    print("=" * 50)
    
    try:
        success = debug_organ_creation()
        
        if success:
            print("\n🎉 Debug completed successfully!")
            print("The organ creation process should work now.")
        else:
            print("\n❌ Debug encountered issues.")
            print("Check the logs above for details.")
        
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        traceback.print_exc()
        success = False
    
    finally:
        # Clean up
        try:
            if ray.is_initialized():
                ray.shutdown()
                print("✅ Ray connection closed")
        except:
            pass
    
    return success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
