#!/usr/bin/env python3
"""
Test script for EventizerServiceClient

This script demonstrates how to use the EventizerServiceClient to interact
with the eventizer service deployed under the /ops application.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.serve.eventizer_client import EventizerServiceClient

async def test_eventizer_client():
    """Test the EventizerServiceClient with various scenarios."""
    
    print("🚀 Testing EventizerServiceClient...")
    
    # Initialize client
    client = EventizerServiceClient()
    print(f"✅ Client initialized with base URL: {client.base_url}")
    
    try:
        # Test 1: Health check
        print("\n📊 Test 1: Health Check")
        health = await client.health_check()
        print(f"Health status: {health}")
        
        # Test 2: Basic text processing
        print("\n📊 Test 2: Basic Text Processing")
        text = "Emergency alert: Fire detected in room 1510"
        result = await client.process_text(text)
        print(f"Processed text: {text}")
        print(f"Result: {result}")
        
        # Test 3: Emergency classification
        print("\n📊 Test 3: Emergency Classification")
        emergency_result = await client.classify_emergency("URGENT: Building evacuation required")
        print(f"Emergency classification: {emergency_result}")
        
        # Test 4: Security classification
        print("\n📊 Test 4: Security Classification")
        security_result = await client.classify_security("Unauthorized access detected in server room")
        print(f"Security classification: {security_result}")
        
        # Test 5: Tag extraction
        print("\n📊 Test 5: Tag Extraction")
        tags = await client.extract_tags("Temperature sensor reading 85°F in conference room A")
        print(f"Extracted tags: {tags}")
        
        # Test 6: PKG hints
        print("\n📊 Test 6: PKG Policy Hints")
        pkg_hints = await client.get_pkg_hints("HVAC system malfunction in data center")
        print(f"PKG hints: {pkg_hints}")
        
        # Test 7: Batch processing
        print("\n📊 Test 7: Batch Processing")
        batch_texts = [
            "Normal operation status",
            "Warning: High CPU usage detected",
            "Critical: Database connection failed"
        ]
        batch_results = await client.process_batch(batch_texts)
        print(f"Batch processing results: {len(batch_results)} items")
        for i, result in enumerate(batch_results):
            print(f"  Item {i+1}: {result.get('tags', {}).get('priority', 'unknown')} priority")
        
        # Test 8: Configuration validation
        print("\n📊 Test 8: Configuration Validation")
        config = await client.validate_config()
        print(f"Configuration validation: {config}")
        
        print("\n✅ All tests completed successfully!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

async def test_service_registry():
    """Test the service client registry."""
    print("\n🔧 Testing Service Client Registry...")
    
    try:
        from seedcore.serve import get_service_client, get_all_service_clients
        
        # Test individual client retrieval
        eventizer_client = get_service_client("eventizer")
        print(f"✅ Retrieved eventizer client: {type(eventizer_client).__name__}")
        
        # Test health check through registry
        health = await eventizer_client.health_check()
        print(f"✅ Registry client health: {health}")
        
        # Test all clients retrieval
        all_clients = get_all_service_clients()
        print(f"✅ Retrieved all clients: {list(all_clients.keys())}")
        
    except Exception as e:
        print(f"❌ Registry test failed: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main test runner."""
    print("🧪 EventizerServiceClient Integration Tests")
    print("=" * 50)
    
    # Run async tests
    asyncio.run(test_eventizer_client())
    asyncio.run(test_service_registry())
    
    print("\n🎉 All integration tests completed!")

if __name__ == "__main__":
    main()
