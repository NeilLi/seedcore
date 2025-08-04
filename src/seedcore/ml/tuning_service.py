"""
Hyperparameter Tuning Service for SeedCore ML Models

This module provides hyperparameter tuning functionality using Ray Tune,
specifically for XGBoost models in the SeedCore platform.
"""

import ray
import requests
import logging
import time
import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from ray import tune
from ray.tune.schedulers import ASHAScheduler
from ray.tune.search.basic_variant import BasicVariantGenerator

from .tuning_config import get_search_space, get_tune_config
from .models.xgboost_service import get_xgboost_service, XGBoostConfig, TrainingConfig
from ..memory.flashbulb_client import FlashbulbClient

logger = logging.getLogger(__name__)

def tune_xgb_trainable(config: Dict[str, Any]) -> None:
    """
    A Ray Tune trainable function that directly trains XGBoost models.
    
    This function is called by Ray Tune for each trial with a different
    hyperparameter configuration.
    
    Args:
        config: Hyperparameter configuration sampled by Ray Tune
    """
    # Generate a simple trial ID for logging
    trial_id = f"trial_{int(time.time() * 1000) % 10000}"
    
    try:
        logger.info(f"🚀 Starting trial {trial_id} with config: {config}")
        
        # Import XGBoost service directly
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service, XGBoostConfig, TrainingConfig
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Create sample dataset for consistency across trials
        dataset = xgb_service.create_sample_dataset(n_samples=1000, n_features=10)
        
        # Convert config to XGBoostConfig (only include supported parameters)
        xgb_config = XGBoostConfig(
            objective=config.get("objective", "binary:logistic"),
            eval_metric=config.get("eval_metric", ["logloss", "auc"]),
            eta=config.get("eta", 0.1),
            max_depth=config.get("max_depth", 5),
            tree_method=config.get("tree_method", "hist"),
            num_boost_round=config.get("num_boost_round", 50),
            early_stopping_rounds=config.get("early_stopping_rounds", 10)
        )
        
        # Create training config
        training_config = TrainingConfig(
            num_workers=1,  # Use single worker for tuning trials
            use_gpu=False,
            cpu_per_worker=1,
            memory_per_worker=1000000000  # 1GB per worker
        )
        
        # Train the model
        logger.info(f"📡 Training model for trial {trial_id}")
        start_time = time.time()
        
        result = xgb_service.train_model(
            dataset=dataset,
            label_column="target",
            xgb_config=xgb_config,
            training_config=training_config,
            model_name=f"tune_trial_{trial_id}"
        )
        
        training_time = time.time() - start_time
        
        # Extract metrics
        metrics = result.get("metrics", {})
        auc = metrics.get("validation_0-auc", 0.0)
        logloss = metrics.get("validation_0-logloss", float('inf'))
        
        logger.info(f"✅ Trial {trial_id} completed - AUC: {auc:.4f}, LogLoss: {logloss:.4f}, Time: {training_time:.2f}s")
        
        # Report the score back to Ray Tune
        logger.info(f"📊 Reporting metrics for trial {trial_id}: mean_accuracy={auc}, logloss={logloss}")
        
        # In modern Ray Tune, we return the metrics instead of using tune.report
        return {
            "mean_accuracy": auc,
            "logloss": logloss,
            "training_time": training_time,
            "trial_id": trial_id
        }
        
    except Exception as e:
        logger.error(f"❌ Trial {trial_id} failed with error: {e}")
        # Report failure by returning metrics with 0 accuracy
        logger.info(f"📊 Reporting failure for trial {trial_id}: mean_accuracy=0.0")
        return {
            "mean_accuracy": 0.0,
            "logloss": float('inf'),
            "training_time": 0.0,
            "trial_id": trial_id
        }

