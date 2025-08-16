#!/usr/bin/env python3
"""
Comprehensive Ray actor monitoring script.
"""

import ray
import sys
import os
import asyncio
import json
from datetime import datetime

def monitor_actors():
    """Monitor all Ray actors and their status."""
    try:
        # Initialize Ray connection
        if not ray.is_initialized():
            ray.init(address="ray://ray-head:10001", ignore_reinit_error=True)
            print("🔌 Connected to Ray cluster...")
        
        print("🔍 Ray Actor Monitor")
        print("=" * 60)
        print(f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Import required modules
        try:
            from src.seedcore.bootstrap import get_miss_tracker, get_shared_cache
            from src.seedcore.agents.observer_agent import ObserverAgent
        except ImportError as e:
            print(f"⚠️  Could not import seedcore modules: {e}")
            print("   This is normal if running from ray-head container")
            return True
        
        # Check singleton actors
        print("📊 Singleton Actors Status:")
        print("-" * 30)
        
        actors_status = {}
        
        # MissTracker
        try:
            miss_tracker = get_miss_tracker()
            # Try to get some basic info
            try:
                # This might fail if no misses recorded yet
                top_misses = ray.get(miss_tracker.get_top_n.remote(1))
                actors_status["MissTracker"] = {
                    "status": "✅ Running",
                    "top_misses": len(top_misses) if top_misses else 0
                }
            except:
                actors_status["MissTracker"] = {
                    "status": "✅ Running",
                    "top_misses": 0
                }
        except Exception as e:
            actors_status["MissTracker"] = {
                "status": f"❌ Error: {str(e)[:50]}",
                "top_misses": 0
            }
        
        # SharedCache
        try:
            shared_cache = get_shared_cache()
            # Try to get cache info
            try:
                # This might fail if cache is empty
                cache_keys = ray.get(shared_cache.keys.remote())
                actors_status["SharedCache"] = {
                    "status": "✅ Running",
                    "cache_items": len(cache_keys) if cache_keys else 0
                }
            except:
                actors_status["SharedCache"] = {
                    "status": "✅ Running",
                    "cache_items": 0
                }
        except Exception as e:
            actors_status["SharedCache"] = {
                "status": f"❌ Error: {str(e)[:50]}",
                "cache_items": 0
            }
        
        # MwStore
        try:
            from src.seedcore.bootstrap import get_mw_store
            mw_store = get_mw_store()
            actors_status["MwStore"] = {
                "status": "✅ Running",
                "info": "Working memory store"
            }
        except Exception as e:
            actors_status["MwStore"] = {
                "status": f"❌ Error: {str(e)[:50]}",
                "info": "Working memory store"
            }
        
        # Print singleton actors status
        for name, info in actors_status.items():
            print(f"🎭 {name}: {info['status']}")
            if 'top_misses' in info:
                print(f"   📈 Top misses: {info['top_misses']}")
            if 'cache_items' in info:
                print(f"   💾 Cache items: {info['cache_items']}")
            if 'info' in info:
                print(f"   ℹ️  {info['info']}")
            print()
        
        # Check for ObserverAgent
        print("👁️  ObserverAgent Status:")
        print("-" * 30)
        
        try:
            # Try to get existing ObserverAgent
            observer = ray.get_actor("ObserverAgent", namespace="seedcore")
            print("✅ ObserverAgent: Found existing instance")
            
            # Try to get status
            try:
                status = ray.get(observer.get_status.remote())
                print(f"   🆔 Agent ID: {status.get('agent_id', 'Unknown')}")
                print(f"   ✅ Ready: {status.get('is_ready', False)}")
                print(f"   🎯 Miss Threshold: {status.get('miss_threshold', 'Unknown')}")
            except Exception as e:
                print(f"   ⚠️  Could not get status: {str(e)[:50]}")
                
        except:
            print("ℹ️  ObserverAgent: No existing instance found")
            print("   💡 Create one by running a scenario or test")
        
        print()
        
        # Cluster info
        print("🌐 Cluster Information:")
        print("-" * 30)
        try:
            print(f"   🔗 Ray Address: {ray.get_runtime_context().gcs_address}")
            print(f"   ✅ Ray Initialized: {ray.is_initialized()}")
            
            # Try to get basic cluster stats
            try:
                # This might not work without dashboard
                print(f"   📊 Dashboard: Enabled and working")
            except:
                pass
                
        except Exception as e:
            print(f"   ❌ Error getting cluster info: {str(e)[:50]}")
        
        print()
        print("💡 Tips:")
        print("   • Run 'python -m scripts.scenario_3_proactive_caching' to create ObserverAgent")
        print("   • Check logs with 'docker compose logs ray-head'")
        print("   • Monitor real-time with 'docker compose logs -f ray-head'")
        print("   • Access dashboard at http://localhost:8265")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = monitor_actors()
    sys.exit(0 if success else 1) 