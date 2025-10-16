#!/usr/bin/env python3
"""
Test script for Eventizer integration.

This script demonstrates the deterministic eventizer pipeline
and its integration with task creation and routing.
"""

import asyncio
import json
import sys
import os
import pytest

# Import mocks first
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mock_eventizer_dependencies import MockEventizerService

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.eventizer import EventizerRequest, EventizerConfig


async def test_eventizer_basic():
    """Test basic eventizer functionality."""
    print("🧪 Testing Eventizer Service - Basic Functionality")
    print("=" * 60)
    
    # Create eventizer service with configuration
    config = EventizerConfig(
        enable_regex=True,
        enable_keyword=True,
        enable_entity=True,
        enable_pii_redaction=True,
        pattern_files=["../config/eventizer_patterns.json"]
    )
    
    eventizer = MockEventizerService(config)
    await eventizer.initialize()
    
    # Test cases
    test_cases = [
        {
            "name": "HVAC Temperature Issue",
            "text": "The temperature in room 205 is too high at 85°F, HVAC system needs adjustment",
            "expected_types": ["hvac"]
        },
        {
            "name": "Security Alert",
            "text": "Security breach detected in building A, unauthorized access to server room",
            "expected_types": ["security"]
        },
        {
            "name": "Emergency Situation",
            "text": "Emergency! Fire alarm activated on floor 3, immediate evacuation required",
            "expected_types": ["emergency"]
        },
        {
            "name": "VIP Visit",
            "text": "VIP executive visit scheduled for tomorrow, prepare conference room 101",
            "expected_types": ["vip"]
        },
        {
            "name": "Maintenance Request",
            "text": "Elevator maintenance needed, service call scheduled for next week",
            "expected_types": ["maintenance"]
        },
        {
            "name": "Allergen Alert",
            "text": "Peanut allergen detected in cafeteria food, immediate alert required",
            "expected_types": ["allergen"]
        },
        {
            "name": "Mixed Event Types",
            "text": "Emergency HVAC failure in server room, temperature critical at 95°F, security alert",
            "expected_types": ["emergency", "hvac", "security"]
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. {test_case['name']}")
        print(f"   Text: {test_case['text']}")
        
        # Create eventizer request
        request = EventizerRequest(
            text=test_case["text"],
            task_type="general_query",
            domain="facilities",
            preserve_pii=False,
            include_metadata=True
        )
        
        # Process through eventizer
        response = await eventizer.process_text(request)
        
        # Display results
        print(f"   Processing Time: {response.processing_time_ms:.2f} ms")
        print(f"   Patterns Applied: {response.patterns_applied}")
        print(f"   PII Redacted: {response.pii_redacted}")
        print(f"   Overall Confidence: {response.confidence.overall_confidence:.3f}")
        print(f"   Needs ML Fallback: {response.confidence.needs_ml_fallback}")
        
        # Check event types
        detected_types = [et.lower() for et in response.event_tags.event_types]
        print(f"   Detected Event Types: {detected_types}")
        
        # Check if expected types were detected
        expected_types = [et.lower() for et in test_case["expected_types"]]
        matches = any(et in detected_types for et in expected_types)
        print(f"   Expected Types Match: {'✅' if matches else '❌'}")
        
        # Display attributes
        if response.attributes.target_organ:
            print(f"   Suggested Organ: {response.attributes.target_organ}")
        if response.attributes.required_service:
            print(f"   Required Service: {response.attributes.required_service}")
        if response.attributes.required_skill:
            print(f"   Required Skill: {response.attributes.required_skill}")
        
        # Display priority and urgency
        print(f"   Priority: {response.event_tags.priority}/10")
        print(f"   Urgency: {response.event_tags.urgency}")
        
        # Display warnings/errors
        if response.warnings:
            print(f"   Warnings: {', '.join(response.warnings)}")
        if response.errors:
            print(f"   Errors: {', '.join(response.errors)}")


async def test_eventizer_pii_redaction():
    """Test PII redaction functionality."""
    print("\n\n🔒 Testing Eventizer Service - PII Redaction")
    print("=" * 60)
    
    config = EventizerConfig(
        enable_pii_redaction=True,
        pii_redaction_entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]
    )
    
    eventizer = MockEventizerService(config)
    await eventizer.initialize()
    
    pii_test_cases = [
        {
            "name": "Email and Phone",
            "text": "Contact John Doe at john.doe@company.com or call (555) 123-4567 for HVAC issues",
            "should_redact": True
        },
        {
            "name": "No PII",
            "text": "The temperature in the building is too high",
            "should_redact": False
        }
    ]
    
    for i, test_case in enumerate(pii_test_cases, 1):
        print(f"\n{i}. {test_case['name']}")
        print(f"   Original: {test_case['text']}")
        
        request = EventizerRequest(
            text=test_case["text"],
            preserve_pii=True  # Keep redacted text for comparison
        )
        
        response = await eventizer.process_text(request)
        
        print(f"   Processed: {response.processed_text}")
        if response.pii_redacted_text:
            print(f"   PII Redacted: {response.pii_redacted_text}")
        
        print(f"   PII Redacted: {'✅' if response.pii_redacted else '❌'}")
        print(f"   Expected: {'✅' if test_case['should_redact'] else '❌'}")


async def test_eventizer_integration():
    """Test eventizer integration with task creation simulation."""
    print("\n\n🔗 Testing Eventizer Integration - Task Creation Simulation")
    print("=" * 60)
    
    config = EventizerConfig(
        pattern_files=["../config/eventizer_patterns.json"]
    )
    
    eventizer = MockEventizerService(config)
    await eventizer.initialize()
    
    # Simulate task creation payload
    task_payloads = [
        {
            "type": "general_query",
            "description": "HVAC system in conference room 201 is not cooling properly, temperature is 80°F",
            "domain": "facilities",
            "params": {"query": "hvac issue"}
        },
        {
            "type": "security_alert",
            "description": "Unauthorized access detected in server room at 2:30 AM, security breach alert",
            "domain": "security",
            "params": {"alert_type": "intrusion"}
        },
        {
            "type": "emergency_response",
            "description": "Fire alarm activated on floor 5, immediate evacuation required",
            "domain": "emergency",
            "params": {"priority": "critical"}
        }
    ]
    
    for i, payload in enumerate(task_payloads, 1):
        print(f"\n{i}. Task Creation Simulation")
        print(f"   Type: {payload['type']}")
        print(f"   Description: {payload['description']}")
        print(f"   Domain: {payload['domain']}")
        
        # Simulate eventizer processing (as done in create_task)
        if payload["description"].strip():
            request = EventizerRequest(
                text=payload["description"],
                task_type=payload["type"],
                domain=payload["domain"],
                preserve_pii=False,
                include_metadata=True
            )
            
            response = await eventizer.process_text(request)
            
            # Simulate enriched params (as done in create_task)
            enriched_params = dict(payload["params"])
            enriched_params.update({
                "event_tags": response.event_tags.model_dump(),
                "attributes": response.attributes.model_dump(),
                "confidence": response.confidence.model_dump(),
                "needs_ml_fallback": response.confidence.needs_ml_fallback,
                "eventizer_metadata": {
                    "processing_time_ms": response.processing_time_ms,
                    "patterns_applied": response.patterns_applied,
                    "pii_redacted": response.pii_redacted
                }
            })
            
            print(f"   Enriched Params:")
            print(f"     - Event Types: {[et.lower() for et in response.event_tags.event_types]}")
            print(f"     - Target Organ: {response.attributes.target_organ}")
            print(f"     - Required Service: {response.attributes.required_service}")
            print(f"     - Priority: {response.event_tags.priority}/10")
            print(f"     - Urgency: {response.event_tags.urgency}")
            print(f"     - Confidence: {response.confidence.overall_confidence:.3f}")
            print(f"     - ML Fallback: {response.confidence.needs_ml_fallback}")
            
            # Simulate routing decision
            if response.attributes.target_organ:
                print(f"   🎯 Routing Decision: Would route to {response.attributes.target_organ}")
            elif response.event_tags.event_types:
                event_type = response.event_tags.event_types[0].lower()
                if event_type == "hvac":
                    print(f"   🌡️ Routing Decision: Would route to hvac_organ")
                elif event_type == "security":
                    print(f"   🔒 Routing Decision: Would route to security_organ")
                elif event_type == "emergency":
                    print(f"   🚨 Routing Decision: Would route to emergency_organ")
                else:
                    print(f"   📋 Routing Decision: Would use default routing")
            else:
                print(f"   📋 Routing Decision: Would use default routing")


@pytest.mark.asyncio
async def test_eventizer_suite():
    """Run all eventizer tests as a single pytest test."""
    print("🚀 Eventizer Integration Test Suite")
    print("=" * 60)
    
    await test_eventizer_basic()
    await test_eventizer_pii_redaction()
    await test_eventizer_integration()
    
    print("\n\n✅ All tests completed successfully!")


if __name__ == "__main__":
    # For standalone execution
    asyncio.run(test_eventizer_suite())
