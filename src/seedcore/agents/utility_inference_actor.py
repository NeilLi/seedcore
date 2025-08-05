"""
Utility Predictor Actor for XGBoost Model Inference

This module implements a Ray actor within the Utility organ that performs
XGBoost model inference and integrates with the Energy system.

The actor periodically checks for new models and logs the energy impact
of each prediction, creating a closed loop for model performance tracking.
"""

import ray
import requests
import json
import numpy as np
from datetime import datetime
import logging
import os
from typing import Optional, Dict, Any, List
import operator

logger = logging.getLogger(__name__)


def get_latest_model_path() -> Optional[str]:
    """
    Queries the API to find the path of the most recent model.
    
    Returns:
        str: Path to the latest model, or None if no models found
    """
    try:
        # Use environment variable for Ray Serve address
        base_url = os.getenv("RAY_SERVE_ADDRESS", "localhost:8000")
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        r = requests.get(f"{base_url}/xgboost/list_models", timeout=5)
        r.raise_for_status()
        models = r.json().get("models", [])
        if not models:
            logger.warning("No models found in the system")
            return None
        
        # Sort by 'created' timestamp descending and get the first one
        newest_model = max(models, key=operator.itemgetter("created"))
        model_path = newest_model.get("path")
        logger.info(f"Latest model found: {model_path}")
        return model_path
        
    except requests.RequestException as e:
        logger.error(f"Error fetching models: {e}")
        return None


@ray.remote
class UtilityPredictor:
    """
    Ray actor for XGBoost model inference within the Utility organ.
    
    This actor handles:
    - Dynamic model loading and refresh
    - Real-time prediction inference
    - Energy system integration
    - Performance monitoring and logging
    """
    
    def __init__(self, refresh_interval_hours: int = 24):
        """
        Initialize the UtilityPredictor actor.
        
        Args:
            refresh_interval_hours: How often to check for new models (default: 24 hours)
        """
        self.model_path: Optional[str] = None
        self.refresh_interval_hours = refresh_interval_hours
        self.last_refresh: Optional[datetime] = None
        self.prediction_count = 0
        self.success_count = 0
        
        # Initial model load on startup
        self.refresh_model()
        logger.info("UtilityPredictor actor initialized")

    def refresh_model(self) -> bool:
        """
        Periodically called to load the latest model.
        
        Returns:
            bool: True if model was refreshed, False otherwise
        """
        latest_path = get_latest_model_path()
        if latest_path and latest_path != self.model_path:
            self.model_path = latest_path
            self.last_refresh = datetime.utcnow()
            logger.info(f"UtilityPredictor loaded new model: {self.model_path}")
            return True
        return False

    def should_refresh_model(self) -> bool:
        """
        Check if it's time to refresh the model based on the refresh interval.
        
        Returns:
            bool: True if model should be refreshed
        """
        if not self.last_refresh:
            return True
        
        time_since_refresh = datetime.utcnow() - self.last_refresh
        return time_since_refresh.total_seconds() > (self.refresh_interval_hours * 3600)

    def predict(self, features: np.ndarray) -> float:
        """
        Runs a single prediction and logs the energy impact.
        
        Args:
            features: Input features as numpy array
            
        Returns:
            float: Prediction value, or -1.0 if prediction failed
        """
        # Check if we need to refresh the model
        if self.should_refresh_model():
            self.refresh_model()
        
        if not self.model_path:
            self.refresh_model()
            if not self.model_path:
                logger.error("No model available for prediction")
                return -1.0

        payload = {
            "features": features.tolist(),
            "path": self.model_path
        }
        
        try:
            # Use environment variable for Ray Serve address
            base_url = os.getenv("RAY_SERVE_ADDRESS", "localhost:8000")
            if not base_url.startswith("http"):
                base_url = f"http://{base_url}"
            r = requests.post(f"{base_url}/xgboost/predict",
                              json=payload, timeout=5)
            r.raise_for_status()
            prediction = r.json()["prediction"]
            
            # Update prediction statistics
            self.prediction_count += 1
            self.success_count += 1
            
            # --- Energy Integration Step ---
            self._log_energy_event(prediction, success=True)
            
            logger.debug(f"Prediction successful: {prediction}")
            return prediction
            
        except requests.RequestException as e:
            logger.error(f"Prediction failed: {e}")
            self.prediction_count += 1
            self._log_energy_event(-1.0, success=False)
            return -1.0

    def _log_energy_event(self, prediction: float, success: bool) -> None:
        """
        Log energy event to the energy ledger.
        
        Args:
            prediction: The prediction value
            success: Whether the prediction was successful
        """
        energy_event = {
            "ts": datetime.utcnow().timestamp(),
            "organ": "utility",
            "metric": "predicted_risk",  # Or 'predicted_success_prob' etc.
            "value": prediction,
            "model_path": self.model_path,
            "success": success,
            "prediction_count": self.prediction_count,
            "success_rate": self.success_count / max(1, self.prediction_count)
        }
        
        try:
            # Post the event to the energy ledger API (telemetry server on internal network)
            # Use environment variable for API address
            api_address = os.getenv("SEEDCORE_API_ADDRESS", "seedcore-api:8002")
            if not api_address.startswith("http"):
                api_address = f"http://{api_address}"
            requests.post(f"{api_address}/energy/log", 
                         json=energy_event, timeout=2)
            logger.debug(f"Energy event logged: {energy_event}")
        except requests.RequestException as e:
            logger.warning(f"Failed to log energy event: {e}")

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the predictor.
        
        Returns:
            dict: Status information including model path, refresh info, and statistics
        """
        return {
            "model_path": self.model_path,
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "refresh_interval_hours": self.refresh_interval_hours,
            "prediction_count": self.prediction_count,
            "success_count": self.success_count,
            "success_rate": self.success_count / max(1, self.prediction_count)
        }

    def force_refresh(self) -> bool:
        """
        Force a model refresh regardless of the refresh interval.
        
        Returns:
            bool: True if model was refreshed, False otherwise
        """
        logger.info("Forcing model refresh")
        return self.refresh_model()

    def update_refresh_interval(self, hours: int) -> None:
        """
        Update the refresh interval.
        
        Args:
            hours: New refresh interval in hours
        """
        self.refresh_interval_hours = hours
        logger.info(f"Refresh interval updated to {hours} hours")


# Global actor instance for easy access
_utility_predictor = None


def get_utility_predictor(refresh_interval_hours: int = 24) -> ray.actor.ActorHandle:
    """
    Get or create the global UtilityPredictor actor instance.
    
    Args:
        refresh_interval_hours: Refresh interval for new instances
        
    Returns:
        ray.actor.ActorHandle: Handle to the UtilityPredictor actor
    """
    global _utility_predictor
    if _utility_predictor is None:
        _utility_predictor = UtilityPredictor.remote(refresh_interval_hours)
        logger.info("Created new UtilityPredictor actor instance")
    return _utility_predictor


def reset_utility_predictor() -> None:
    """Reset the global UtilityPredictor actor instance."""
    global _utility_predictor
    _utility_predictor = None
    logger.info("Reset UtilityPredictor actor instance") 