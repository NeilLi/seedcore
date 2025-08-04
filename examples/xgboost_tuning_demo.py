#!/usr/bin/env python3
"""
XGBoost Hyperparameter Tuning Demo for SeedCore

This script demonstrates the new hyperparameter tuning functionality
using Ray Tune, integrated with the Cognitive Organism Architecture.
"""

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
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = requests.Session()
    
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
            response = self.session.post(f"{self.base_url}/xgboost/train", json=payload)
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
            response = self.session.post(f"{self.base_url}/xgboost/tune", json=payload)
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
    
    def test_default_tuning(self) -> bool:
        """Test default hyperparameter tuning."""
        logger.info("🎯 Testing default hyperparameter tuning...")
        
        payload = {
            "space_type": "default",
            "config_type": "default",
            "experiment_name": "demo_default_tuning"
        }
        
        try:
            response = self.session.post(f"{self.base_url}/xgboost/tune", json=payload)
            response.raise_for_status()
            result = response.json()
            
            if result.get("status") == "success":
                best_trial = result.get("best_trial", {})
                logger.info(f"✅ Default tuning successful!")
                logger.info(f"   Best AUC: {best_trial.get('auc', 'N/A'):.4f}")
                logger.info(f"   Total trials: {result.get('total_trials', 'N/A')}")
                logger.info(f"   Best config: {best_trial.get('config', {})}")
                return True
            else:
                logger.error(f"❌ Default tuning failed: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Default tuning failed: {e}")
            return False
    
    def test_custom_tuning(self) -> bool:
        """Test custom hyperparameter tuning with specific parameters."""
        logger.info("🎯 Testing custom hyperparameter tuning...")
        
        # Custom search space (using dictionary format for JSON serialization)
        custom_search_space = {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "tree_method": "hist",
            "eta": {"type": "loguniform", "lower": 0.01, "upper": 0.3},
            "max_depth": {"type": "randint", "lower": 3, "upper": 8},
            "subsample": {"type": "uniform", "lower": 0.7, "upper": 1.0},
            "colsample_bytree": {"type": "uniform", "lower": 0.7, "upper": 1.0},
            "lambda": {"type": "uniform", "lower": 0.1, "upper": 3.0},
            "alpha": {"type": "uniform", "lower": 0.0, "upper": 2.0},
            "num_boost_round": 100,
            "early_stopping_rounds": 10
        }
        
        # Custom tuning config
        custom_tune_config = {
            "num_samples": 10,
            "max_concurrent_trials": 2,
            "time_budget_s": 600,  # 10 minutes
            "grace_period": 5,
            "reduction_factor": 2
        }
        
        payload = {
            "custom_search_space": custom_search_space,
            "custom_tune_config": custom_tune_config,
            "experiment_name": "demo_custom_tuning"
        }
        
        try:
            response = self.session.post(f"{self.base_url}/xgboost/tune", json=payload)
            response.raise_for_status()
            result = response.json()
            
            if result.get("status") == "success":
                best_trial = result.get("best_trial", {})
                logger.info(f"✅ Custom tuning successful!")
                logger.info(f"   Best AUC: {best_trial.get('auc', 'N/A'):.4f}")
                logger.info(f"   Total trials: {result.get('total_trials', 'N/A')}")
                logger.info(f"   Best config: {best_trial.get('config', {})}")
                return True
            else:
                logger.error(f"❌ Custom tuning failed: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Custom tuning failed: {e}")
            return False
    
    def test_model_refresh(self) -> bool:
        """Test model refresh functionality."""
        logger.info("🔄 Testing model refresh...")
        
        try:
            response = self.session.post(f"{self.base_url}/xgboost/refresh_model")
            response.raise_for_status()
            result = response.json()
            
            if result.get("status") == "success":
                logger.info(f"✅ Model refresh successful!")
                logger.info(f"   Current model path: {result.get('current_model_path', 'N/A')}")
                return True
            else:
                logger.warning(f"⚠️ Model refresh warning: {result.get('message', 'Unknown warning')}")
                return True  # Not necessarily a failure
                
        except Exception as e:
            logger.error(f"❌ Model refresh failed: {e}")
            return False
    
    def test_prediction_with_tuned_model(self) -> bool:
        """Test prediction using the tuned model."""
        logger.info("🔮 Testing prediction with tuned model...")
        
        # Sample features (10 features for our demo)
        features = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        
        payload = {
            "features": features
        }
        
        try:
            response = self.session.post(f"{self.base_url}/xgboost/predict", json=payload)
            response.raise_for_status()
            result = response.json()
            
            if result.get("status") == "success":
                prediction = result.get("prediction", "N/A")
                logger.info(f"✅ Prediction successful!")
                logger.info(f"   Prediction: {prediction}")
                logger.info(f"   Model path: {result.get('path', 'N/A')}")
                return True
            else:
                logger.error(f"❌ Prediction failed: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Prediction failed: {e}")
            return False
    
    def run_full_demo(self) -> bool:
        """Run the complete hyperparameter tuning demo."""
        logger.info("🚀 Starting XGBoost Hyperparameter Tuning Demo")
        logger.info("=" * 60)
        
        # Test basic functionality first
        if not self.test_basic_training():
            logger.error("❌ Basic training failed, aborting demo")
            return False
        
        # Test conservative tuning
        if not self.test_conservative_tuning():
            logger.warning("⚠️ Conservative tuning failed, continuing with other tests")
        
        # Test default tuning
        if not self.test_default_tuning():
            logger.warning("⚠️ Default tuning failed, continuing with other tests")
        
        # Test custom tuning
        if not self.test_custom_tuning():
            logger.warning("⚠️ Custom tuning failed, continuing with other tests")
        
        # Test model refresh
        if not self.test_model_refresh():
            logger.warning("⚠️ Model refresh failed, continuing with other tests")
        
        # Test prediction
        if not self.test_prediction_with_tuned_model():
            logger.warning("⚠️ Prediction failed")
        
        logger.info("=" * 60)
        logger.info("🎉 XGBoost Hyperparameter Tuning Demo completed!")
        logger.info("📊 Check the Ray Dashboard at http://localhost:8265 for detailed tuning results")
        logger.info("🧠 Check flashbulb memory for logged tuning events")
        
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