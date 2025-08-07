#!/usr/bin/env python3
"""
Test DSPy Status and Cognitive Core Functionality

This script tests the DSPy status endpoint and basic cognitive core functionality
to ensure everything is working correctly.
"""

import requests
import json
import time
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_dspy_status():
    """Test the DSPy status endpoint."""
    print("🔍 Testing DSPy Status Endpoint")
    print("=" * 40)
    
    try:
        # Test the status endpoint
        response = requests.get("http://localhost:8002/dspy/status", timeout=10)
        response.raise_for_status()
        
        status_data = response.json()
        print(f"✅ Status endpoint responded successfully")
        print(f"   Success: {status_data.get('success', False)}")
        print(f"   Cognitive Core Available: {status_data.get('cognitive_core_available', False)}")
        print(f"   Serve Client Available: {status_data.get('serve_client_available', False)}")
        print(f"   Supported Task Types: {len(status_data.get('supported_task_types', []))}")
        print(f"   Timestamp: {status_data.get('timestamp', 'N/A')}")
        
        return status_data
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to connect to status endpoint: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse JSON response: {e}")
        return None

def test_cognitive_core_direct():
    """Test cognitive core directly without Ray Serve."""
    print("\n🧠 Testing Cognitive Core Directly")
    print("=" * 40)
    
    try:
        from seedcore.agents.cognitive_core import (
            CognitiveCore, 
            CognitiveContext, 
            CognitiveTaskType,
            initialize_cognitive_core
        )
        
        # Initialize cognitive core
        print("🚀 Initializing cognitive core...")
        cognitive_core = initialize_cognitive_core()
        print("✅ Cognitive core initialized successfully")
        
        # Test a simple failure analysis
        print("🔍 Testing failure analysis...")
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={
                "incident_id": "test_001",
                "error_message": "Simple test error",
                "agent_state": {"capability_score": 0.5}
            }
        )
        
        result = cognitive_core(context)
        print("✅ Failure analysis completed successfully")
        print(f"   Success: {result.get('success', False)}")
        print(f"   Thought: {result.get('thought', 'N/A')[:50]}...")
        print(f"   Confidence: {result.get('confidence_score', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Cognitive core test failed: {e}")
        return False

def test_api_endpoints():
    """Test the DSPy API endpoints."""
    print("\n🌐 Testing DSPy API Endpoints")
    print("=" * 40)
    
    base_url = "http://localhost:8002"
    endpoints = [
        "/dspy/reason-about-failure",
        "/dspy/plan-task", 
        "/dspy/make-decision",
        "/dspy/solve-problem",
        "/dspy/synthesize-memory",
        "/dspy/assess-capabilities"
    ]
    
    for endpoint in endpoints:
        try:
            # Test with a simple POST request
            test_data = {
                "agent_id": "test_agent",
                "task_description": "Test task" if "plan-task" in endpoint else None,
                "incident_id": "test_001" if "reason-about-failure" in endpoint else None,
                "decision_context": {"test": "data"} if "make-decision" in endpoint else None,
                "problem_statement": "Test problem" if "solve-problem" in endpoint else None,
                "memory_fragments": [{"test": "data"}] if "synthesize-memory" in endpoint else None,
                "performance_data": {"test": "data"} if "assess-capabilities" in endpoint else None
            }
            
            # Remove None values
            test_data = {k: v for k, v in test_data.items() if v is not None}
            
            response = requests.post(f"{base_url}{endpoint}", json=test_data, timeout=30)
            
            if response.status_code == 200:
                print(f"✅ {endpoint} - Working")
            else:
                print(f"⚠️ {endpoint} - Status {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"❌ {endpoint} - Connection failed: {e}")
        except Exception as e:
            print(f"❌ {endpoint} - Error: {e}")

def main():
    """Main test function."""
    print("🧪 DSPy Status and Functionality Test")
    print("=" * 50)
    
    # Test 1: Status endpoint
    status_data = test_dspy_status()
    
    # Test 2: Direct cognitive core
    core_working = test_cognitive_core_direct()
    
    # Test 3: API endpoints (only if core is working)
    if core_working:
        test_api_endpoints()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Summary")
    print("=" * 50)
    
    if status_data:
        print(f"✅ Status Endpoint: Working")
        print(f"   Cognitive Core Available: {status_data.get('cognitive_core_available', False)}")
        print(f"   Serve Client Available: {status_data.get('serve_client_available', False)}")
    else:
        print(f"❌ Status Endpoint: Failed")
    
    print(f"✅ Direct Cognitive Core: {'Working' if core_working else 'Failed'}")
    
    print("\n🔧 Recommendations:")
    if not status_data or not status_data.get('cognitive_core_available', False):
        print("1. Check if the API server is running")
        print("2. Verify OPENAI_API_KEY is set")
        print("3. Check server logs for errors")
    
    if not status_data or not status_data.get('serve_client_available', False):
        print("4. Ray Serve client is not available (expected for simple setup)")
        print("5. Use direct cognitive core instead of Ray Serve")
    
    print("\n🎯 Next Steps:")
    print("1. Run: python examples/simple_dspy_example.py")
    print("2. Check the API documentation at http://localhost:8002/docs")
    print("3. Monitor logs for any issues")

if __name__ == "__main__":
    main()
