#!/usr/bin/env python3
"""
Organism Serve Entrypoint for SeedCore
entrypoints/organism_entrypoint.py
"""
import sys
import os
from typing import Dict, Any

# 1. Safer Path Injection (Idempotent)
# Best practice: Set PYTHONPATH in Dockerfile, but this acts as a fallback
project_roots = ['/app', '/app/src']
for root in project_roots:
    if root not in sys.path and os.path.exists(root):
        sys.path.insert(0, root)

# Import the CLASS, not the instance
try:
    from seedcore.services.organism_service import OrganismService
except ImportError as e:
    raise ImportError(f"Could not import OrganismService. Check PYTHONPATH. Error: {e}")

def build_organism_app(args: Dict[str, Any] | None = None):
    """
    Builder function for the organism service application.
    
    Dynamically binds the OrganismService with configuration arguments 
    defined in the Serve YAML.
    """
    args = args or {}
    
    # Extract config to pass to the service
    # e.g., enabling/disabling specific organs via config
    service_config = {
        "env": args.get("env", "development"),
        "log_level": args.get("log_level", "INFO")
    }

    # Dynamic Binding
    # This creates a NEW instance of the deployment structure every time Serve reloads
    return OrganismService.bind(config=service_config)