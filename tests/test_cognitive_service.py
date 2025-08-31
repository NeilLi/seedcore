#!/usr/bin/env python3
"""
Test Script for SeedCore Cognitive Service

This script tests all cognitive service endpoints to ensure they're working correctly.
Run this after starting the cognitive service to verify functionality.
"""

import requests
import json
import time
import sys
from typing import Dict, Any, Optional

# Configuration
# Try to detect the correct base URL based on environment
import os

# Check if we're in a Kubernetes pod environment
if os.getenv("KUBERNETES_SERVICE_HOST") or os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token"):
    # We're in a K8s pod - try to connect to the cognitive service
    if os.getenv("SEEDCORE_NS") == "seedcore-dev":
        # We're in the seedcore namespace - connect to Ray Serve endpoint
        # The cognitive service is running on Ray head node via Ray Serve
        BASE_URL = os.getenv("RAY_SERVE_UR", "http://seedcore-svc-stable-svc:8000")   # Use RAY_SERVE_URL from env.example
    else:
        BASE_URL = "http://localhost:8000"  # Fallback to localhost
else:
    # We're running locally or from host
    BASE_URL = "http://localhost:8000"  # Default to localhost

ROUTE_PREFIX = "/cognitive"
TIMEOUT = 30  # seconds

# Colors for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_status(status: str, message: str):
    """Print colored status messages."""
    color_map = {
        "OK": Colors.GREEN,
        "ERROR": Colors.RED,
        "WARN": Colors.YELLOW,
        "INFO": Colors.BLUE
    }
    color = color_map.get(status, Colors.END)
    print(f"{color}{status}:{Colors.END} {message}")

def test_endpoint(method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, expected_status: int = 200) -> bool:
    """Test a single endpoint and return success status."""
    url = f"{BASE_URL}{ROUTE_PREFIX}{endpoint}"
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=TIMEOUT)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, timeout=TIMEOUT)
        else:
            print_status("ERROR", f"Unsupported method: {method}")
            return False
        
        if response.status_code == expected_status:
            print_status("OK", f"{method} {endpoint} - Status: {response.status_code}")
            try:
                result = response.json()
                if "result" in result and result.get("success", False):
                    print_status("OK", f"  Response indicates success")
                elif "status" in result and result.get("status") == "healthy":
                    print_status("OK", f"  Health check passed")
                elif endpoint == "/" and "status" in result and result.get("status") == "healthy":
                    print_status("OK", f"  Root endpoint healthy")
                else:
                    print_status("WARN", f"  Response: {json.dumps(result, indent=2)}")
            except json.JSONDecodeError:
                print_status("WARN", f"  Non-JSON response: {response.text[:200]}")
            return True
        else:
            print_status("ERROR", f"{method} {endpoint} - Expected {expected_status}, got {response.status_code}")
            print_status("ERROR", f"  Response: {response.text[:200]}")
            return False
            
    except requests.exceptions.ConnectionError:
        print_status("ERROR", f"Cannot connect to {url}")
        print_status("INFO", "Make sure the cognitive service is running and accessible")
        return False
    except requests.exceptions.Timeout:
        print_status("ERROR", f"Request to {endpoint} timed out after {TIMEOUT}s")
        return False
    except Exception as e:
        print_status("ERROR", f"Unexpected error testing {endpoint}: {e}")
        return False

def test_health_endpoints():
    """Test health and root endpoints."""
    print(f"\n{Colors.BOLD}🔍 Testing Health Endpoints{Colors.END}")
    
    success_count = 0
    total_count = 3  # Updated to include /info endpoint
    
    # Test health endpoint
    if test_endpoint("GET", "/health"):
        success_count += 1
    
    # Test root endpoint
    if test_endpoint("GET", "/"):
        success_count += 1
    
    # Test info endpoint
    if test_endpoint("GET", "/info"):
        success_count += 1
    
    return success_count, total_count

