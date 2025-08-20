#!/usr/bin/env python3
"""
Test script for JSON sanitization function

This script tests the sanitize_json function to ensure it properly handles
inf, -inf, and NaN values that are not JSON compliant.
"""

import math
import numpy as np
import json
import sys
import os

# Add the src directory to the path so we can import the sanitization function
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_sanitization():
    """Test the sanitize_json function with various problematic values."""
    
    # Import the sanitization function
    try:
        from seedcore.ml.serve_app import sanitize_json
        print("✅ Successfully imported sanitize_json function")
    except ImportError as e:
        print(f"❌ Failed to import sanitize_json: {e}")
        return False
    
    # Test data with problematic values
    test_data = {
        "normal_float": 3.14,
        "infinity": float('inf'),
        "negative_infinity": float('-inf'),
        "nan": float('nan'),
        "numpy_inf": np.inf,
        "numpy_neg_inf": np.NINF,
        "numpy_nan": np.nan,
        "numpy_array": np.array([1.0, np.inf, np.nan, -np.inf]),
        "nested": {
            "deep_inf": float('inf'),
            "deep_nan": float('nan'),
            "list_with_problems": [1.0, float('inf'), float('nan')]
        },
        "mixed_list": [1, 2.5, float('inf'), "string", float('nan')]
    }
    
    print("\n🧪 Testing sanitization with problematic values...")
    print(f"Original data: {test_data}")
    
    try:
        # Apply sanitization
        sanitized = sanitize_json(test_data)
        print(f"✅ Sanitization completed successfully")
        
        # Try to serialize to JSON
        json_str = json.dumps(sanitized, indent=2)
        print(f"✅ JSON serialization successful")
        
        # Check that problematic values were replaced
        print("\n📊 Sanitization results:")
        print(f"  Original infinity: {test_data['infinity']}")
        print(f"  Sanitized infinity: {sanitized['infinity']}")
        print(f"  Original nan: {test_data['nan']}")
        print(f"  Sanitized nan: {sanitized['nan']}")
        print(f"  Original numpy_inf: {test_data['numpy_inf']}")
        print(f"  Sanitized numpy_inf: {sanitized['numpy_inf']}")
        
        # Verify that all problematic values were replaced with None
        assert sanitized['infinity'] is None, "Infinity should be replaced with None"
        assert sanitized['negative_infinity'] is None, "Negative infinity should be replaced with None"
        assert sanitized['nan'] is None, "NaN should be replaced with None"
        assert sanitized['numpy_inf'] is None, "NumPy infinity should be replaced with None"
        assert sanitized['numpy_neg_inf'] is None, "NumPy negative infinity should be replaced with None"
        assert sanitized['numpy_nan'] is None, "NumPy NaN should be replaced with None"
        
        print("✅ All assertions passed - sanitization working correctly!")
        
        # Show the final sanitized JSON
        print(f"\n📄 Final sanitized JSON:")
        print(json_str)
        
        return True
        
    except Exception as e:
        print(f"❌ Sanitization test failed: {e}")
        return False

def test_edge_cases():
    """Test edge cases and unusual data types."""
    try:
        from seedcore.ml.serve_app import sanitize_json
        print("\n🧪 Testing edge cases...")
        
        # Test with None
        result = sanitize_json(None)
        assert result is None, "None should remain None"
        
        # Test with empty containers
        result = sanitize_json({})
        assert result == {}, "Empty dict should remain empty"
        
        result = sanitize_json([])
        assert result == [], "Empty list should remain empty"
        
        # Test with strings and integers
        result = sanitize_json("hello")
        assert result == "hello", "Strings should remain unchanged"
        
        result = sanitize_json(42)
        assert result == 42, "Integers should remain unchanged"
        
        # Test with complex nested structure
        complex_data = {
            "level1": {
                "level2": [
                    {"value": float('inf')},
                    {"value": float('nan')},
                    {"value": 123.45}
                ]
            }
        }
        
        sanitized = sanitize_json(complex_data)
        assert sanitized['level1']['level2'][0]['value'] is None, "Nested infinity should be replaced"
        assert sanitized['level1']['level2'][1]['value'] is None, "Nested NaN should be replaced"
        assert sanitized['level1']['level2'][2]['value'] == 123.45, "Normal values should remain"
        
        print("✅ Edge case tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Edge case test failed: {e}")
        return False

def main():
    """Main test function."""
    print("🚀 Starting JSON Sanitization Tests")
    print("=" * 50)
    
    success1 = test_sanitization()
    success2 = test_edge_cases()
    
    print("\n" + "=" * 50)
    if success1 and success2:
        print("🎉 All tests passed! JSON sanitization is working correctly.")
    else:
        print("❌ Some tests failed. Please check the implementation.")
    
    return success1 and success2

if __name__ == "__main__":
    main()
