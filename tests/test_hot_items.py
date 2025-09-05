import ray
import json
from src.seedcore.memory.working_memory import MwManager
from src.seedcore.bootstrap import get_mw_store
from src.seedcore.utils.ray_utils import ensure_ray_initialized

def test_hot_items():
    print("--- Testing Hot Items Tracking ---")
    ensure_ray_initialized()
    
    # Create a MwManager
    mw_manager = MwManager(organ_id="test_organ")
    
    # Simulate some misses
    test_item_id = "test_item_123"
    print(f"Simulating misses for {test_item_id}...")
    
    # Get the mw store
    mw_store = get_mw_store()
    
    # Simulate some misses
    for i in range(5):
        print(f"Simulating miss #{i+1}")
        mw_store.incr.remote(test_item_id)
    
    # Check hot items
    print("Checking hot items...")
    hot_items = mw_manager.get_hot_items(top_n=3)
    print(f"Hot items: {hot_items}")
    
    # Check if our test item is in the hot items
    found = False
    for item_id, count in hot_items:
        if item_id == test_item_id:
            print(f"✅ Found test item with {count} misses")
            found = True
            break
    
    if not found:
        print("❌ Test item not found in hot items")
    
    print("--- Test Complete ---")

if __name__ == "__main__":
    test_hot_items() 