def test_cognitive_endpoints():
    """Test all cognitive reasoning endpoints."""
    print(f"\n{Colors.BOLD}🧠 Testing Cognitive Endpoints{Colors.END}")
    
    # Test data for cognitive endpoints
    test_data = {
        "agent_id": "test-agent-001",
        "incident_context": {"error": "test error", "timestamp": time.time()},
        "task_description": "Test task for validation",
        "decision_context": {"options": ["A", "B", "C"], "criteria": "test"},
        "historical_data": {"previous_decisions": ["A", "B"], "success_rate": 0.8},
        "problem_statement": "Test problem for validation",
        "constraints": {"time_limit": 60, "resources": "limited"},
        "available_tools": {"tool1": "description", "tool2": "description"},
        "memory_fragments": ["fragment1", "fragment2", "fragment3"],
        "synthesis_goal": "Test synthesis goal",
        "performance_data": {"accuracy": 0.95, "latency": 100},
        "current_capabilities": {"capability1": 0.7, "capability2": 0.8},
        "target_capabilities": {"capability1": 0.9, "capability2": 0.95}
    }
    
    endpoints = [
        ("POST", "/reason-about-failure", {"agent_id": test_data["agent_id"], "incident_context": test_data["incident_context"]}),
        ("POST", "/plan-task", {"agent_id": test_data["agent_id"], "task_description": test_data["task_description"], "current_capabilities": test_data["current_capabilities"], "available_tools": test_data["available_tools"]}),
        ("POST", "/make-decision", {"agent_id": test_data["agent_id"], "decision_context": test_data["decision_context"], "historical_data": test_data["historical_data"]}),
        ("POST", "/solve-problem", {"agent_id": test_data["agent_id"], "problem_statement": test_data["problem_statement"], "constraints": test_data["constraints"], "available_tools": test_data["available_tools"]}),
        ("POST", "/synthesize-memory", {"agent_id": test_data["agent_id"], "memory_fragments": test_data["memory_fragments"], "synthesis_goal": test_data["synthesis_goal"]}),
        ("POST", "/assess-capabilities", {"agent_id": test_data["agent_id"], "performance_data": test_data["performance_data"], "current_capabilities": test_data["current_capabilities"], "target_capabilities": test_data["target_capabilities"]})
    ]
    
    success_count = 0
    total_count = len(endpoints)
    
    for method, endpoint, data in endpoints:
        if test_endpoint(method, endpoint, data):
            success_count += 1
    
    return success_count, total_count

def test_error_handling():
    """Test error handling with invalid requests."""
    print(f"\n{Colors.BOLD}⚠️  Testing Error Handling{Colors.END}")
    
    success_count = 0
    total_count = 2
    
    # Test with missing required fields
    invalid_data = {"incident_context": {}} # This is correct, agent_id is missing
    
    # Test with invalid data
    if test_endpoint("POST", "/reason-about-failure", invalid_data, expected_status=422):
        success_count += 1
    
    # Test with completely invalid data
    if test_endpoint("POST", "/plan-task", {}, expected_status=422):
        success_count += 1
    
    return success_count, total_count

