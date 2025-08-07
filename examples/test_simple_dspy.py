#!/usr/bin/env python3
"""
Simple DSPy Test (No API Key Required)

This script tests the basic DSPy integration structure without requiring an API key.
It verifies that the cognitive core can be initialized and the basic structure works.
"""

import os
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_imports():
    """Test that all required modules can be imported."""
    print("🔍 Testing imports...")
    
    try:
        from seedcore.agents.cognitive_core import (
            CognitiveCore, 
            CognitiveContext, 
            CognitiveTaskType,
            initialize_cognitive_core,
            get_cognitive_core
        )
        print("✅ All cognitive core imports successful")
        
        from seedcore.config.llm_config import configure_llm_openai
        print("✅ LLM config imports successful")
        
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def test_cognitive_task_types():
    """Test that all cognitive task types are available."""
    print("\n🔍 Testing cognitive task types...")
    
    try:
        from seedcore.agents.cognitive_core import CognitiveTaskType
        
        expected_types = [
            "failure_analysis",
            "task_planning", 
            "decision_making",
            "problem_solving",
            "memory_synthesis",
            "capability_assessment"
        ]
        
        available_types = [task.value for task in CognitiveTaskType]
        
        print(f"✅ Found {len(available_types)} task types:")
        for task_type in available_types:
            print(f"   - {task_type}")
        
        # Check if all expected types are present
        missing_types = set(expected_types) - set(available_types)
        if missing_types:
            print(f"⚠️ Missing task types: {missing_types}")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Task types test failed: {e}")
        return False

def test_cognitive_context():
    """Test that CognitiveContext can be created."""
    print("\n🔍 Testing cognitive context creation...")
    
    try:
        from seedcore.agents.cognitive_core import CognitiveContext, CognitiveTaskType
        
        context = CognitiveContext(
            agent_id="test_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={"test": "data"}
        )
        
        print("✅ CognitiveContext created successfully")
        print(f"   Agent ID: {context.agent_id}")
        print(f"   Task Type: {context.task_type.value}")
        print(f"   Input Data: {context.input_data}")
        
        return True
    except Exception as e:
        print(f"❌ CognitiveContext test failed: {e}")
        return False

def test_cognitive_core_structure():
    """Test that CognitiveCore can be created (without initialization)."""
    print("\n🔍 Testing cognitive core structure...")
    
    try:
        from seedcore.agents.cognitive_core import CognitiveCore
        
        # Create a cognitive core instance (this won't initialize DSPy)
        core = CognitiveCore.__new__(CognitiveCore)
        
        print("✅ CognitiveCore structure test passed")
        print(f"   Class: {type(core).__name__}")
        
        return True
    except Exception as e:
        print(f"❌ CognitiveCore structure test failed: {e}")
        return False

def test_llm_config():
    """Test LLM configuration structure."""
    print("\n🔍 Testing LLM configuration...")
    
    try:
        from seedcore.config.llm_config import LLMConfig, LLMProvider
        
        # Test creating config from environment
        config = LLMConfig.from_env()
        
        print("✅ LLM configuration test passed")
        print(f"   Provider: {config.provider.value}")
        print(f"   Model: {config.model}")
        print(f"   API Key Set: {config.api_key is not None}")
        
        return True
    except Exception as e:
        print(f"❌ LLM configuration test failed: {e}")
        return False

def test_api_endpoints():
    """Test that the API endpoints are accessible."""
    print("\n🔍 Testing API endpoints...")
    
    try:
        import requests
        
        # Test the status endpoint
        response = requests.get("http://localhost:8002/dspy/status", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ DSPy status endpoint accessible")
            print(f"   Success: {data.get('success', False)}")
            print(f"   Supported Task Types: {len(data.get('supported_task_types', []))}")
            return True
        else:
            print(f"⚠️ Status endpoint returned {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ API endpoint test failed: {e}")
        return False
    except Exception as e:
        print(f"❌ API test failed: {e}")
        return False

def main():
    """Main test function."""
    print("🧪 Simple DSPy Integration Test (No API Key Required)")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Cognitive Task Types", test_cognitive_task_types),
        ("Cognitive Context", test_cognitive_context),
        ("Cognitive Core Structure", test_cognitive_core_structure),
        ("LLM Configuration", test_llm_config),
        ("API Endpoints", test_api_endpoints)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! DSPy integration is ready.")
        print("\nNext steps:")
        print("1. Set OPENAI_API_KEY environment variable")
        print("2. Run: python examples/simple_dspy_example.py")
    else:
        print("⚠️ Some tests failed. Please check the errors above.")
    
    print("\n💡 This test verifies the basic structure without requiring an API key.")
    print("   To test full functionality, set OPENAI_API_KEY and run the full example.")

if __name__ == "__main__":
    main()
