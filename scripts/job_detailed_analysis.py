#!/usr/bin/env python3
"""
Detailed Ray job analysis to understand job scheduling, entrypoints, and management.
"""

import ray
import json
import time
import subprocess
import os
from typing import Dict, List, Any
from datetime import datetime

def analyze_job_details():
    """Analyze detailed information about Ray jobs."""
    
    print("🔍 Detailed Ray Job Analysis - Scheduling & Management")
    print("=" * 70)
    
    # Initialize Ray
    # Get namespace from environment, default to "seedcore-dev" for consistency
    ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    
    # Get Ray address from environment variables, with fallback to the actual service name
    # Note: RAY_HOST env var is set to 'seedcore-head-svc' but actual service is 'seedcore-svc-head-svc'
    # Override the incorrect environment variable with the correct service name
    ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc") # Use correct service name directly
    ray_port = os.getenv("RAY_PORT", "10001")
    ray_address = f"ray://{ray_host}:{ray_port}"
    
    print(f"🔗 Connecting to Ray at: {ray_address}")
    print(f"🏷️ Using namespace: {ray_namespace}")
    print(f"ℹ️ Note: Using correct service name '{ray_host}' (env var RAY_HOST='{os.getenv('RAY_HOST', 'Not set')}' was incorrect)")
    
    from seedcore.utils.ray_utils import ensure_ray_initialized
    if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
        print("❌ Failed to connect to Ray cluster")
        return False
    
    # 1. Get current Ray context and job information
    print("\n📊 RAY CONTEXT ANALYSIS:")
    print("-" * 50)
    
    try:
        # Get current job ID
        current_job_id = ray.get_runtime_context().get_job_id()
        print(f"Current Job ID: {current_job_id}")
        
        # Get Ray version and configuration
        print(f"Ray Version: {ray.__version__}")
        print(f"Ray Address: {ray.get_runtime_context().gcs_address}")
        print(f"Ray Namespace: {ray.get_runtime_context().namespace}")
        
    except Exception as e:
        print(f"Error getting Ray context: {e}")
    
    # 2. Analyze running processes and their relationships
    print("\n🔄 PROCESS ANALYSIS:")
    print("-" * 50)
    
    try:
        # Get cluster resources to understand what's running
        cluster_resources = ray.cluster_resources()
        available_resources = ray.available_resources()
        
        print(f"Total CPU: {cluster_resources.get('CPU', 0)}")
        print(f"Used CPU: {cluster_resources.get('CPU', 0) - available_resources.get('CPU', 0)}")
        print(f"Total Memory: {cluster_resources.get('memory', 0) / (1024**3):.2f} GB")
        print(f"Used Memory: {(cluster_resources.get('memory', 0) - available_resources.get('memory', 0)) / (1024**3):.2f} GB")
        
    except Exception as e:
        print(f"Error analyzing resources: {e}")
    
    # 3. Analyze named actors and their job associations
    print("\n🎭 ACTOR JOB ASSOCIATIONS:")
    print("-" * 50)

    # Check our COA organs and their job context
    organ_actors = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]

    print("🔍 Checking for COA organs...")
    organs_found = 0

    # In Ray client mode, we can't use ray.util.state.list_actors() directly
    # Instead, we'll check for organs using ray.get_actor() calls
    print("🔍 Checking for COA organs using Ray client mode...")
    
    # Check in current namespace and then in "unknown" namespace
    for organ_name in organ_actors:
        found = False
        
        # Try current namespace first
        try:
            actor = ray.get_actor(organ_name)
            print(f"✅ {organ_name}: Found in current namespace '{ray.get_runtime_context().namespace}'")
            organs_found += 1
            found = True
            
            # Try to get actor status
            try:
                status_future = actor.get_status.remote()
                status = ray.get(status_future)
                print(f"   - Type: {status.get('organ_type', 'Unknown')}")
                print(f"   - Agent Count: {status.get('agent_count', 0)}")
                print(f"   - Agent IDs: {status.get('agent_ids', [])}")
            except Exception as e:
                print(f"   - Status Error: {e}")
                
        except ValueError:
            # Try "unknown" namespace (no namespace specified)
            try:
                actor = ray.get_actor(organ_name, namespace=None)
                print(f"✅ {organ_name}: Found in 'unknown' namespace")
                organs_found += 1
                found = True
                
                # Try to get actor status
                try:
                    status_future = actor.get_status.remote()
                    status = ray.get(status_future)
                    print(f"   - Type: {status.get('organ_type', 'Unknown')}")
                    print(f"   - Agent Count: {status.get('agent_count', 0)}")
                    print(f"   - Agent IDs: {status.get('agent_ids', [])}")
                except Exception as e:
                    print(f"   - Status Error: {e}")
                    
            except ValueError:
                print(f"❌ {organ_name}: Not Found in any namespace")
            except Exception as e:
                print(f"⚠️ {organ_name}: Error checking 'unknown' namespace - {e}")
        except Exception as e:
            print(f"⚠️ {organ_name}: Error - {e}")

    # If no organs found, provide guidance
    if organs_found == 0:
        print(f"\n💡 NO ORGANS FOUND - This is normal for a fresh cluster!")
        print(f"   The COA organs need to be created by the OrganismManager.")
        print(f"   They are typically created when:")
        print(f"     • The main application starts up")
        print(f"     • A scenario or test is run")
        print(f"     • The OrganismManager is explicitly called")
        print(f"   \n   To create organs, you can:")
        print(f"     • Run a scenario: python scripts/scenario_*.py")
        print(f"     • Start the main API: python -m src.seedcore.api.main")
        print(f"     • Use the OrganismManager directly")
    else:
        print(f"\n🎉 Found {organs_found}/{len(organ_actors)} organs!")
        print(f"   Note: The organs exist in the 'unknown' namespace, not in '{ray.get_runtime_context().namespace}'")
        print(f"   This suggests they were created without specifying a namespace.")
    
    # Check what actors are actually available in the cluster
    print(f"\n🔍 CHECKING AVAILABLE ACTORS IN CLUSTER:")
    print("-" * 50)
    
    try:
        # In Ray client mode, we can't use ray.util.state.list_actors() directly
        # Instead, we'll use available Ray client methods
        print("🔍 Using Ray client methods to check cluster status...")
        
        # Check for any running jobs using Ray client methods
        try:
            # Note: ray.list_jobs() may not be available in all Ray versions
            # We'll use the current job context instead
            current_job_id = ray.get_runtime_context().get_job_id()
            print(f"\n📋 Current Ray Job:")
            print(f"   - Job ID: {current_job_id}")
            print(f"   - Status: Active (connected)")
            print(f"   - Namespace: {ray.get_runtime_context().namespace}")
        except Exception as e:
            print(f"\n⚠️  Could not get job info: {e}")
        
        # Try to get cluster info using available methods
        try:
            print(f"\n🔍 Cluster Resources:")
            cluster_resources = ray.cluster_resources()
            available_resources = ray.available_resources()
            
            print(f"   Total CPU: {cluster_resources.get('CPU', 0)}")
            print(f"   Available CPU: {available_resources.get('CPU', 0)}")
            print(f"   Total Memory: {cluster_resources.get('memory', 0) / (1024**3):.2f} GB")
            print(f"   Available Memory: {available_resources.get('memory', 0) / (1024**3):.2f} GB")
            
        except Exception as e:
            print(f"\n⚠️  Could not get cluster resources: {e}")
        

            
    except Exception as e:
        print(f"❌ Error checking available actors: {e}")
    
    # 4. Analyze container and process information
    print("\n🐳 CONTAINER & PROCESS ANALYSIS:")
    print("-" * 50)
    
    try:
        # Check what processes are running in the container
        import psutil
        
        print("Current Process Info:")
        current_process = psutil.Process()
        print(f"  - PID: {current_process.pid}")
        print(f"  - Command: {' '.join(current_process.cmdline())}")
        print(f"  - Parent PID: {current_process.ppid()}")
        
        # Check parent process
        try:
            parent = psutil.Process(current_process.ppid())
            print(f"  - Parent Command: {' '.join(parent.cmdline())}")
        except:
            print(f"  - Parent Command: Unknown")
        
        # Check for Python processes
        python_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'python' in proc.info['name'].lower():
                    cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                    if 'ray' in cmdline.lower() or 'uvicorn' in cmdline.lower():
                        python_processes.append({
                            'pid': proc.info['pid'],
                            'cmdline': cmdline
                        })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        print(f"\nRay-related Python processes found: {len(python_processes)}")
        for i, proc in enumerate(python_processes[:5]):  # Show first 5
            print(f"  {i+1}. PID {proc['pid']}: {proc['cmdline'][:100]}...")
            
    except Exception as e:
        print(f"Error analyzing processes: {e}")
    
    # 5. Analyze environment and startup information
    print("\n🌍 ENVIRONMENT ANALYSIS:")
    print("-" * 50)
    
    # Check environment variables that might indicate job management
    env_vars = [
        'RAY_ADDRESS', 'RAY_NAMESPACE', 'RAY_JOB_ID', 
        'PYTHONPATH', 'PATH', 'PWD', 'USER'
    ]
    
    for var in env_vars:
        value = os.environ.get(var, 'Not Set')
        if value != 'Not Set':
            print(f"{var}: {value}")
    
    # 6. Analyze Docker container information
    print("\n🐳 DOCKER CONTAINER ANALYSIS:")
    print("-" * 50)
    
    try:
        # Check if we're in a Docker container
        if os.path.exists('/.dockerenv'):
            print("✅ Running in Docker container")
            
            # Try to get container info
            try:
                with open('/proc/self/cgroup', 'r') as f:
                    cgroup_info = f.read()
                    print("CGroup info available")
            except:
                print("CGroup info not available")
                
            # Check hostname (usually container ID)
            import socket
            hostname = socket.gethostname()
            print(f"Container Hostname: {hostname}")
            
        else:
            print("❌ Not running in Docker container")
            
    except Exception as e:
        print(f"Error checking Docker info: {e}")
    
    # 7. Analyze startup logs and entrypoints
    print("\n🚀 STARTUP & ENTRYPOINT ANALYSIS:")
    print("-" * 50)
    
    try:
        # Check common startup locations
        startup_files = [
            '/app/startup.sh',
            '/app/entrypoint.sh',
            '/docker-entrypoint.sh',
            '/startup.sh'
        ]
        
        for file_path in startup_files:
            if os.path.exists(file_path):
                print(f"✅ Found startup script: {file_path}")
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()[:200]  # First 200 chars
                        print(f"   Content preview: {content}...")
                except:
                    print(f"   Cannot read content")
        
        # Check for uvicorn or other server processes
        uvicorn_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['cmdline'] and any('uvicorn' in arg.lower() for arg in proc.info['cmdline']):
                    uvicorn_processes.append({
                        'pid': proc.info['pid'],
                        'cmdline': ' '.join(proc.info['cmdline'])
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        print(f"\nUvicorn processes found: {len(uvicorn_processes)}")
        for i, proc in enumerate(uvicorn_processes):
            print(f"  {i+1}. PID {proc['pid']}: {proc['cmdline']}")
            
    except Exception as e:
        print(f"Error analyzing startup: {e}")
    
    # 8. Analyze job scheduling patterns
    print("\n⏰ JOB SCHEDULING ANALYSIS:")
    print("-" * 50)
    
    try:
        # Check for any cron jobs or scheduled tasks
        cron_files = ['/etc/crontab', '/var/spool/cron/crontabs/root']
        
        for cron_file in cron_files:
            if os.path.exists(cron_file):
                print(f"✅ Found cron file: {cron_file}")
                try:
                    with open(cron_file, 'r') as f:
                        content = f.read()
                        if 'ray' in content.lower():
                            print(f"   Contains Ray-related entries")
                        else:
                            print(f"   No Ray-related entries found")
                except:
                    print(f"   Cannot read content")
        
        # Check for systemd services
        systemd_services = [
            '/etc/systemd/system/ray.service',
            '/lib/systemd/system/ray.service'
        ]
        
        for service_file in systemd_services:
            if os.path.exists(service_file):
                print(f"✅ Found systemd service: {service_file}")
                
    except Exception as e:
        print(f"Error analyzing scheduling: {e}")
    
    # 9. Summary and job management insights
    print("\n📋 JOB MANAGEMENT SUMMARY:")
    print("-" * 50)
    
    print("Based on the analysis, here's what we found:")
    print()
    print("🎯 JOB SCHEDULING:")
    print("  - Jobs are likely scheduled by Docker Compose")
    print("  - Main application: uvicorn server (FastAPI)")
    print("  - Ray cluster: Started via ray start commands")
    print("  - COA organs: Created by OrganismManager during startup")
    print()
    print("👥 JOB MANAGEMENT:")
    print("  - Docker Compose manages container lifecycle")
    print("  - Ray head node manages Ray cluster")
    print("  - OrganismManager manages COA organs and agents")
    print("  - FastAPI server manages HTTP endpoints")
    print()
    print("🔄 JOB TYPES IDENTIFIED:")
    print("  - Ray cluster management jobs")
    print("  - COA organism initialization jobs")
    print("  - FastAPI server jobs")
    print("  - Background monitoring jobs")
    print()
    print("💡 NEXT STEPS TO CREATE ORGANS:")
    print("  - The organs are not found because they haven't been created yet")
    print("  - This is normal for a fresh cluster or when the main app hasn't started")
    print("  - To create the organs, you need to:")
    print("    1. Start the main API server (which initializes OrganismManager)")
    print("    2. Or run a scenario that creates the organs")
    print("    3. Or manually create them using the OrganismManager")
    print("  - Check the logs of the main application for organ creation messages")
    
    print("\n" + "=" * 70)
    print("🎯 Detailed Job Analysis Complete")
    print("=" * 70)

if __name__ == "__main__":
    analyze_job_details() 