class HyperparameterTuningService:
    """
    Service for orchestrating hyperparameter tuning with Ray Tune.
    
    This service provides:
    - Hyperparameter sweep orchestration
    - Trial management and monitoring
    - Best model promotion
    - Integration with SeedCore ML pipeline
    """
    
    def __init__(self, model_storage_path: str = "/data/models"):
        """
        Initialize the hyperparameter tuning service.
        
        Args:
            model_storage_path: Path to store trained models
        """
        self.model_storage_path = Path(model_storage_path)
        self.model_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize Ray if not already initialized
        if not ray.is_initialized():
            try:
                # Try to connect to existing Ray cluster
                ray.init(address="ray://localhost:10001", log_to_driver=False)
                logger.info("✅ Connected to existing Ray cluster")
            except Exception as e:
                logger.warning(f"⚠️ Failed to connect to existing Ray cluster: {e}")
                try:
                    # Try alternative address format
                    ray.init(address="localhost:10001", log_to_driver=False)
                    logger.info("✅ Connected to Ray cluster with alternative address")
                except Exception as e2:
                    logger.warning(f"⚠️ Failed to connect with alternative address: {e2}")
                    # Fallback to local initialization
                    ray.init()
                    logger.info("✅ Initialized local Ray instance")
        
        # Initialize flashbulb client for logging high-impact events
        try:
            self.flashbulb_client = FlashbulbClient()
            logger.info("✅ FlashbulbClient initialized for tuning service")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize FlashbulbClient: {e}")
            self.flashbulb_client = None
    
    def run_tuning_sweep(
        self,
        space_type: str = "default",
        config_type: str = "default",
        custom_search_space: Optional[Dict[str, Any]] = None,
        custom_tune_config: Optional[Dict[str, Any]] = None,
        experiment_name: str = "xgboost_tuning"
    ) -> Dict[str, Any]:
        """
        Run a hyperparameter tuning sweep using Ray Tune.
        
        Args:
            space_type: Type of search space ("default", "conservative", "aggressive")
            config_type: Type of tuning config ("default", "conservative", "aggressive")
            custom_search_space: Custom search space (overrides space_type)
            custom_tune_config: Custom tuning config (overrides config_type)
            experiment_name: Name for the tuning experiment
            
        Returns:
            Dictionary containing tuning results and best model information
        """
        try:
            logger.info(f"🎯 Starting hyperparameter tuning sweep: {experiment_name}")
            logger.info(f"🔍 Ray initialized: {ray.is_initialized()}")
            if ray.is_initialized():
                logger.info(f"🔍 Ray address: {ray.get_runtime_context().gcs_address}")
                logger.info(f"🔍 Available resources: {ray.available_resources()}")
            
            # Get search space and tuning configuration
            search_space = custom_search_space or get_search_space(space_type)
            tune_config_dict = custom_tune_config or get_tune_config(config_type)
            
            # Convert dictionary format search space to Ray Tune format if needed
            if custom_search_space and isinstance(custom_search_space, dict):
                search_space = self._convert_dict_to_tune_space(custom_search_space)
            
            logger.info(f"📊 Search space type: {space_type}")
            logger.info(f"⚙️ Tuning config type: {config_type}")
            logger.info(f"🔍 Number of samples: {tune_config_dict['num_samples']}")
            
            # Create ASHA scheduler for early stopping
            scheduler = ASHAScheduler(
                metric="mean_accuracy",
                mode="max",
                max_t=tune_config_dict.get("max_t", 200),
                grace_period=tune_config_dict["grace_period"],
                reduction_factor=tune_config_dict["reduction_factor"]
            )
            
            # Create search algorithm
            search_alg = BasicVariantGenerator(max_concurrent=tune_config_dict["max_concurrent_trials"])
            
            # Configure the tuner
            # Note: In modern Ray Tune, experiment name and local_dir are handled differently
            # We'll use the default local_dir and let Ray handle the experiment naming
            tuner = tune.Tuner(
                tune_xgb_trainable,
                param_space=search_space,
                tune_config=tune.TuneConfig(
                    num_samples=tune_config_dict["num_samples"],
                    scheduler=scheduler,
                    search_alg=search_alg,
                    time_budget_s=tune_config_dict["time_budget_s"],
                    max_concurrent_trials=tune_config_dict["max_concurrent_trials"],
                )
            )
            
            # Run the tuning sweep
            logger.info("🚀 Starting tuning sweep...")
            logger.info(f"📁 Experiment name: {experiment_name}")
            results = tuner.fit()
            
            # Get the best result
            best_result = results.get_best_result(metric="mean_accuracy", mode="max")
            
            logger.info(f"🏆 Best trial achieved AUC: {best_result.metrics.get('mean_accuracy', 0):.4f}")
            logger.info(f"📈 Best trial config: {best_result.config}")
            
            # Promote the best model
            promotion_result = self._promote_best_model(best_result, experiment_name)
            
            # Log successful tuning to flashbulb memory
            self._log_tuning_success(best_result, experiment_name, promotion_result)
            
            return {
                "status": "success",
                "experiment_name": experiment_name,
                "best_trial": {
                    "trial_id": best_result.metrics.get("trial_id"),
                    "auc": best_result.metrics.get("mean_accuracy"),
                    "logloss": best_result.metrics.get("logloss"),
                    "training_time": best_result.metrics.get("training_time"),
                    "config": best_result.config,
                },
                "promotion": promotion_result,
                "total_trials": len(results),
                "experiment_path": str(best_result.path) if hasattr(best_result, 'path') else "~/ray_results"
            }
            
        except Exception as e:
            logger.error(f"❌ Tuning sweep failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "experiment_name": experiment_name
            }
    
    def _promote_best_model(self, best_result, experiment_name: str) -> Dict[str, Any]:
        """
        Promote the best model from the tuning sweep to a stable location.
        
        Args:
            best_result: Best trial result from Ray Tune
            experiment_name: Name of the tuning experiment
            
        Returns:
            Dictionary containing promotion results
        """
        try:
            # Get the best model path from the trial
            trial_id = best_result.metrics.get("trial_id", "unknown")
            best_model_name = f"tune_trial_{trial_id}"
            
            # Source model path (from the trial)
            source_model_path = self.model_storage_path / best_model_name / "model.xgb"
            
            # Define a stable, "blessed" path for the best model
            blessed_model_name = f"utility_risk_model_latest"
            blessed_model_path = self.model_storage_path / blessed_model_name / "model.xgb"
            blessed_model_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy the model to the stable path
            if source_model_path.exists():
                shutil.copy2(source_model_path, blessed_model_path)
                logger.info(f"✅ Model promoted to: {blessed_model_path}")
                
                # Create metadata file with tuning information
                metadata = {
                    "promoted_from": str(source_model_path),
                    "experiment_name": experiment_name,
                    "trial_id": trial_id,
                    "promotion_timestamp": time.time(),
                    "best_config": best_result.config,
                    "best_metrics": {
                        "auc": best_result.metrics.get("mean_accuracy"),
                        "logloss": best_result.metrics.get("logloss"),
                        "training_time": best_result.metrics.get("training_time")
                    }
                }
                
                metadata_path = blessed_model_path.parent / "tuning_metadata.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                return {
                    "status": "success",
                    "source_path": str(source_model_path),
                    "blessed_path": str(blessed_model_path),
                    "metadata_path": str(metadata_path)
                }
            else:
                logger.error(f"❌ Source model not found: {source_model_path}")
                return {
                    "status": "error",
                    "error": f"Source model not found: {source_model_path}"
                }
                
        except Exception as e:
            logger.error(f"❌ Model promotion failed: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def get_tuning_history(self, experiment_name: str = None) -> List[Dict[str, Any]]:
        """
        Get the history of tuning experiments.
        
        Args:
            experiment_name: Optional specific experiment name
            
        Returns:
            List of tuning experiment results
        """
        try:
            # This would typically query Ray Tune's experiment tracking
            # For now, we'll return a simple structure
            return []
        except Exception as e:
            logger.error(f"❌ Failed to get tuning history: {e}")
            return []
    
    def _log_tuning_success(self, best_result, experiment_name: str, promotion_result: Dict[str, Any]) -> None:
        """
        Log a successful tuning run to flashbulb memory.
        
        Args:
            best_result: Best trial result from Ray Tune
            experiment_name: Name of the tuning experiment
            promotion_result: Result of model promotion
        """
        if self.flashbulb_client is None:
            logger.warning("⚠️ FlashbulbClient not available, skipping event logging")
            return
        
        try:
            # Create flashbulb event data
            event_data = {
                "event_type": "model_tuning_completed",
                "timestamp": time.time(),
                "outcome": "success",
                "experiment_name": experiment_name,
                "best_model_path": promotion_result.get("blessed_path"),
                "metric_achieved": {
                    "auc": best_result.metrics.get("mean_accuracy", 0.0),
                    "logloss": best_result.metrics.get("logloss", float('inf'))
                },
                "best_params": best_result.config,
                "trial_id": best_result.metrics.get("trial_id"),
                "promotion_status": promotion_result.get("status"),
                "total_trials": len(best_result.metrics) if hasattr(best_result, 'metrics') else 0
            }
            
            # Calculate salience score based on performance improvement
            auc_score = best_result.metrics.get("mean_accuracy", 0.0)
            # High salience for AUC > 0.95, medium for > 0.90, low for > 0.85
            if auc_score > 0.95:
                salience = 0.95
            elif auc_score > 0.90:
                salience = 0.85
            elif auc_score > 0.85:
                salience = 0.75
            else:
                salience = 0.60
            
            # Log to flashbulb memory
            success = self.flashbulb_client.log_incident(event_data, salience)
            
            if success:
                logger.info(f"✅ Tuning success logged to flashbulb memory with salience {salience}")
            else:
                logger.warning("⚠️ Failed to log tuning success to flashbulb memory")
                
        except Exception as e:
            logger.error(f"❌ Error logging tuning success to flashbulb memory: {e}")
    
    def _convert_dict_to_tune_space(self, search_space_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert dictionary format search space to Ray Tune format.
        
        Args:
            search_space_dict: Dictionary with search space parameters
            
        Returns:
            Dictionary with Ray Tune search space objects
        """
        converted_space = {}
        
        for key, value in search_space_dict.items():
            if isinstance(value, dict) and "type" in value:
                # Convert dictionary format to Ray Tune objects
                if value["type"] == "loguniform":
                    converted_space[key] = tune.loguniform(value["lower"], value["upper"])
                elif value["type"] == "uniform":
                    converted_space[key] = tune.uniform(value["lower"], value["upper"])
                elif value["type"] == "randint":
                    converted_space[key] = tune.randint(value["lower"], value["upper"])
                elif value["type"] == "choice":
                    converted_space[key] = tune.choice(value["choices"])
                else:
                    # Keep as is if type is not recognized
                    converted_space[key] = value
            else:
                # Keep non-dictionary values as is
                converted_space[key] = value
        
        return converted_space

def get_tuning_service() -> HyperparameterTuningService:
    """
    Get a singleton instance of the hyperparameter tuning service.
    
    Returns:
        HyperparameterTuningService instance
    """
    if not hasattr(get_tuning_service, '_instance'):
        get_tuning_service._instance = HyperparameterTuningService()
    return get_tuning_service._instance 