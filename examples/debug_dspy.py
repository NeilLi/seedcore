#!/usr/bin/env python3
"""
Debug DSPy Integration

This script helps debug the DSPy integration by testing each component step by step.
"""

import os
import sys
import json
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_llm_configuration():
    """Test LLM configuration step by step."""
    print("🔍 Testing LLM Configuration")
    print("=" * 40)
    
    try:
        # Check environment variable
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            print(f"✅ OPENAI_API_KEY found (length: {len(api_key)})")
            print(f"   Key starts with: {api_key[:10]}...")
        else:
            print("❌ OPENAI_API_KEY not found")
            return False
        
        # Test LLM config creation
        from seedcore.config.llm_config import configure_llm_openai, LLMConfig
        
        print("🔧 Creating LLM configuration...")
        config = LLMConfig.from_env()
        print(f"✅ LLM config created: {config}")
        
        # Test configuration
        print("🔧 Configuring OpenAI...")
        configure_llm_openai(api_key)
        print("✅ OpenAI configured successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ LLM configuration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_dspy_imports():
    """Test DSPy imports and basic functionality."""
    print("\n🔍 Testing DSPy Imports")
    print("=" * 40)
    
    try:
        import dspy
        print("✅ DSPy imported successfully")
        
        # Test basic DSPy functionality
        print("🔧 Testing DSPy settings...")
        print(f"   Current LM: {dspy.settings.lm}")
        
        return True
        
    except Exception as e:
        print(f"❌ DSPy import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cognitive_core_initialization():
    """Test cognitive core initialization."""
    print("\n🔍 Testing Cognitive Core Initialization")
    print("=" * 40)
    
    try:
        from seedcore.agents.cognitive_core import (
            CognitiveCore, 
            CognitiveContext, 
            CognitiveTaskType,
            initialize_cognitive_core,
            get_cognitive_core
        )
        
        print("🔧 Initializing cognitive core...")
        cognitive_core = initialize_cognitive_core()
        print("✅ Cognitive core initialized")
        
        print(f"   Provider: {cognitive_core.llm_provider}")
        print(f"   Model: {cognitive_core.model}")
        print(f"   Task handlers: {len(cognitive_core.task_handlers)}")
        
        # Test getting the global instance
        global_core = get_cognitive_core()
        if global_core:
            print("✅ Global cognitive core instance available")
        else:
            print("❌ Global cognitive core instance not available")
        
        return cognitive_core
        
    except Exception as e:
        print(f"❌ Cognitive core initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_simple_dspy_call():
    """Test a simple DSPy call."""
    print("\n🔍 Testing Simple DSPy Call")
    print("=" * 40)
    
    try:
        import dspy
        
        # Create a simple signature
        class SimpleSignature(dspy.Signature):
            input_text = dspy.InputField(desc="Input text")
            output_text = dspy.OutputField(desc="Output text")
        
        # Create a simple predictor
        predictor = dspy.ChainOfThought(SimpleSignature)
        
        print("🔧 Testing simple DSPy call...")
        result = predictor(input_text="Hello, this is a test.")
        
        print("✅ Simple DSPy call successful")
        print(f"   Input: Hello, this is a test.")
        print(f"   Output: {result.output_text}")
        
        return True
        
    except Exception as e:
        print(f"❌ Simple DSPy call failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cognitive_task():
    """Test a cognitive task."""
    print("\n🔍 Testing Cognitive Task")
    print("=" * 40)
    
    try:
        from seedcore.agents.cognitive_core import (
            CognitiveContext, 
            CognitiveTaskType,
            get_cognitive_core
        )
        
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            print("❌ Cognitive core not available")
            return False
        
        # Create a simple context
        context = CognitiveContext(
            agent_id="debug_agent",
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data={
                "incident_id": "debug_001",
                "error_message": "Test error for debugging",
                "agent_state": {"capability_score": 0.5}
            }
        )
        
        print("🔧 Executing cognitive task...")
        result = cognitive_core(context)
        
        print("✅ Cognitive task executed")
        print(f"   Success: {result.get('success', False)}")
        print(f"   Thought: {result.get('thought', 'N/A')}")
        print(f"   Solution: {result.get('proposed_solution', 'N/A')}")
        print(f"   Confidence: {result.get('confidence_score', 'N/A')}")
        
        if result.get('error'):
            print(f"   Error: {result.get('error')}")
        
        return result.get('success', False)
        
    except Exception as e:
        print(f"❌ Cognitive task failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main debug function."""
    print("🐛 DSPy Integration Debug")
    print("=" * 50)
    
    # Test 1: LLM Configuration
    llm_ok = test_llm_configuration()
    
    # Test 2: DSPy Imports
    dspy_ok = test_dspy_imports()
    
    # Test 3: Cognitive Core Initialization
    cognitive_core = test_cognitive_core_initialization()
    
    # Test 4: Simple DSPy Call
    simple_ok = test_simple_dspy_call()
    
    # Test 5: Cognitive Task
    task_ok = test_cognitive_task()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Debug Summary")
    print("=" * 50)
    
    print(f"LLM Configuration: {'✅ PASS' if llm_ok else '❌ FAIL'}")
    print(f"DSPy Imports: {'✅ PASS' if dspy_ok else '❌ FAIL'}")
    print(f"Cognitive Core: {'✅ PASS' if cognitive_core else '❌ FAIL'}")
    print(f"Simple DSPy Call: {'✅ PASS' if simple_ok else '❌ FAIL'}")
    print(f"Cognitive Task: {'✅ PASS' if task_ok else '❌ FAIL'}")
    
    if all([llm_ok, dspy_ok, cognitive_core, simple_ok, task_ok]):
        print("\n🎉 All tests passed! DSPy integration is working correctly.")
    else:
        print("\n⚠️ Some tests failed. Check the errors above for details.")
    
    print("\n💡 If the cognitive task is failing, it might be due to:")
    print("   - API rate limiting")
    print("   - Network connectivity issues")
    print("   - Model availability")
    print("   - Token limits")

if __name__ == "__main__":
    main()
