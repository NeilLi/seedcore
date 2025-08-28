#!/usr/bin/env python3
"""
Test script for enhanced integration between Ray Serve apps and detached actors.

This script tests:
1. CognitiveCore Serve deployment
2. OrganismManager integration with CognitiveCore
3. Fast path vs. escalation routing
4. Metrics collection
"""

import os
import sys
import time
import asyncio
import logging
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

async def test_cognitive_serve():
    """Test the CognitiveCore Serve deployment."""
    try:
        from seedcore.serve.cognitive_serve import CognitiveCoreServe, CognitiveCoreClient
        
        logger.info("🧪 Testing CognitiveCore Serve deployment...")
        
        # Test the client wrapper
        client = CognitiveCoreClient(deployment_name="cognitive", timeout_s=5.0)
        
        # Test health check
        is_healthy = client.is_healthy()
        logger.info(f"✅ CognitiveCore health check: {is_healthy}")
        
        # Test ping
        ping_result = await client.ping()
        logger.info(f"✅ CognitiveCore ping: {ping_result}")
        
        # Test solve_problem
        test_request = {
            "task_id": "test-123",
            "type": "general_query",
            "description": "Test task for integration testing",
            "constraints": {"latency_ms": 1000, "budget": 0.01},
            "context": {"drift_score": 0.8, "features": {"complexity": "high"}},
            "available_organs": ["memory", "graph", "retrieval", "executor"],
            "correlation_id": "test-correlation-123"
        }
        
        result = await client.solve_problem(**test_request)
        logger.info(f"✅ CognitiveCore solve_problem result: {result}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ CognitiveCore Serve test failed: {e}")
        return False

async def test_organism_manager_integration():
    """Test OrganismManager integration with CognitiveCore."""
    try:
        from seedcore.organs.organism_manager import OrganismManager
        
        logger.info("🧪 Testing OrganismManager integration...")
        
        # Create OrganismManager instance
        org_manager = OrganismManager()
        
        # Test configuration loading
        logger.info(f"✅ OrganismManager created with {len(org_manager.organ_configs)} organ configs")
        
        # Test cognitive client configuration
        logger.info(f"✅ Escalation timeout: {org_manager.escalation_timeout_s}s")
        logger.info(f"✅ Max inflight: {org_manager.escalation_max_inflight}")
        logger.info(f"✅ OCPS drift threshold: {org_manager.ocps_drift_threshold}")
        logger.info(f"✅ Fast path SLO: {org_manager.fast_path_latency_slo_ms}ms")
        logger.info(f"✅ Max plan steps: {org_manager.max_plan_steps}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ OrganismManager integration test failed: {e}")
        return False

async def test_routing_logic():
    """Test the enhanced routing logic."""
    try:
        from seedcore.organs.organism_manager import OrganismManager
        
        logger.info("🧪 Testing enhanced routing logic...")
        
        # Create OrganismManager instance
        org_manager = OrganismManager()
        
        # Test fallback plan generation
        test_task = {
            "type": "test_task",
            "description": "Test task for routing",
            "drift_score": 0.3
        }
        
        fallback_plan = org_manager._fallback_plan(test_task)
        logger.info(f"✅ Fallback plan generated: {fallback_plan}")
        
        # Test plan validation
        valid_plan = [
            {"organ_id": "memory", "task": {"op": "search", "args": {"query": "test"}}}
        ]
        
        invalid_plan = [
            {"organ_id": "unknown_organ", "task": {"op": "search"}}
        ]
        
        valid_result = org_manager._validate_or_fallback(valid_plan, test_task)
        invalid_result = org_manager._validate_or_fallback(invalid_plan, test_task)
        
        logger.info(f"✅ Valid plan validation: {valid_result}")
        logger.info(f"✅ Invalid plan validation: {invalid_result}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Routing logic test failed: {e}")
        return False

