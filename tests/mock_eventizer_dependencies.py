#!/usr/bin/env python3
"""
Mock Eventizer Dependencies for Testing

This module provides mock implementations of Eventizer services and clients
to allow tests to run without requiring a running Kubernetes pod or Ray cluster.
"""

import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock
import asyncio

# Mock EventizerService
class MockEventizerService:
    """Mock EventizerService that provides the expected interface."""
    
    def __init__(self, config=None):
        self.config = config or self._get_default_config()
        self.initialized = False
    
    def _get_default_config(self):
        """Get default mock config."""
        try:
            from seedcore.ops.eventizer import EventizerConfig
            return EventizerConfig()
        except:
            return MagicMock()
    
    async def initialize(self):
        """Mock initialize method."""
        self.initialized = True
    
    async def process_text(self, request):
        """Mock process_text method that returns a realistic response."""
        from datetime import datetime
        
        # Create mock response with realistic structure
        response = MagicMock()
        response.original_text = getattr(request, 'text', 'mock text')
        response.processed_text = getattr(request, 'text', 'mock text').lower()
        response.normalized_text = getattr(request, 'text', 'mock text').lower()
        response.processing_time_ms = 5.0
        response.patterns_applied = 3
        response.pii_redacted = False
        response.pii_redacted_text = None
        response.warnings = []
        response.errors = []
        response.processing_log = ["Mock processing complete"]
        
        # Event tags
        response.event_tags = MagicMock()
        response.event_tags.event_types = ["general"]
        response.event_tags.priority = 5
        response.event_tags.urgency = "normal"
        response.event_tags.model_dump = lambda: {
            "event_types": ["general"],
            "priority": 5,
            "urgency": "normal"
        }
        
        # Attributes
        response.attributes = MagicMock()
        response.attributes.target_organ = None
        response.attributes.required_service = None
        response.attributes.required_skill = None
        response.attributes.model_dump = lambda: {
            "target_organ": None,
            "required_service": None,
            "required_skill": None
        }
        
        # Confidence
        response.confidence = MagicMock()
        response.confidence.overall_confidence = 0.75
        response.confidence.needs_ml_fallback = False
        response.confidence.confidence_level = "medium"
        response.confidence.model_dump = lambda: {
            "overall_confidence": 0.75,
            "needs_ml_fallback": False,
            "confidence_level": "medium"
        }
        
        # Detect HVAC events
        text_lower = response.original_text.lower()
        if 'hvac' in text_lower or 'temperature' in text_lower or 'cooling' in text_lower:
            response.event_tags.event_types = ["hvac"]
            response.event_tags.priority = 7
            response.attributes.target_organ = "hvac_organ"
            response.attributes.required_service = "hvac"
            response.event_tags.model_dump = lambda: {
                "event_types": ["hvac"],
                "priority": 7,
                "urgency": "normal"
            }
        
        # Detect security events
        if 'security' in text_lower or 'unauthorized' in text_lower or 'breach' in text_lower:
            response.event_tags.event_types = ["security"]
            response.event_tags.priority = 9
            response.event_tags.urgency = "high"
            response.attributes.target_organ = "security_organ"
            response.attributes.required_service = "security"
            response.event_tags.model_dump = lambda: {
                "event_types": ["security"],
                "priority": 9,
                "urgency": "high"
            }
        
        # Detect emergency events
        if 'emergency' in text_lower or 'fire' in text_lower or 'evacuation' in text_lower:
            response.event_tags.event_types = ["emergency"]
            response.event_tags.priority = 10
            response.event_tags.urgency = "critical"
            response.attributes.target_organ = "emergency_organ"
            response.attributes.required_service = "emergency"
            response.event_tags.model_dump = lambda: {
                "event_types": ["emergency"],
                "priority": 10,
                "urgency": "critical"
            }
        
        # Detect VIP events
        if 'vip' in text_lower:
            response.event_tags.event_types = ["vip"]
            response.event_tags.priority = 8
        
        # Detect maintenance events
        if 'maintenance' in text_lower or 'elevator' in text_lower or 'service' in text_lower:
            response.event_tags.event_types = ["maintenance"]
            response.event_tags.priority = 6
        
        # Detect allergen events
        if 'allergen' in text_lower or 'peanut' in text_lower:
            response.event_tags.event_types = ["allergen"]
            response.event_tags.priority = 9
        
        return response
    
    async def health_check(self):
        """Mock health check."""
        return {"status": "healthy", "initialized": self.initialized}


