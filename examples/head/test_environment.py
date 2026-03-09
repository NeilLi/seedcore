#!/usr/bin/env python3
"""
Environment Test Script for SeedCore API Pod

This script tests the environment variables and service connectivity
to help debug issues when running in the seedcore-api pod.
"""

import os
import sys
import requests
from pathlib import Path

def test_environment_variables():
    """Test environment variables."""
    print("🔍 Environment Variables Test")
    print("=" * 40)
    
    # Check key environment variables
    key_vars = [
        'SEEDCORE_API_ADDRESS',
        'RAY_NAMESPACE', 
        'SEEDCORE_NS',
        'RAY_HOST',
        'RAY_PORT',
        'RAY_SERVE_URL'
    ]
    
    for var in key_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: Not set")
    
    print()

def test_service_connectivity():
    """Test connectivity to various services."""
    print("🔗 Service Connectivity Test")
    print("=" * 40)
    
    # Test Ray head service
    services = [
        ("Ray Head ML Service", "http://seedcore-svc-stable-svc:8000/ml/health"),
        ("Ray Head Dashboard", "http://seedcore-svc-stable-svc:8265"),
        ("Localhost ML Service", "http://localhost:8000/ml/health"),
        ("Localhost Dashboard", "http://localhost:8265")
    ]
    
    for name, url in services:
        try:
            if "health" in url:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    print(f"✅ {name}: {url} - Status: {response.status_code}")
                else:
                    print(f"⚠️  {name}: {url} - Status: {response.status_code}")
            else:
                response = requests.get(url, timeout=5)
                print(f"✅ {name}: {url} - Status: {response.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"❌ {name}: {url} - Connection refused")
        except Exception as e:
            print(f"❌ {name}: {url} - Error: {e}")
    
    print()

def test_writable_directories():
    """Test which directories are writable."""
    print("📁 Writable Directories Test")
    print("=" * 40)
    
    test_dirs = [
        "/tmp",
        "/app/data"
    ]
    
    for dir_path in test_dirs:
        if dir_path is None:
            continue
            
        if os.path.exists(dir_path):
            if os.access(dir_path, os.W_OK):
                print(f"✅ {dir_path}: Writable")
                
                # Try to create a test file
                test_file = os.path.join(dir_path, "test_write.tmp")
                try:
                    with open(test_file, 'w') as f:
                        f.write("test")
                    os.remove(test_file)
                    print(f"   ✅ Can create/delete files")
                except Exception as e:
                    print(f"   ❌ Cannot create/delete files: {e}")
            else:
                print(f"❌ {dir_path}: Not writable")
        else:
            print(f"❌ {dir_path}: Does not exist")
    
    print()

def test_python_paths():
    """Test Python import paths."""
    print("🐍 Python Paths Test")
    print("=" * 40)
    
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print(f"Python path:")
    for i, path in enumerate(sys.path):
        print(f"  {i}: {path}")
    
    print()

def main():
    """Run all tests."""
    print("🚀 SeedCore API Pod Environment Test")
    print("=" * 50)
    print()
    
    test_environment_variables()
    test_service_connectivity()
    test_writable_directories()
    test_python_paths()
    
    print("✨ Environment test completed!")

if __name__ == "__main__":
    main()
