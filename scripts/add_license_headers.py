# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#!/usr/bin/env python3
# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Script to add Apache-2.0 license headers to Python files.

Usage:
    python scripts/add_license_headers.py
"""

import os
import glob
from pathlib import Path

LICENSE_HEADER = '''# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''

def has_license_header(content):
    """Check if file already has a license header."""
    return content.startswith('# Copyright 2024 SeedCore Contributors')

def add_license_header(file_path):
    """Add license header to a Python file if it doesn't already have one."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if has_license_header(content):
            print(f"✓ {file_path} - Already has license header")
            return False
        
        # Add license header
        new_content = LICENSE_HEADER + content
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✓ {file_path} - Added license header")
        return True
        
    except Exception as e:
        print(f"✗ {file_path} - Error: {e}")
        return False

def main():
    """Add license headers to all Python files in the project."""
    # Find all Python files
    python_files = []
    
    # Add src directory
    src_files = glob.glob("src/**/*.py", recursive=True)
    python_files.extend(src_files)
    
    # Add test files
    test_files = glob.glob("tests/**/*.py", recursive=True)
    python_files.extend(test_files)
    
    # Add scripts
    script_files = glob.glob("scripts/**/*.py", recursive=True)
    python_files.extend(script_files)
    
    # Add examples
    example_files = glob.glob("examples/**/*.py", recursive=True)
    python_files.extend(example_files)
    
    print(f"Found {len(python_files)} Python files")
    print("Adding Apache-2.0 license headers...")
    print("-" * 50)
    
    modified_count = 0
    for file_path in python_files:
        if add_license_header(file_path):
            modified_count += 1
    
    print("-" * 50)
    print(f"Modified {modified_count} files")
    print("License header addition complete!")

if __name__ == "__main__":
    main() 