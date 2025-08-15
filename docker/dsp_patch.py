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
        """Safe file handler that redirects to stdout instead of files."""
        print(f"⚠️  FileHandler requested for {filename}, redirecting to stdout")
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