async def test_metrics_collection():
    """Test metrics collection functionality."""
    try:
        from seedcore.organs.organism_manager import OrganismManager
        
        logger.info("🧪 Testing metrics collection...")
        
        # Create OrganismManager instance
        org_manager = OrganismManager()
        
        # Test initial metrics
        initial_metrics = org_manager.get_metrics()
        logger.info(f"✅ Initial metrics: {initial_metrics}")
        
        # Test metrics tracking
        org_manager._track_metrics("fast", True, 150.0)
        org_manager._track_metrics("hgnn", True, 2500.0)
        org_manager._track_metrics("fast", False, 200.0)
        
        # Get updated metrics
        updated_metrics = org_manager.get_metrics()
        logger.info(f"✅ Updated metrics: {updated_metrics}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Metrics collection test failed: {e}")
        return False

async def test_environment_configuration():
    """Test environment variable configuration."""
    logger.info("🧪 Testing environment configuration...")
    
    # Test OCPS configuration
    ocps_drift_threshold = os.getenv("OCPS_DRIFT_THRESHOLD", "0.5")
    cognitive_timeout = os.getenv("COGNITIVE_TIMEOUT_S", "8.0")
    cognitive_max_inflight = os.getenv("COGNITIVE_MAX_INFLIGHT", "64")
    fast_path_slo = os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000")
    max_plan_steps = os.getenv("MAX_PLAN_STEPS", "16")
    
    logger.info(f"✅ OCPS_DRIFT_THRESHOLD: {ocps_drift_threshold}")
    logger.info(f"✅ COGNITIVE_TIMEOUT_S: {cognitive_timeout}")
    logger.info(f"✅ COGNITIVE_MAX_INFLIGHT: {cognitive_max_inflight}")
    logger.info(f"✅ FAST_PATH_LATENCY_SLO_MS: {fast_path_slo}")
    logger.info(f"✅ MAX_PLAN_STEPS: {max_plan_steps}")
    
    return True

async def main():
    """Run all integration tests."""
    logger.info("🚀 Starting enhanced integration tests...")
    
    tests = [
        ("Environment Configuration", test_environment_configuration),
        ("CognitiveCore Serve", test_cognitive_serve),
        ("OrganismManager Integration", test_organism_manager_integration),
        ("Routing Logic", test_routing_logic),
        ("Metrics Collection", test_metrics_collection),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"Running: {test_name}")
        logger.info(f"{'='*50}")
        
        try:
            start_time = time.time()
            success = await test_func()
            duration = time.time() - start_time
            
            results[test_name] = {
                "success": success,
                "duration": duration
            }
            
            if success:
                logger.info(f"✅ {test_name} PASSED ({duration:.2f}s)")
            else:
                logger.error(f"❌ {test_name} FAILED ({duration:.2f}s)")
                
        except Exception as e:
            logger.error(f"❌ {test_name} ERROR: {e}")
            results[test_name] = {
                "success": False,
                "duration": 0,
                "error": str(e)
            }
    
    # Summary
    logger.info(f"\n{'='*50}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*50}")
    
    passed = sum(1 for r in results.values() if r["success"])
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        duration = f"({result['duration']:.2f}s)" if result["duration"] > 0 else ""
        error = f" - {result['error']}" if "error" in result else ""
        logger.info(f"{status} {test_name} {duration}{error}")
    
    logger.info(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! Enhanced integration is working correctly.")
        return 0
    else:
        logger.error("💥 Some tests failed. Please check the logs above.")
        return 1

if __name__ == "__main__":
    # Set some test environment variables
    os.environ.setdefault("OCPS_DRIFT_THRESHOLD", "0.3")
    os.environ.setdefault("COGNITIVE_TIMEOUT_S", "5.0")
    os.environ.setdefault("COGNITIVE_MAX_INFLIGHT", "32")
    os.environ.setdefault("FAST_PATH_LATENCY_SLO_MS", "500")
    os.environ.setdefault("MAX_PLAN_STEPS", "8")
    
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
