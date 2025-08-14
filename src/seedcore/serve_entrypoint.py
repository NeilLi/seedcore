"""
SeedCore Serve Entrypoint Module

This module provides the build_app function that creates and returns
the Ray Serve application deployment graph for the standalone serve pod.
"""

from src.seedcore.ml.serve_app import create_serve_app

def build_app():
    """
    Build and return the SeedCore Ray Serve application.
    
    This function creates the main ML service deployment that includes:
    - Salience scoring models
    - Anomaly detection models  
    - Predictive scaling models
    - XGBoost distributed training and inference
    
    Returns:
        A Ray Serve deployment that can be deployed with serve.run()
    """
    return create_serve_app()