class MockEventizerServiceClient:
    """Mock EventizerServiceClient for testing."""
    
    def __init__(self, base_url=None):
        self.base_url = base_url or "http://localhost:8000/ops"
        self._metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "fallback_count": 0,
            "failure_count": 0,
            "circuit_breaker_open": False,
            "cache_hit_rate": 0.0,
            "success_rate": 1.0,
            "average_latency_ms": 5.0,
            "cache_stats": {"size": 0, "max_size": 1000}
        }
    
    async def health_check(self):
        """Mock health check."""
        return {"status": "healthy", "service": "eventizer"}
    
    async def process_text(self, text):
        """Mock process_text method."""
        self._metrics["total_requests"] += 1
        self._metrics["successful_requests"] += 1
        
        return {
            "event_tags": {
                "event_types": ["general"],
                "priority": 5,
                "urgency": "normal"
            },
            "attributes": {
                "target_organ": None,
                "required_service": None,
                "required_skill": None
            },
            "confidence": {
                "overall_confidence": 0.75,
                "needs_ml_fallback": False
            },
            "processing_time_ms": 5.0,
            "patterns_applied": 3,
            "pii_redacted": False,
            "processing_log": ["Mock processing complete"]
        }
    
    async def classify_emergency(self, text):
        """Mock emergency classification."""
        return {"is_emergency": "emergency" in text.lower(), "confidence": 0.9}
    
    async def classify_security(self, text):
        """Mock security classification."""
        return {"is_security": "security" in text.lower(), "confidence": 0.9}
    
    async def extract_tags(self, text):
        """Mock tag extraction."""
        return {"tags": ["general"], "count": 1}
    
    async def get_pkg_hints(self, text):
        """Mock PKG hints."""
        return {"hints": [], "count": 0}
    
    async def process_batch(self, texts):
        """Mock batch processing."""
        results = []
        for text in texts:
            result = await self.process_text(text)
            results.append(result)
        return results
    
    async def validate_config(self):
        """Mock config validation."""
        return {"valid": True, "config": "mock_config"}
    
    async def process_eventizer_request(self, payload):
        """Mock eventizer request processing."""
        self._metrics["total_requests"] += 1
        self._metrics["successful_requests"] += 1
        
        text = payload.get("text", "")
        return {
            "event_tags": {
                "event_types": ["general"],
                "priority": 5,
                "urgency": "normal"
            },
            "attributes": {
                "target_organ": None,
                "required_service": None,
                "required_skill": None
            },
            "confidence": {
                "overall_confidence": 0.75,
                "needs_ml_fallback": False
            },
            "processing_time_ms": 5.0,
            "patterns_applied": 3,
            "pii_redacted": False,
            "processing_log": ["Mock processing complete"]
        }
    
    def get_metrics(self):
        """Get mock metrics."""
        return self._metrics
    
    async def close(self):
        """Mock close method."""
        pass


class MockFastEventizer:
    """Mock fast eventizer for performance testing."""
    
    def process_text(self, text):
        """Mock fast text processing."""
        return {
            "event_tags": {
                "event_types": ["general"],
                "priority": 5,
                "urgency": "normal"
            },
            "confidence": {
                "overall_confidence": 0.75,
                "needs_ml_fallback": False
            },
            "processing_time_ms": 0.5
        }


def get_fast_eventizer():
    """Get mock fast eventizer instance."""
    return MockFastEventizer()


def process_text_fast(text):
    """Mock fast text processing function."""
    eventizer = get_fast_eventizer()
    return eventizer.process_text(text)


async def get_eventizer_client():
    """Mock function to get eventizer client."""
    return MockEventizerServiceClient()


# Install mocks in sys.modules
sys.modules['seedcore.serve.eventizer_client'] = type('MockEventizerClientModule', (), {
    'EventizerServiceClient': MockEventizerServiceClient,
    'get_service_client': lambda name: MockEventizerServiceClient() if name == "eventizer" else None,
    'get_all_service_clients': lambda: {"eventizer": MockEventizerServiceClient()}
})()

sys.modules['seedcore.ops.eventizer.fast_eventizer'] = type('MockFastEventizerModule', (), {
    'get_fast_eventizer': get_fast_eventizer,
    'process_text_fast': process_text_fast
})()

# Mock the tasks router eventizer client getter
sys.modules['seedcore.api.routers.tasks_router'] = type('MockTasksRouterModule', (), {
    'get_eventizer_client': get_eventizer_client
})()

print("✅ Mock Eventizer dependencies loaded successfully")