def test_service_info():
    """Display service information and configuration."""
    print(f"\n{Colors.BOLD}ℹ️  Service Information{Colors.END}")
    
    try:
        # First try the new /info endpoint for comprehensive metadata
        response = requests.get(f"{BASE_URL}{ROUTE_PREFIX}/info", timeout=TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            print(f"Service: {data.get('service', 'Unknown')}")
            print(f"Route Prefix: {data.get('route_prefix', 'Unknown')}")
            print(f"Ray Namespace: {data.get('ray_namespace', 'Unknown')}")
            print(f"Ray Address: {data.get('ray_address', 'Unknown')}")
            
            if "deployment" in data:
                deployment = data["deployment"]
                print(f"Deployment: {deployment.get('name', 'Unknown')}")
                print(f"Replicas: {deployment.get('replicas', 'Unknown')}")
                print(f"Max Requests: {deployment.get('max_ongoing_requests', 'Unknown')}")
            
            if "resources" in data:
                resources = data["resources"]
                print(f"CPU Allocation: {resources.get('num_cpus', 'Unknown')}")
                print(f"GPU Allocation: {resources.get('num_gpus', 'Unknown')}")
                print(f"Resource Pinning: {resources.get('pinned_to', 'Unknown')}")
            
            if "endpoints" in data:
                print(f"\nAvailable Endpoints:")
                for endpoint_type, endpoints in data["endpoints"].items():
                    if isinstance(endpoints, list):
                        for endpoint in endpoints:
                            print(f"  {endpoint}")
                    else:
                        print(f"  {endpoints}")
        else:
            # Fallback to health endpoint if /info is not available
            print_status("WARN", f"/info endpoint returned {response.status_code}, falling back to /health")
            response = requests.get(f"{BASE_URL}{ROUTE_PREFIX}/health", timeout=TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                print(f"Service: {data.get('service', 'Unknown')}")
                print(f"Status: {data.get('status', 'Unknown')}")
                print(f"Route Prefix: {data.get('route_prefix', 'Unknown')}")
                
                if "endpoints" in data:
                    print(f"\nAvailable Endpoints:")
                    for endpoint_type, endpoints in data["endpoints"].items():
                        if isinstance(endpoints, list):
                            for endpoint in endpoints:
                                print(f"  {endpoint}")
                        else:
                            print(f"  {endpoints}")
            else:
                print_status("ERROR", f"Could not retrieve service info: {response.status_code}")
            
    except Exception as e:
        print_status("ERROR", f"Failed to get service info: {e}")

def main():
    """Main test function."""
    print(f"{Colors.BOLD}🚀 SeedCore Cognitive Service Test Suite{Colors.END}")
    print(f"Testing service at: {BASE_URL}{ROUTE_PREFIX}")
    print(f"Timeout: {TIMEOUT} seconds")
    
    # Display test configuration
    print(f"\n{Colors.BOLD}⚙️  Test Configuration{Colors.END}")
    print(f"Base URL: {BASE_URL}")
    print(f"Route Prefix: {ROUTE_PREFIX}")
    print(f"Full Service URL: {BASE_URL}{ROUTE_PREFIX}")
    print(f"Environment: {'Kubernetes Pod' if os.getenv('KUBERNETES_SERVICE_HOST') else 'Local/Host'}")
    if os.getenv("SEEDCORE_NS"):
        print(f"Namespace: {os.getenv('SEEDCORE_NS')}")
    if os.getenv("HOSTNAME"):
        print(f"Hostname: {os.getenv('HOSTNAME')}")
    
    # Check if service is accessible
    print_status("INFO", f"Testing connection to: {BASE_URL}{ROUTE_PREFIX}")
    
    try:
        response = requests.get(f"{BASE_URL}{ROUTE_PREFIX}/health", timeout=5)
        if response.status_code == 200:
            print_status("OK", "Service is accessible")
        else:
            print_status("WARN", f"Service responded with status {response.status_code}")
    except requests.exceptions.ConnectionError:
        print_status("ERROR", "Cannot connect to cognitive service")
        print_status("INFO", "Current test configuration:")
        print_status("INFO", f"  - Base URL: {BASE_URL}")
        print_status("INFO", f"  - Route Prefix: {ROUTE_PREFIX}")
        print_status("INFO", f"  - Full URL: {BASE_URL}{ROUTE_PREFIX}")
        
        if "seedcore-svc-stable-svc" in BASE_URL:
            print_status("INFO", "You're testing from a K8s pod - make sure:")
            print_status("INFO", "  1. The cognitive service is deployed on Ray head node via Ray Serve")
            print_status("INFO", "  2. Ray Serve is running and accessible at seedcore-svc-stable-svc:8000")
            print_status("INFO", "  3. Check Ray Serve status: kubectl exec -it <ray-head-pod> -- ray status")
        elif "seedcore-api" in BASE_URL:
            print_status("INFO", "You're testing from seedcore-api pod - make sure:")
            print_status("INFO", "  1. The cognitive service is deployed on Ray head node via Ray Serve")
            print_status("INFO", "  2. Ray Serve is accessible at seedcore-svc-stable-svc:8000")
        else:
            print_status("INFO", "You're testing from localhost - make sure:")
            print_status("INFO", "  1. Port forwarding is set up: kubectl port-forward svc/seedcore-svc-stable-svc 8000:8000")
            print_status("INFO", "  2. The cognitive service is deployed and running on Ray head node")
        
        return
    
    total_success = 0
    total_tests = 0
    
    # Run all tests
    success, count = test_health_endpoints()
    total_success += success
    total_tests += count
    
    success, count = test_cognitive_endpoints()
    total_success += success
    total_tests += count
    
    success, count = test_error_handling()
    total_success += success
    total_tests += count
    
    # Display service information
    test_service_info()
    
    # Summary
    print(f"\n{Colors.BOLD}📊 Test Summary{Colors.END}")
    print(f"Tests Passed: {total_success}/{total_tests}")
    success_rate = (total_success / total_tests * 100) if total_tests > 0 else 0
    
    if success_rate >= 90:
        print_status("OK", f"Success Rate: {success_rate:.1f}% - Excellent!")
    elif success_rate >= 70:
        print_status("WARN", f"Success Rate: {success_rate:.1f}% - Good, but some issues")
    else:
        print_status("ERROR", f"Success Rate: {success_rate:.1f}% - Multiple issues detected")
    
    if total_success == total_tests:
        print(f"\n{Colors.GREEN}🎉 All tests passed! Cognitive service is working correctly.{Colors.END}")
    else:
        print(f"\n{Colors.YELLOW}⚠️  Some tests failed. Check the output above for details.{Colors.END}")

if __name__ == "__main__":
    main()
