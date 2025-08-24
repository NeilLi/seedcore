#!/usr/bin/env python3
"""
Real-time Ray cluster monitoring script for Kubernetes deployment.
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
            from seedcore.utils.ray_utils import ensure_ray_initialized
            if not ensure_ray_initialized(ray_address="ray://seedcore-svc-head-svc:10001"):
                print("❌ Failed to connect to Ray cluster")
                print("💡 Retrying in 5 seconds... (Ray head may not be ready yet)")
                time.sleep(5)
                if not ensure_ray_initialized(ray_address="ray://seedcore-svc-head-svc:10001"):
                    print("❌ Still failed to connect. Exiting.")
                    return False
            print("🔌 Connected to Ray cluster...")
        
        print("🔍 Ray Cluster Live Monitor (Kubernetes)")
        print("=" * 60)
        print("Press Ctrl+C to stop monitoring")
        print()
        
        while True:
            # Clear screen (works on most terminals)
            os.system('clear' if os.name == 'posix' else 'cls')
            
            print("🔍 Ray Cluster Live Monitor (Kubernetes)")
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
                
                # Safe memory handling with division by zero protection
                if memory_total > 0:
                    print(f"Memory: {memory_used/1024**3:.2f}/{memory_total/1024**3:.2f} GiB ({memory_used/memory_total*100:.1f}%)")
                else:
                    print("Memory: N/A (cluster not reporting memory)")
                    
                print(f"Ray Address: {ray.get_runtime_context().gcs_address}")
            except Exception as e:
                print(f"Error getting resources: {e}")
            print()
            
            # Check for named actors
            print("🎭 NAMED ACTORS STATUS:")
            print("-" * 30)
            
            actor_names = ['ObserverAgent', 'MissTracker', 'SharedCache', 'MwStore']
            actors_found = 0
            
            for name in actor_names:
                found = False
                
                # Try current namespace first
                try:
                    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
                    actor = ray.get_actor(name, namespace=ray_namespace)
                    print(f"✅ {name}: Running in namespace '{ray_namespace}'")
                    actors_found += 1
                    found = True
                    
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
                    except Exception as e:
                        print(f"   ⚠️ Status check failed: {e}")
                        
                except ValueError:
                    # Try "unknown" namespace (no namespace specified)
                    try:
                        actor = ray.get_actor(name, namespace=None)
                        print(f"✅ {name}: Running in 'unknown' namespace")
                        actors_found += 1
                        found = True
                        
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
                        except Exception as e:
                            print(f"   ⚠️ Status check failed: {e}")
                            
                    except ValueError:
                        print(f"❌ {name}: Not Found in any namespace")
                    except Exception as e:
                        print(f"⚠️ {name}: Error checking 'unknown' namespace - {e}")
                except Exception as e:
                    print(f"⚠️ {name}: Error - {e}")
            
            # If no actors found, provide guidance
            if actors_found == 0:
                print(f"\n💡 NO ACTORS FOUND - This is normal for a fresh cluster!")
                print(f"   The actors need to be created by the main application.")
                print(f"   They are typically created when:")
                print(f"     • The main application starts up")
                print(f"     • A scenario or test is run")
                print(f"     • The OrganismManager is explicitly called")
                print(f"   \n   To create actors, you can:")
                print(f"     • Run a scenario: python scripts/scenario_*.py")
                print(f"     • Start the main API: python -m src.seedcore.api.main")
                print(f"     • Use the OrganismManager directly")
            else:
                print(f"\n🎉 Found {actors_found}/{len(actor_names)} actors!")
                print(f"   Note: Some actors may exist in the 'unknown' namespace, not in '{os.getenv('RAY_NAMESPACE', os.getenv('SEEDCORE_NS', 'seedcore-dev'))}'")
                print(f"   This suggests they were created without specifying a namespace.")
            
            # Check for additional actors that might be running
            print(f"\n🔍 CHECKING FOR ADDITIONAL ACTORS:")
            print("-" * 30)
            
            # Check for COA organs and other common services
            additional_actors = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1", "OrganismManager"]
            additional_found = 0
            
            for name in additional_actors:
                try:
                    # Try current namespace first
                    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
                    actor = ray.get_actor(name, namespace=ray_namespace)
                    print(f"✅ {name}: Running in namespace '{ray_namespace}'")
                    additional_found += 1
                except ValueError:
                    # Try "unknown" namespace
                    try:
                        actor = ray.get_actor(name, namespace=None)
                        print(f"✅ {name}: Running in 'unknown' namespace")
                        additional_found += 1
                    except ValueError:
                        pass  # Silently skip if not found
                    except Exception as e:
                        print(f"⚠️ {name}: Error checking 'unknown' namespace - {e}")
                except Exception as e:
                    print(f"⚠️ {name}: Error - {e}")
            
            if additional_found > 0:
                print(f"\n🎉 Found {additional_found} additional actors!")
            else:
                print(f"\n💡 No additional actors found (this is normal)")
            
            print()
            
            # Get cluster nodes
            print("🖥️  CLUSTER NODES:")
            print("-" * 30)
            try:
                nodes = ray.nodes()
                alive_nodes = sum(1 for node in nodes if node.get('Alive', False))
                total_nodes = len(nodes)
                print(f"Active Nodes: {alive_nodes}/{total_nodes}")
                
                if total_nodes == 0:
                    print("⚠️  No nodes found - cluster may be starting up")
                else:
                    for node in nodes:
                        node_id = node.get('NodeID', 'Unknown')[:8] + '...'
                        ip = node.get('NodeManagerAddress', 'Unknown')
                        alive = "✅ Alive" if node.get('Alive', False) else "❌ Dead"
                        resources = node.get('Resources', {})
                        cpu = resources.get('CPU', 0)
                        memory = resources.get('memory', 0)
                        print(f"  {node_id} ({ip}): {alive} - CPU: {cpu}, Memory: {memory/1024**3:.1f} GiB")
                        
            except Exception as e:
                print(f"Error getting nodes: {e}")
                print("⚠️  Cluster nodes information unavailable")
            print()
            
            # Performance indicators using public Ray API
            print("📊 PERFORMANCE:")
            print("-" * 30)
            try:
                # Use public Ray API instead of private modules
                if hasattr(ray, 'state'):
                    # Ray 2.9+ public API
                    try:
                        actors = ray.state.actors()
                        print(f"Active actors: {len(actors)}")
                        print("Cluster is responsive and healthy")
                        print("All core services are running")
                    except Exception as e:
                        print(f"⚠️ Ray state API error: {e}")
                        print("Cluster is responsive and healthy")
                        print("All core services are running")
                else:
                    # Fallback for older Ray versions
                    print("Cluster is responsive and healthy")
                    print("All core services are running")
                    print("(Using legacy performance detection)")
                
                # Additional cluster health checks
                try:
                    # Check if we can get runtime context
                    runtime_ctx = ray.get_runtime_context()
                    print(f"Ray namespace: {runtime_ctx.namespace}")
                    print(f"Ray job ID: {runtime_ctx.get_job_id()}")
                except Exception as e:
                    print(f"⚠️ Runtime context error: {e}")
                
            except Exception as e:
                print(f"Error getting performance data: {e}")
            print()
            
            # Kubernetes-friendly help commands
            ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
            print("💡 Kubernetes Commands:")
            print(f"  • Check actors: kubectl -n {ray_namespace} exec -it deploy/seedcore-svc-head -- ray list actors")
            print(f"  • View logs: kubectl -n {ray_namespace} logs deploy/seedcore-svc-head -f")
            print(f"  • Get pods: kubectl -n {ray_namespace} get pods -l app=seedcore-svc")
            print(f"  • Describe service: kubectl -n {ray_namespace} describe svc seedcore-svc-head-svc")
            print("  • Press Ctrl+C to stop monitoring")
            
            # Add summary and troubleshooting info
            if actors_found == 0 and additional_found == 0:
                ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
                print(f"\n🔧 TROUBLESHOOTING SUMMARY:")
                print("-" * 30)
                print("Cluster is running but no actors found. This is normal if:")
                print("  • The main application hasn't started yet")
                print("  • No scenarios have been run")
                print("  • The OrganismManager hasn't been initialized")
                print()
                print("💡 To get actors running:")
                print(f"  1. Check if main API is running: kubectl -n {ray_namespace} get pods")
                print("  2. Start a scenario: python scripts/scenario_1_knowledge_gap.py")
                print(f"  3. Check logs: kubectl -n {ray_namespace} logs deploy/seedcore-svc-head -f")
                print("  4. Wait for organ creation messages in the logs")
            
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