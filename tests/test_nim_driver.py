#!/usr/bin/env python3
"""
Test Script for SeedCore ML Driver
==================================

This script validates both NimDriverSDK (OpenAI SDK) and NimClient (HTTP)
implementations defined in:
    seedcore/ml/driver/__init__.py

Usage:
    python test_nim_driver.py
    pytest tests/test_nim_driver.py -v
"""

import os
import json
import traceback
from seedcore.ml.driver import (
    NimDriverSDK,
    NimClient,
    get_driver,
    create_fallback_driver,
)


# ---------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------
BASE_URL = os.getenv(
    "NIM_LLM_BASE_URL",
    "http://a3055aa0ec20d4fefab34716edbe28ad-419314233.us-east-1.elb.amazonaws.com:8000/v1",
)
MODEL = os.getenv("SEEDCORE_NIM_MODEL", "meta/llama-3.1-8b-base")
API_KEY = os.getenv("NIM_LLM_API_KE", "none")

TEST_MESSAGE = [{"role": "user", "content": "Hello from SeedCore NIM test!"}]


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
def run_driver(driver, label):
    """Run a simple chat test and show structured output."""
    print(f"\n=== Running {label} ===")
    try:
        response = driver.chat(TEST_MESSAGE)
        print("Response:")
        print(response)
        print("✓ Success")
        return True
    except Exception as e:
        print("✗ Failed:", e)
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------
# Main testing logic
# ---------------------------------------------------------------------
def test_nimclient():
    """Test low-level NimClient."""
    client = NimClient(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    assert run_driver(client, "NimClient (HTTP)") is True


def test_nimdriver_sdk():
    """Test SDK-based driver."""
    driver = NimDriverSDK(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    assert run_driver(driver, "NimDriverSDK (OpenAI SDK)") is True


def test_get_driver_auto_detection():
    """Test get_driver() environment auto-detection."""
    os.environ["SEEDCORE_USE_SDK"] = "true"
    driver = get_driver(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    assert run_driver(driver, "get_driver (auto-detect SDK)") is True

    os.environ["SEEDCORE_USE_SDK"] = "false"
    driver = get_driver(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    assert run_driver(driver, "get_driver (auto-detect HTTP)") is True


def test_fallback_creation():
    """Test automatic fallback behavior."""
    driver = create_fallback_driver(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    assert run_driver(driver, "create_fallback_driver (SDK→HTTP)") is True


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("=== SeedCore ML Driver Test ===")
    print(f"Base URL: {BASE_URL}")
    print(f"Model: {MODEL}")
    print(f"API Key: {API_KEY}")
    print("-" * 60)

    results = {
        "nimclient": test_nimclient(),
        "sdk": test_nimdriver_sdk(),
        "auto": test_get_driver_auto_detection(),
        "fallback": test_fallback_creation(),
    }

    print("\n=== Summary ===")
    print(json.dumps(results, indent=2))
    print("\nAll tests completed.")

