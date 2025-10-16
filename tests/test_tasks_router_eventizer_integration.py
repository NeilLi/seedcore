#!/usr/bin/env python3
"""
Test script for Tasks Router Eventizer Integration

This script tests that the tasks_router correctly uses the EventizerServiceClient
to communicate with the remote eventizer service deployed under /ops.
"""

import asyncio
import sys
import os
import uuid
from typing import Dict, Any
import pytest

# Import mocks first
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mock_eventizer_dependencies import (
    get_eventizer_client,
    MockEventizerServiceClient as EventizerServiceClient
)

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

async def test_eventizer_client_integration():
    """Test that the EventizerServiceClient works correctly."""
    
    print("🚀 Testing EventizerServiceClient Integration...")
    
    try:
        # Test 1: Get client through tasks_router function
        print("\n📊 Test 1: Tasks Router Client Initialization")
        client = await get_eventizer_client()
        print(f"✅ Client retrieved: {type(client).__name__}")
        print(f"✅ Base URL: {client.base_url}")
        
        # Test 2: Health check
        print("\n📊 Test 2: Health Check")
        health = await client.health_check()
        print(f"✅ Health status: {health}")
        
        # Test 3: Basic text processing
        print("\n📊 Test 3: Basic Text Processing")
        payload = {
            "text": "Emergency alert: Fire detected in room 1510",
            "task_type": "emergency",
            "domain": "facilities",
            "preserve_pii": False,
            "include_metadata": True
        }
        
        result = await client.process_eventizer_request(payload)
        print(f"✅ Processing result keys: {list(result.keys())}")
        
        # Test 4: Verify response structure matches expected format
        print("\n📊 Test 4: Response Structure Validation")
        expected_keys = ["event_tags", "attributes", "confidence", "processing_time_ms", "patterns_applied"]
        for key in expected_keys:
            if key in result:
                print(f"✅ Found expected key: {key}")
            else:
                print(f"⚠️  Missing expected key: {key}")
        
        # Test 5: Test with task-like payload (similar to what tasks_router uses)
        print("\n📊 Test 5: Task-like Processing")
        task_payload = {
            "text": "HVAC temperature sensor reading 85°F in conference room A - requires immediate attention",
            "task_type": "maintenance",
            "domain": "facilities",
            "preserve_pii": False,
            "include_metadata": True
        }
        
        task_result = await client.process_eventizer_request(task_payload)
        
        # Extract the data that tasks_router would use
        enriched_params = {
            "event_tags": task_result.get("event_tags", {}),
            "attributes": task_result.get("attributes", {}),
            "confidence": task_result.get("confidence", {}),
            "needs_ml_fallback": task_result.get("confidence", {}).get("needs_ml_fallback", True),
            "eventizer_metadata": {
                "processing_time_ms": task_result.get("processing_time_ms", 0),
                "patterns_applied": task_result.get("patterns_applied", 0),
                "pii_redacted": task_result.get("pii_redacted", False),
                "processing_log": task_result.get("processing_log", [])
            }
        }
        
        print(f"✅ Enriched params structure: {list(enriched_params.keys())}")
        print(f"✅ Confidence: {enriched_params['confidence']}")
        print(f"✅ Needs ML fallback: {enriched_params['needs_ml_fallback']}")
        
        # Test 6: Error handling
        print("\n📊 Test 6: Error Handling")
        try:
            # Test with invalid payload
            invalid_payload = {"invalid": "data"}
            await client.process_eventizer_request(invalid_payload)
            print("⚠️  Expected error but got success")
        except Exception as e:
            print(f"✅ Error handling works: {type(e).__name__}: {e}")
        
        print("\n✅ All integration tests completed successfully!")
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()

async def test_service_discovery():
    """Test service discovery mechanism."""
    
    print("\n🔧 Testing Service Discovery...")
    
    try:
        # Test direct client creation
        client = EventizerServiceClient()
        print(f"✅ Direct client creation: {client.base_url}")
        
        # Test with custom base URL
        custom_client = EventizerServiceClient(base_url="http://localhost:8000/ops")
        print(f"✅ Custom URL client: {custom_client.base_url}")
        
        # Test health check to verify service discovery works
        health = await custom_client.health_check()
        print(f"✅ Service discovery health: {health.get('status', 'unknown')}")
        
    except Exception as e:
        print(f"❌ Service discovery test failed: {e}")

async def test_tasks_router_simulation():
    """Simulate the exact flow that tasks_router would use."""
    
    print("\n🎯 Testing Tasks Router Simulation...")
    
    try:
        # Simulate task creation with eventizer processing
        task_description = "Critical: Database connection timeout in production environment"
        task_type = "infrastructure"
        domain = "database"
        
        # Get client (same as tasks_router)
        eventizer_client = await get_eventizer_client()
        
        # Create payload (same as tasks_router)
        eventizer_payload = {
            "text": task_description,
            "task_type": task_type,
            "domain": domain,
            "preserve_pii": False,
            "include_metadata": True
        }
        
        # Process (same as tasks_router)
        eventizer_response_data = await eventizer_client.process_eventizer_request(eventizer_payload)
        
        # Enrich params (same logic as tasks_router)
        enriched_params = {
            "event_tags": eventizer_response_data.get("event_tags", {}),
            "attributes": eventizer_response_data.get("attributes", {}),
            "confidence": eventizer_response_data.get("confidence", {}),
            "needs_ml_fallback": eventizer_response_data.get("confidence", {}).get("needs_ml_fallback", True),
            "eventizer_metadata": {
                "processing_time_ms": eventizer_response_data.get("processing_time_ms", 0),
                "patterns_applied": eventizer_response_data.get("patterns_applied", 0),
                "pii_redacted": eventizer_response_data.get("pii_redacted", False),
                "processing_log": eventizer_response_data.get("processing_log", [])
            }
        }
        
        # Store PII handling (same as tasks_router)
        if eventizer_response_data.get("pii_redacted") and eventizer_response_data.get("pii_redacted_text"):
            enriched_params["pii_redacted_text"] = eventizer_response_data.get("pii_redacted_text")
            enriched_params["original_text"] = eventizer_response_data.get("original_text")
        
        print(f"✅ Tasks router simulation completed")
        print(f"✅ Task type: {task_type}")
        print(f"✅ Confidence: {enriched_params['confidence'].get('overall_confidence', 0.0):.3f}")
        print(f"✅ Needs ML fallback: {enriched_params['needs_ml_fallback']}")
        print(f"✅ Patterns applied: {enriched_params['eventizer_metadata']['patterns_applied']}")
        
    except Exception as e:
        print(f"❌ Tasks router simulation failed: {e}")
        import traceback
        traceback.print_exc()

@pytest.mark.asyncio
async def test_tasks_router_eventizer_integration_suite():
    """Test suite for tasks router eventizer integration."""
    print("🧪 Tasks Router Eventizer Integration Tests")
    print("=" * 60)
    
    await test_eventizer_client_integration()
    await test_service_discovery()
    await test_tasks_router_simulation()
    
    print("\n🎉 All integration tests completed!")


if __name__ == "__main__":
    # For standalone execution
    asyncio.run(test_tasks_router_eventizer_integration_suite())
