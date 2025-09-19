#!/usr/bin/env python3
"""
DSP Package Patch to prevent file logging issues.
This module must be imported before any DSP-related imports.
"""

import logging
import sys
import os

def patch_dsp_before_import():
    """Patch DSP package before it's imported to prevent file logging."""
    
    # Set environment variables
    os.environ['DSP_LOG_TO_FILE'] = 'false'
    os.environ['DSP_LOG_TO_STDOUT'] = 'true'
    os.environ['DSP_LOG_LEVEL'] = 'INFO'
    
    # Monkey patch logging.FileHandler globally
    original_file_handler = logging.FileHandler
    
    def safe_file_handler(filename, mode='a', encoding=None, delay=False):
        """Safe file handler that redirects to /tmp or configured path instead of the original location."""
        # Use environment variable if set, otherwise default to /tmp
        log_path = os.getenv('DSP_LOG_PATH', '/tmp')
        if os.path.isdir(log_path):
            safe_filename = os.path.join(log_path, os.path.basename(filename))
        else:
            safe_filename = f"/tmp/{os.path.basename(filename)}"
        
        print(f"⚠️  FileHandler requested for {filename}, redirecting to {safe_filename}")
        try:
            return original_file_handler(safe_filename, mode, encoding, delay)
        except Exception as e:
            print(f"⚠️  Failed to create file handler for {safe_filename}, falling back to stdout: {e}")
            return logging.StreamHandler(sys.stdout)
    
    # Replace the FileHandler class
    logging.FileHandler = safe_file_handler
    
    # Also patch the logging.basicConfig to prevent file handlers
    original_basic_config = logging.basicConfig
    
    def safe_basic_config(*args, **kwargs):
        """Safe basicConfig that prevents file handlers."""
        # Remove any file handlers from kwargs
        if 'handlers' in kwargs:
            safe_handlers = []
            for handler in kwargs['handlers']:
                if not hasattr(handler, 'baseFilename'):
                    safe_handlers.append(handler)
                else:
                    print(f"⚠️  Replacing file handler with stdout handler")
                    safe_handlers.append(logging.StreamHandler(sys.stdout))
            kwargs['handlers'] = safe_handlers
        
        # Call original with safe kwargs
        return original_basic_config(*args, **kwargs)
    
    logging.basicConfig = safe_basic_config
    
    print("✅ DSP logging patched globally to prevent file creation")

# Apply the patch immediately when this module is imported
patch_dsp_before_import()



