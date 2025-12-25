#!/usr/bin/env python3
"""
Verification script for MLServiceClient intent compilation endpoints.

This script verifies:
  - get_intent_schema: Retrieving function schemas (all, by domain, by function name)
  - compile_intent: Compiling natural language text into structured function calls

Usage:
    python scripts/verify_intent_compilation.py
"""

import os
import sys
import json
import time
import traceback
from pathlib import Path
from typing import Any, List

import anyio  # pyright: ignore[reportMissingImports]
import logging

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


def _pretty(obj: Any) -> str:
    """Pretty print JSON objects."""
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)


def _infer_execution_path(result: dict) -> str:
    """
    Determine which execution path was used based on diagnostics.
    
    Returns:
        "MODEL_INFERENCE" if model was used
        "FALLBACK_HEURISTIC" if fallback was used
    """
    diag = result.get("diagnostics") or {}
    if diag.get("used_model") is True:
        return "MODEL_INFERENCE"
    return "FALLBACK_HEURISTIC"


def _print_header(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 20 + f" {title} " + "=" * 20)


def _elapsed(fn):
    """Decorator to measure execution time."""
    async def wrap(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            out = await fn(*args, **kwargs)
            return out, (time.perf_counter() - t0)
        except Exception as e:
            return e, (time.perf_counter() - t0)
    return wrap


async def verify_get_intent_schema(client) -> List[str]:
    """Verify get_intent_schema method with various scenarios."""
    failures = []
    
    _print_header("GET_INTENT_SCHEMA TESTS")
    
    # Test 1: Get all schemas
    logger.info("Test 1: Get all schemas (no filters)")
    try:
        get_all = _elapsed(client.get_intent_schema)
        result, dt = await get_all()
        if isinstance(result, Exception):
            logger.error(f"❌ Failed: {result}")
            failures.append("get_intent_schema (all) failed")
        else:
            logger.info(f"✅ Success in {dt:.2f}s")
            logger.info(f"Response keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
            if isinstance(result, dict) and "schemas" in result:
                logger.info(f"Number of schemas: {len(result.get('schemas', []))}")
            logger.debug(f"Response: {_pretty(result)}")
    except Exception as e:
        logger.error(f"❌ Exception: {e}")
        logger.error(traceback.format_exc())
        failures.append("get_intent_schema (all) exception")
    
    # Test 2: Get schemas by domain
    logger.info("\nTest 2: Get schemas filtered by domain='device'")
    try:
        get_by_domain = _elapsed(client.get_intent_schema)
        result, dt = await get_by_domain(domain="device")
        if isinstance(result, Exception):
            logger.error(f"❌ Failed: {result}")
            failures.append("get_intent_schema (by domain) failed")
        else:
            logger.info(f"✅ Success in {dt:.2f}s")
            logger.info(f"Response keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
            if isinstance(result, dict) and "schemas" in result:
                schemas = result.get("schemas", [])
                logger.info(f"Number of schemas in 'device' domain: {len(schemas)}")
                if schemas:
                    logger.info(f"First schema function name: {schemas[0].get('function_name', 'N/A')}")
            logger.debug(f"Response: {_pretty(result)}")
    except Exception as e:
        logger.error(f"❌ Exception: {e}")
        logger.error(traceback.format_exc())
        failures.append("get_intent_schema (by domain) exception")
    
    # Test 3: Get schema by function name
    logger.info("\nTest 3: Get schema for specific function")
    try:
        # First, get all schemas to find a function name
        all_schemas_result = await client.get_intent_schema()
        function_name = None
        if isinstance(all_schemas_result, dict):
            schemas = all_schemas_result.get("schemas", [])
            if schemas and isinstance(schemas, list) and len(schemas) > 0:
                function_name = schemas[0].get("function_name")
        
        if function_name:
            logger.info(f"Using function name: {function_name}")
            get_by_function = _elapsed(client.get_intent_schema)
            result, dt = await get_by_function(function_name=function_name)
            if isinstance(result, Exception):
                logger.error(f"❌ Failed: {result}")
                failures.append("get_intent_schema (by function_name) failed")
            else:
                logger.info(f"✅ Success in {dt:.2f}s")
                logger.info(f"Response keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                logger.debug(f"Response: {_pretty(result)}")
        else:
            logger.warning("⚠️  Could not find a function name to test with")
            failures.append("get_intent_schema (by function_name) - no function found")
    except Exception as e:
        logger.error(f"❌ Exception: {e}")
        logger.error(traceback.format_exc())
        failures.append("get_intent_schema (by function_name) exception")
    
    # Test 4: Get schema with both domain and function_name
    logger.info("\nTest 4: Get schema with both domain and function_name")
    try:
        all_schemas_result = await client.get_intent_schema()
        function_name = None
        domain = None
        if isinstance(all_schemas_result, dict):
            schemas = all_schemas_result.get("schemas", [])
            if schemas and isinstance(schemas, list) and len(schemas) > 0:
                first_schema = schemas[0]
                function_name = first_schema.get("function_name")
                domain = first_schema.get("domain")
        
        if function_name and domain:
            logger.info(f"Using function_name={function_name}, domain={domain}")
            get_combined = _elapsed(client.get_intent_schema)
            result, dt = await get_combined(function_name=function_name, domain=domain)
            if isinstance(result, Exception):
                logger.error(f"❌ Failed: {result}")
                failures.append("get_intent_schema (combined filters) failed")
            else:
                logger.info(f"✅ Success in {dt:.2f}s")
                logger.debug(f"Response: {_pretty(result)}")
        else:
            logger.warning("⚠️  Could not find function_name and domain to test with")
            failures.append("get_intent_schema (combined filters) - insufficient data")
    except Exception as e:
        logger.error(f"❌ Exception: {e}")
        logger.error(traceback.format_exc())
        failures.append("get_intent_schema (combined filters) exception")
    
    return failures


async def verify_compile_intent(client) -> List[str]:
    """Verify compile_intent method with various scenarios."""
    failures = []
    
    _print_header("COMPILE_INTENT TESTS")
    
    # Test cases for intent compilation
    test_cases = [
        {
            "name": "Simple device control",
            "text": "turn on the bedroom light",
            "context": {"domain": "device", "room": "bedroom", "device_id": "eisp7pij1tkyzhiw"},
            "expect_model": True,  # Should use model if available
        },
        {
            "name": "Temperature adjustment",
            "text": "set the temperature to 72 degrees",
            "context": {"domain": "device", "room": "living_room", "device_id": "eisp7pij1tkyzhiw"},
            "expect_model": False,  # Will early-exit due to no schema
        },
        {
            "name": "Energy query",
            "text": "what is the current energy consumption",
            "context": {"domain": "energy"},
            "expect_model": False,  # Will early-exit due to no schema
        },
        {
            "name": "Multiple devices",
            "text": "turn off all lights in the kitchen",
            "context": {"domain": "device", "room": "kitchen", "device_id": "eisp7pij1tkyzhiw"},
            "expect_model": True,  # Should use model if available
        },
        {
            "name": "No context",
            "text": "turn on the lights",
            "context": None,
            "expect_model": True,  # Should use model if available
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        logger.info(f"\nTest {i}: {test_case['name']}")
        logger.info(f"Text: '{test_case['text']}'")
        logger.info(f"Context: {test_case['context']}")
        
        try:
            compile_fn = _elapsed(client.compile_intent)
            result, dt = await compile_fn(
                text=test_case["text"],
                context=test_case["context"]
            )
            
            if isinstance(result, Exception):
                logger.error(f"❌ Failed: {result}")
                failures.append(f"compile_intent ({test_case['name']}) failed")
            else:
                logger.info(f"✅ Success in {dt:.2f}s")
                logger.info(f"Response keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                
                # Check for expected fields in response
                if isinstance(result, dict):
                    # Infer and report execution path
                    path = _infer_execution_path(result)
                    diagnostics = result.get("diagnostics", {})
                    
                    logger.info(f"Execution path: {path}")
                    
                    if diagnostics:
                        logger.info(
                            "Diagnostics: used_model=%s, model_version=%s",
                            diagnostics.get("used_model"),
                            diagnostics.get("model_version"),
                        )
                    
                    if "function" in result:
                        logger.info(f"Compiled function: {result.get('function')}")
                    if "arguments" in result:
                        logger.info(f"Arguments: {_pretty(result.get('arguments'))}")
                    if "confidence" in result:
                        logger.info(f"Confidence: {result.get('confidence')}")
                    if "processing_time_ms" in result:
                        logger.info(f"Latency (server): {result.get('processing_time_ms')} ms")
                    
                    # ⚠️ Soft warnings (do NOT fail test)
                    if diagnostics.get("used_model") and result.get("confidence", 0) < 0.3:
                        logger.warning(
                            "⚠️ Model was used but confidence is low (%.2f) - may indicate model uncertainty",
                            result.get("confidence"),
                        )
                    
                    if not diagnostics.get("used_model"):
                        logger.warning("⚠️ Fallback path used for this request")
                    
                    # Check expectations if specified
                    expected_model = test_case.get("expect_model")
                    if expected_model is not None:
                        actual_model = diagnostics.get("used_model", False)
                        if expected_model != actual_model:
                            logger.warning(
                                "⚠️ Execution path mismatch: expected used_model=%s, got %s",
                                expected_model, actual_model
                            )
                            # Optionally fail the test (uncomment to enforce strict expectations)
                            # failures.append(
                            #     f"compile_intent ({test_case['name']}): expected used_model={expected_model}, got {actual_model}"
                            # )
                
                logger.debug(f"Full response: {_pretty(result)}")
        except Exception as e:
            logger.error(f"❌ Exception: {e}")
            logger.error(traceback.format_exc())
            failures.append(f"compile_intent ({test_case['name']}) exception")
    
    return failures


async def verify_service_health(client) -> bool:
    """Verify ML service is healthy before running tests."""
    _print_header("SERVICE HEALTH CHECK")
    
    try:
        health = await client.health()
        logger.info(f"Health status: {health.get('status', 'unknown')}")
        logger.debug(f"Health response: {_pretty(health)}")
        
        if health.get("status") == "healthy":
            logger.info("✅ Service is healthy")
            return True
        else:
            logger.warning("⚠️  Service health status is not 'healthy'")
            return False
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        logger.error(traceback.format_exc())
        return False


async def run_verification() -> int:
    """Run all verification tests."""
    logger.info("🚀 Starting intent compilation verification...")
    
    failures = []
    
    # Initialize ML client
    _print_header("CLIENT INITIALIZATION")
    try:
        from seedcore.serve.ml_client import MLServiceClient
        
        # Try to get base URL from ray_utils, fallback to env or default
        base_url = None
        try:
            from seedcore.utils.ray_utils import ML
            base_url = ML
            logger.info(f"Using ML service URL from ray_utils: {base_url}")
        except Exception:
            base_url = os.getenv("MLS_BASE_URL", "http://127.0.0.1:8000/ml")
            logger.info(f"Using ML service URL: {base_url}")
        
        # Use longer timeout for intent compilation (p95 latency ~8-9s on CPU, 15s provides safety margin)
        client = MLServiceClient(base_url=base_url, timeout=15.0)
        logger.info("✅ MLServiceClient initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize MLServiceClient: {e}")
        logger.error(traceback.format_exc())
        return 1
    
    # Check service health
    is_healthy = await verify_service_health(client)
    if not is_healthy:
        logger.warning("⚠️  Service health check failed, but continuing with tests...")
    
    # Run verification tests
    schema_failures = await verify_get_intent_schema(client)
    failures.extend(schema_failures)
    
    compile_failures = await verify_compile_intent(client)
    failures.extend(compile_failures)
    
    # Summary
    _print_header("SUMMARY")
    if failures:
        logger.error(f"❌ {len(failures)} test(s) failed:")
        for failure in failures:
            logger.error(f"  - {failure}")
        return 1
    else:
        logger.info("✅ All verification tests passed!")
        return 0


def main():
    """Main entry point."""
    try:
        code = anyio.run(run_verification)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        code = 130
    except Exception:
        logger.error("Unhandled exception:")
        logger.error(traceback.format_exc())
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()

