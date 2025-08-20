#!/usr/bin/env python3
"""
XGBoost Hyperparameter Tuning Demo for SeedCore

This script demonstrates the new hyperparameter tuning functionality
using Ray Tune, integrated with the Cognitive Organism Architecture.
"""

import os
import requests
import json
import time
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class XGBoostTuningDemo:
    """Demo class for XGBoost hyperparameter tuning functionality."""
    
    def __init__(self, base_url: str = None):
        if base_url is None:
            # Auto-detect service URL based on environment
            if os.getenv('KUBERNETES_SERVICE_HOST'):
                # We're in a K8s pod, use internal service names
                self.base_url = "http://seedcore-svc-serve-svc:8000"
            else:
                # Local development (assumes port-forwarding)
                self.base_url = "http://localhost:8000"
        else:
            self.base_url = base_url
        
        # ✅ FIX: Add the /ml_serve route prefix to all requests
        self.ml_service_url = f"{self.base_url}/ml_serve"
        self.session = requests.Session()
        logger.info(f"🔗 Using ML service at: {self.ml_service_url}")
    
    def test_basic_training(self) -> bool:
        """Test basic XGBoost training to ensure the service is working."""
        logger.info("🧪 Testing basic XGBoost training...")
        
        payload = {
            "use_sample_data": True,
            "sample_size": 1000,
            "sample_features": 10,
            "name": "demo_basic_model",
            "xgb_config": {
                "objective": "binary:logistic",
                "eval_metric": ["logloss", "auc"],
                "eta": 0.1,
                "max_depth": 5,
                "num_boost_round": 20
            },
            "training_config": {
                "num_workers": 1,
                "use_gpu": False,
                "cpu_per_worker": 1
            }
        }
        
        try:
            # ✅ FIX: Use the full service URL
            response = self.session.post(f"{self.ml_service_url}/xgboost/train", json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"✅ Basic training successful - AUC: {result.get('metrics', {}).get('validation_0-auc', 'N/A')}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Basic training failed: {e}")
            return False
    
    def test_conservative_tuning(self) -> bool:
        """Test conservative hyperparameter tuning."""
        logger.info("🎯 Testing conservative hyperparameter tuning...")
        
        payload = {
            "space_type": "conservative",
            "config_type": "conservative",
            "experiment_name": "demo_conservative_tuning"
        }
        
        try:
            # ✅ FIX: Use the full service URL
            response = self.session.post(f"{self.ml_service_url}/xgboost/tune", json=payload, timeout=300)
            response.raise_for_status()
            result = response.json()
            
            if result.get("status") == "success":
                best_trial = result.get("best_trial", {})
                logger.info(f"✅ Conservative tuning successful!")
                logger.info(f"   Best AUC: {best_trial.get('auc', 'N/A'):.4f}")
                logger.info(f"   Total trials: {result.get('total_trials', 'N/A')}")
                logger.info(f"   Best config: {best_trial.get('config', {})}")
                return True
            else:
                logger.error(f"❌ Conservative tuning failed: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Conservative tuning failed: {e}")
            return False
    
    # (Other test methods would need the same URL fix)
    
    def run_full_demo(self) -> bool:
        """Run the complete hyperparameter tuning demo."""
        logger.info("🚀 Starting XGBoost Hyperparameter Tuning Demo")
        logger.info("=" * 60)
        
        if not self.test_basic_training():
            logger.error("❌ Basic training failed, aborting demo")
            return False
        
        if not self.test_conservative_tuning():
            logger.warning("⚠️ Conservative tuning failed, continuing with other tests")
        
        # ... (other tests would be called here) ...
        
        logger.info("=" * 60)
        logger.info("🎉 XGBoost Hyperparameter Tuning Demo completed!")
        return True

def main():
    """Main function to run the demo."""
    demo = XGBoostTuningDemo()
    
    try:
        success = demo.run_full_demo()
        if success:
            logger.info("✅ Demo completed successfully!")
        else:
            logger.error("❌ Demo completed with errors")
    except KeyboardInterrupt:
        logger.info("⏹️ Demo interrupted by user")
    except Exception as e:
        logger.error(f"❌ Demo failed with unexpected error: {e}")

if __name__ == "__main__":
    main()
