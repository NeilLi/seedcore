"""
SeedCore Serve Entrypoint Module

This module provides the build_app function that creates and returns
the Ray Serve application deployment graph for the standalone serve pod.
"""

from src.seedcore.ml.serve_app import create_serve_app

def build_app(config: dict = None):
    """
    Build and return the SeedCore Ray Serve application.
    
    This function creates the main ML service deployment that includes:
    - Salience scoring models
    - Anomaly detection models  
    - Predictive scaling models
    - XGBoost distributed training and inference
    
    Args:
        config: Configuration dictionary (required by Ray Serve, can be None)
        
    Returns:
        A Ray Serve deployment that can be deployed with serve.run()
    """
    return create_serve_app()

# Make a top-level app object for RayService to import directly
try:
    app = build_app()   # this should return your Serve graph / ingress deployment
except Exception as e:
    # Optional: log to help debugging if import fails in Serve controller
    import traceback, sys
    print("[serve_entrypoint] build_app() failed at import time:", e, file=sys.stderr)
    traceback.print_exc()
    app = None


