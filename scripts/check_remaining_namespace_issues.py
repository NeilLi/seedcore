#!/usr/bin/env python3
"""
Script to check for any remaining hardcoded namespace references that might have been missed.

This script searches through the codebase for patterns that suggest hardcoded namespaces.
"""

import os
import re
import subprocess
from pathlib import Path

def search_for_hardcoded_namespaces():
    """Search for potential hardcoded namespace references."""
    
    print("🔍 Searching for potential hardcoded namespace references...")
    
    # Patterns that might indicate hardcoded namespaces
    patterns = [
        r'namespace\s*=\s*["\']seedcore[^-]',  # namespace="seedcore" (without -dev)
        r'namespace\s*=\s*["\']serve["\']',     # namespace="serve"
        r'get_actor.*namespace\s*=\s*["\']seedcore[^-]',  # get_actor with hardcoded namespace
        r'ray\.init.*namespace\s*=\s*["\']seedcore[^-]',  # ray.init with hardcoded namespace
    ]
    
    # Directories to search
    search_dirs = [
        "src",
        "scripts", 
        "docker",
        "examples"
    ]
    
    # File extensions to search
    extensions = [".py", ".yaml", ".yml", ".sh"]
    
    issues_found = []
    
    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
            
        for root, dirs, files in os.walk(search_dir):
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    file_path = os.path.join(root, file)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                        for i, line in enumerate(content.split('\n'), 1):
                            for pattern in patterns:
                                if re.search(pattern, line):
                                    issues_found.append({
                                        'file': file_path,
                                        'line': i,
                                        'content': line.strip(),
                                        'pattern': pattern
                                    })
                    except Exception as e:
                        print(f"⚠️ Could not read {file_path}: {e}")
    
    return issues_found

def search_for_missing_environment_usage():
    """Search for files that might be missing environment variable usage."""
    
    print("\n🔍 Searching for files that might need environment variable updates...")
    
    # Files that should use environment variables for namespaces
    critical_files = [
        "src/seedcore/organs/organism_manager.py",
        "src/seedcore/agents/tier0_manager.py", 
        "src/seedcore/utils/ray_utils.py",
        "src/seedcore/config/ray_config.py",
        "src/seedcore/api/routers/tier0_router.py",
        "src/seedcore/serve/simple_app.py",
        "entrypoints/cognitive_entrypoint.py"
    ]
    
    missing_env_usage = []
    
    for file_path in critical_files:
        if not os.path.exists(file_path):
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Check if file uses environment variables for namespaces
            if 'os.getenv' in content and ('RAY_NAMESPACE' in content or 'SEEDCORE_NS' in content):
                print(f"✅ {file_path}: Uses environment variables")
            else:
                missing_env_usage.append(file_path)
                print(f"⚠️ {file_path}: May need environment variable updates")
                
        except Exception as e:
            print(f"❌ Could not read {file_path}: {e}")
    
    return missing_env_usage

def check_environment_variables():
    """Check current environment variable settings."""
    
    print("\n🔍 Checking current environment variables...")
    
    env_vars = {
        'SEEDCORE_NS': os.getenv('SEEDCORE_NS'),
        'RAY_NAMESPACE': os.getenv('RAY_NAMESPACE'),
        'RAY_ADDRESS': os.getenv('RAY_ADDRESS')
    }
    
    for var, value in env_vars.items():
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"⚠️ {var}: Not set")
    
    # Determine effective namespace
    effective_namespace = env_vars['RAY_NAMESPACE'] or env_vars['SEEDCORE_NS'] or "seedcore-dev"
    print(f"\n🎯 Effective namespace: {effective_namespace}")
    
    return env_vars

def main():
    """Main function to run all checks."""
    
    print("🧪 Namespace Issue Checker")
    print("=" * 50)
    
    # Check for hardcoded namespaces
    issues = search_for_hardcoded_namespaces()
    
    if issues:
        print(f"\n❌ Found {len(issues)} potential hardcoded namespace issues:")
        for issue in issues:
            print(f"  📁 {issue['file']}:{issue['line']}")
            print(f"     Content: {issue['content']}")
            print(f"     Pattern: {issue['pattern']}")
            print()
    else:
        print("\n✅ No hardcoded namespace issues found!")
    
    # Check for missing environment variable usage
    missing_env = search_for_missing_environment_usage()
    
    # Check environment variables
    env_vars = check_environment_variables()
    
    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    
    if issues:
        print(f"❌ {len(issues)} potential issues found")
        print("   Please review the files above for hardcoded namespace references")
    else:
        print("✅ No hardcoded namespace issues detected")
    
    if missing_env:
        print(f"⚠️ {len(missing_env)} files may need environment variable updates")
    
    effective_namespace = env_vars['RAY_NAMESPACE'] or env_vars['SEEDCORE_NS'] or "seedcore-dev"
    if effective_namespace == "seedcore-dev":
        print("✅ Environment variables are correctly configured for seedcore-dev namespace")
    else:
        print(f"⚠️ Environment variables suggest namespace: {effective_namespace}")
    
    print("\n🎯 Next steps:")
    if issues:
        print("   1. Review and fix any hardcoded namespace references")
        print("   2. Ensure all components use environment variables")
    else:
        print("   1. Run the test script: python scripts/test_namespace_fix.py")
        print("   2. Deploy and verify agents are visible in the correct namespace")
    
    return len(issues)

if __name__ == "__main__":
    exit(main())
