#!/usr/bin/env python3
"""
Logging configuration for SeedCore API to avoid file permission issues.
This redirects all logs to stdout/stderr instead of writing to files.
"""

import logging
import sys
import os
import warnings

def configure_logging():
    """Configure logging to output to stdout/stderr instead of files."""
    
    try:
        # Set environment variables BEFORE any imports to prevent file logging
        os.environ['DSP_LOG_TO_FILE'] = 'false'
        os.environ['DSP_LOG_TO_STDOUT'] = 'true'
        os.environ['DSP_LOG_LEVEL'] = 'INFO'
        
        # Disable file logging globally
        os.environ['LOG_TO_FILE'] = 'false'
        os.environ['LOG_TO_STDOUT'] = 'true'
        
        # Configure root logger
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.StreamHandler(sys.stderr)
            ]
        )
        
        # Set specific loggers to avoid file writing
        logging.getLogger('dsp').setLevel(logging.INFO)
        logging.getLogger('dspy').setLevel(logging.INFO)
        
        # Redirect any file-based logging to stdout
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'baseFilename'):
                # Replace file handler with stream handler
                logging.getLogger().removeHandler(handler)
                logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
        
        # Suppress warnings about file handlers
        warnings.filterwarnings("ignore", message=".*FileHandler.*")
        
        print("✅ Logging configured to output to stdout/stderr")
        
    except Exception as e:
        print(f"⚠️  Warning: Could not configure logging: {e}")
        print("Continuing with default logging configuration...")

def patch_dsp_logging():
    """Patch DSP package to prevent file logging."""
    try:
        # Monkey patch the logging.FileHandler to prevent file creation
        original_file_handler = logging.FileHandler
        
        def safe_file_handler(filename, mode='a', encoding=None, delay=False):
            """Safe file handler that redirects to stdout instead of files."""
            print(f"⚠️  DSP trying to create file handler for {filename}, redirecting to stdout")
            return logging.StreamHandler(sys.stdout)
        
        # Replace the FileHandler class
        logging.FileHandler = safe_file_handler
        
        print("✅ DSP logging patched to prevent file creation")
        
    except Exception as e:
        print(f"⚠️  Warning: Could not patch DSP logging: {e}")

if __name__ == "__main__":
    # Patch DSP logging first
    patch_dsp_logging()
    
    # Then configure general logging
    configure_logging()
