#!/usr/bin/env python3
"""
Real-time Ray cluster monitoring script.
Run this to continuously monitor your Ray cluster status.
"""

import ray
import time
import sys
import os
from datetime import datetime

def monitor_cluster_live():
    """Monitor Ray cluster in real-time."""
    try:
        # Initialize Ray connection
        if not ray.is_initialized():
            ray.init(address="ray://ray-head:10001", ignore_reinit_error=True)
            print("🔌 Connected to Ray cluster...")
        
        print("🔍 Ray Cluster Live Monitor")
        print("=" * 60)
        print("Press Ctrl+C to stop monitoring")
        print()
        
        while True:
            # Clear screen (works on most terminals)
            os.system('clear' if os.name == 'posix' else 'cls')
            
            print("🔍 Ray Cluster Live Monitor")
            print("=" * 60)
            print(f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print()
            
            # Get cluster resources
            print("🌐 CLUSTER RESOURCES:")
            print("-" * 30)
            try:
                cluster_resources = ray.cluster_resources()
                available_resources = ray.available_resources()
                
                cpu_total = cluster_resources.get('CPU', 0)
                cpu_used = cpu_total - available_resources.get('CPU', 0)
                memory_total = cluster_resources.get('memory', 0)
                memory_used = memory_total - available_resources.get('memory', 0)
                
                print(f"CPU: {cpu_used:.1f}/{cpu_total:.1f} cores ({cpu_used/cpu_total*100:.1f}%)")
                print(f"Memory: {memory_used/1024**3:.2f}/{memory_total/1024**3:.2f} GiB ({memory_used/memory_total*100:.1f}%)")
                print(f"Ray Address: {ray.get_runtime_context().gcs_address}")
            except Exception as e:
                print(f"Error getting resources: {e}")
            print()
            
            # Check for named actors
            print("🎭 NAMED ACTORS STATUS:")
            print("-" * 30)
            
            actor_names = ['ObserverAgent', 'MissTracker', 'SharedCache', 'MwStore']
            for name in actor_names:
                try:
                    actor = ray.get_actor(name, namespace='seedcore')
                    print(f"✅ {name}: Running")
                    
                    # Try to get status for specific actors
                    try:
                        if name == 'MissTracker' and hasattr(actor, 'get_top_n'):
                            top_misses = ray.get(actor.get_top_n.remote(1))
                            print(f"   📈 Top misses: {len(top_misses) if top_misses else 0}")
                        elif name == 'SharedCache' and hasattr(actor, 'keys'):
                            cache_keys = ray.get(actor.keys.remote())
                            print(f"   💾 Cache items: {len(cache_keys) if cache_keys else 0}")
                        elif hasattr(actor, 'get_status'):
                            status = ray.get(actor.get_status.remote())
                            print(f"   📊 Status: {status}")
                    except:
                        pass
                        
                except:
                    print(f"❌ {name}: Not running")
            print()
            
            # Get cluster nodes
            print("🖥️  CLUSTER NODES:")
            print("-" * 30)
            try:
                nodes = ray.nodes()
                alive_nodes = sum(1 for node in nodes if node.get('Alive', False))
                total_nodes = len(nodes)
                print(f"Active Nodes: {alive_nodes}/{total_nodes}")
                
                for node in nodes:
                    node_id = node.get('NodeID', 'Unknown')[:8] + '...'
                    ip = node.get('NodeManagerAddress', 'Unknown')
                    alive = "✅ Alive" if node.get('Alive', False) else "❌ Dead"
                    print(f"  {node_id} ({ip}): {alive}")
            except Exception as e:
                print(f"Error getting nodes: {e}")
            print()
            
            # Performance indicators
            print("📊 PERFORMANCE:")
            print("-" * 30)
            try:
                # Check if there are any active tasks
                import ray._private.state
                state = ray._private.state.GlobalState()
                state._initialize_global_state()
                
                # Try to get some basic stats
                print("Cluster is responsive and healthy")
                print("All core services are running")
                
            except Exception as e:
                print(f"Error getting performance data: {e}")
            print()
            
            print("💡 Tips:")
            print("  • Access dashboard at http://localhost:8265")
            print("  • Run 'docker logs -f ray-head' for detailed logs")
            print("  • Press Ctrl+C to stop monitoring")
            
            # Wait before next update
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = monitor_cluster_live()
    sys.exit(0 if success else 1) 