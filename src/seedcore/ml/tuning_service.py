"""
Hyperparameter Tuning Service for SeedCore ML Models

This module provides hyperparameter tuning functionality using Ray Tune,
specifically for XGBoost models in the SeedCore platform.
"""

from __future__ import annotations

import ray
import requests
import logging
import time
import os
import json
import shutil
from pathlib import Path
from ..utils.ray_utils import ensure_ray_initialized
from typing import Dict, Any, Optional, List, Tuple, Union
from ray import tune
from ray.tune.schedulers import ASHAScheduler
from ray.tune.search.basic_variant import BasicVariantGenerator

from .tuning_config import get_search_space, get_tune_config
from .models.xgboost_service import get_xgboost_service, XGBoostConfig, TrainingConfig
from ..memory.flashbulb_client import FlashbulbClient
from ..predicates.gpu_guard import GPUGuard

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None

logger = logging.getLogger(__name__)

def _validate_dataset(dataset: Any) -> Tuple["pd.DataFrame", str]:
    """
    Accepts a Pandas DataFrame or a dict-like { 'X': df/features, 'y': series/col }.
    Ensures presence of a 'target' label column (or provided y), returns DF and label name.
    Raises ValueError with helpful message if invalid.
    """
    if dataset is None:
        raise ValueError("dataset is None")
    if pd is None:
        raise ValueError("pandas is required for dataset validation but not available")

    # Case 1: already a DataFrame with 'target'
    if isinstance(dataset, pd.DataFrame):
        if "target" not in dataset.columns:
            raise ValueError("dataset DataFrame must contain a 'target' label column")
        return dataset, "target"

    # Case 2: dict-like with X/y
    if isinstance(dataset, dict):
        X = dataset.get("X")
        y = dataset.get("y")
        if X is None or y is None:
            raise ValueError("dict dataset must contain keys 'X' and 'y'")
        if not isinstance(X, pd.DataFrame):
            raise ValueError("'X' must be a pandas DataFrame")
        # bind label
        df = X.copy()
        df["target"] = y
        return df, "target"

    raise ValueError("Unsupported dataset type. Provide a pandas DataFrame or dict with 'X' and 'y'.")

def tune_xgb_trainable(config: Dict[str, Any]) -> None:
    """
    A Ray Tune trainable function that directly trains XGBoost models.
    
    This function is called by Ray Tune for each trial with a different
    hyperparameter configuration.
    
    Args:
        config: Hyperparameter configuration sampled by Ray Tune
    """
    # Get the actual trial ID from Ray Tune
    from ray import tune
    trial_id = tune.get_trial_id() if hasattr(tune, 'get_trial_id') else f"trial_{int(time.time() * 1000) % 10000}"
    
    try:
        logger.info(f"🚀 Starting trial {trial_id} with config: {config}")
        
        # Import XGBoost service directly
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service, XGBoostConfig, TrainingConfig
        from src.seedcore.ml.tuning_service import _validate_dataset  # re-use same helper
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Dataset: prefer externally supplied (via config), else synthetic
        dataset = config.get("_dataset")
        if dataset is None:
            dataset = xgb_service.create_sample_dataset(n_samples=1000, n_features=10)
        dataset, label_col = _validate_dataset(dataset)
        
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
            use_gpu=config.get("_use_gpu", False),
            cpu_per_worker=1,
            memory_per_worker=1000000000  # 1GB per worker
        )
        
        # Train the model
        logger.info(f"📡 Training model for trial {trial_id}")
        start_time = time.time()
        
        result = xgb_service.train_model(
            dataset=dataset,
            label_column=label_col,
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
        logger.exception(f"❌ Trial {trial_id} failed")
        # Emit structured error context (config subset only)
        try:
            err_ctx = {
                "trial_id": trial_id,
                "error_type": type(e).__name__,
                "error": str(e)[:500],
                "config": {k: config.get(k) for k in ["eta","max_depth","subsample","colsample_bytree","num_boost_round"]},
            }
            logger.error(f"[trial_error] {err_ctx}")
        except Exception:
            pass
        # Report failure by returning metrics with 0 accuracy
        logger.info(
            f"📊 Reporting failure for trial {trial_id}: mean_accuracy=0.0"
        )
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
    
    def __init__(self, model_storage_path: str = "/app/data/models"):
        """
        Initialize the hyperparameter tuning service.
        
        Args:
            model_storage_path: Path to store trained models
        """
        self.model_storage_path = Path(model_storage_path)
        self.model_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize Ray if not already initialized
        if not ray.is_initialized():
            # Use the centralized Ray initialization utility
            ray_address = os.getenv("RAY_ADDRESS", "ray://localhost:10001")
            if not ensure_ray_initialized(ray_address=ray_address):
                raise RuntimeError("Failed to initialize Ray connection")
            logger.info("✅ Ray connection established successfully")
        
        # Initialize flashbulb client for logging high-impact events
        try:
            self.flashbulb_client = FlashbulbClient()
            logger.info("✅ FlashbulbClient initialized for tuning service")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize FlashbulbClient: {e}")
            self.flashbulb_client = None

        # Initialize Redis-backed GPU Guard
        try:
            self.gpu_guard = GPUGuard.from_env()
            logger.info(f"✅ GPUGuard ready: {self.gpu_guard.get_status()}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize GPUGuard: {e}")
            self.gpu_guard = GPUGuard(None)  # no-op fallback
    
    def run_tuning_sweep(
        self,
        space_type: str = "default",
        config_type: str = "default",
        custom_search_space: Optional[Dict[str, Any]] = None,
        custom_tune_config: Optional[Dict[str, Any]] = None,
        experiment_name: str = "xgboost_tuning",
        progress_callback: Optional[callable] = None,
        status_actor_handle=None,
        job_id: str = None,
        dataset: Optional[Any] = None,
        expected_gpu_seconds: int = 1800
    ) -> Dict[str, Any]:
        """
        Run a hyperparameter tuning sweep using Ray Tune.
        
        Args:
            space_type: Type of search space ("default", "conservative", "aggressive")
            config_type: Type of tuning config ("default", "conservative", "aggressive")
            custom_search_space: Custom search space (overrides space_type)
            custom_tune_config: Custom tuning config (overrides config_type)
            experiment_name: Name for the tuning experiment
            progress_callback: Optional callback function for progress updates
            status_actor_handle: Optional Ray actor handle for direct status updates
            job_id: Optional job ID for status updates
            dataset: Optional dataset (pd.DataFrame with 'target' or dict{'X','y'})
            expected_gpu_seconds: reservation for GPU budget admission (seconds)
            
        Returns:
            Dictionary containing tuning results and best model information
        """
        try:
            logger.info(f"🎯 Starting hyperparameter tuning sweep: {experiment_name}")

            # GPU Guard admission (resource-bounded by design)
            guard_job_id = job_id or f"tune-{int(time.time())}"
            admit_ok, admit_reason = self.gpu_guard.try_acquire(
                job_id=guard_job_id,
                gpu_seconds_budget=int(expected_gpu_seconds),
            )
            if not admit_ok:
                msg = f"GPUGuard admission rejected: {admit_reason}"
                logger.warning(f"🛑 {msg}")
                raise RuntimeError(msg)
            logger.info(f"✅ GPUGuard admitted job {guard_job_id} ({admit_reason})")
            
            if progress_callback:
                progress_callback("Initializing Ray Tune...")
            
            logger.info(f"🔍 Ray initialized: {ray.is_initialized()}")
            if ray.is_initialized():
                logger.info(f"🔍 Ray address: {ray.get_runtime_context().gcs_address}")
                logger.info(f"🔍 Available resources: {ray.available_resources()}")

            # Validate & attach dataset (if provided)
            label_col = "target"
            attached_dataset = None
            if dataset is not None:
                try:
                    from .tuning_service import _validate_dataset as _vd
                    attached_dataset, label_col = _vd(dataset)
                    logger.info(
                        f"📦 Using custom dataset for tuning (label='{label_col}', rows={len(attached_dataset)})"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Provided dataset invalid ({e}); falling back to synthetic.")
                    attached_dataset = None

            # Get search space and tuning configuration
            search_space = custom_search_space or get_search_space(space_type)
            tune_config_dict = custom_tune_config or get_tune_config(config_type)
            
            # Convert dictionary format search space to Ray Tune format if needed
            if custom_search_space and isinstance(custom_search_space, dict):
                search_space = self._convert_dict_to_tune_space(custom_search_space)
            
            logger.info(f"📊 Search space type: {space_type}")
            logger.info(f"⚙️ Tuning config type: {config_type}")
            logger.info(f"🔍 Number of samples: {tune_config_dict['num_samples']}")
            
            if progress_callback:
                progress_callback(f"Configuring search space with {tune_config_dict['num_samples']} trials...")
            
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
            
            if progress_callback:
                progress_callback("Starting tuning sweep...")

            # Propagate runtime knobs into trainable
            # (dataset, gpu usage hints, etc.)
            search_space["_dataset"] = attached_dataset
            search_space["_use_gpu"] = bool(tune_config_dict.get("use_gpu", False))
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
            sweep_start = time.time()
            total_trials = len(results)
            
            if progress_callback:
                progress_callback("Tuning sweep completed, analyzing results...")
            
            # Get the best result
            best_result = results.get_best_result(metric="mean_accuracy", mode="max")
            
            logger.info(f"🏆 Best trial achieved AUC: {best_result.metrics.get('mean_accuracy', 0):.4f}")
            logger.info(f"📈 Best trial config: {best_result.config}")
            
            if progress_callback:
                progress_callback("Promoting best model...")
            
            # Promote the best model
            promotion_result = self._promote_best_model(best_result, experiment_name)
            
            if progress_callback:
                progress_callback("Logging tuning results...")
            
            # Complete GPU job if GPU Guard is available
            if self.gpu_guard and job_id:
                try:
                    self.gpu_guard.complete_job(job_id, success=True)
                    logger.info(f"✅ Job {job_id} completed in GPU Guard")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to complete job {job_id} in GPU Guard: {e}")
            
            # Log successful tuning to flashbulb memory
            if self.flashbulb_client:
                try:
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
                        "total_trials": total_trials
                    }
                    self.flashbulb_client.log_incident(event_data, 0.8)  # High salience for successful tuning
                    logger.info("✅ Tuning success logged to Flashbulb memory")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to log tuning success to Flashbulb: {e}")
            
            if progress_callback:
                progress_callback("Tuning sweep completed successfully!")
            
            # If we have a status actor handle, update the final status directly
            if status_actor_handle and job_id:
                try:
                    ray.get(status_actor_handle.set_status.remote(job_id, {
                        "status": "COMPLETED",
                        "result": {
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
                            "total_trials": total_trials,
                            "experiment_path": str(best_result.path) if hasattr(best_result, 'path') else "~/ray_results"
                        },
                        "progress": "Tuning sweep completed successfully"
                    }))
                    logger.info(f"✅ Direct status update sent to actor for job {job_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send direct status update to actor: {e}")

            # Mark guard completion (approx wall time as coarse GPU seconds)
            gpu_secs = max(1.0, time.time() - sweep_start)
            self.gpu_guard.complete(guard_job_id, actual_gpu_seconds=gpu_secs, success=True)
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
                "total_trials": total_trials,
                "experiment_path": str(best_result.path) if hasattr(best_result, 'path') else "~/ray_results"
            }
            
        except Exception as e:
            # Ensure guard is released on failure
            guard_job_id = job_id or "unknown"
            self.gpu_guard.complete(guard_job_id, actual_gpu_seconds=0.0, success=False)
            error_msg = f"Tuning sweep failed: {str(e)}"
            logger.error(f"❌ {error_msg}")
            if progress_callback:
                progress_callback(f"Error: {error_msg}")
            
            # If we have a status actor handle, update the error status directly
            if status_actor_handle and job_id:
                try:
                    ray.get(status_actor_handle.set_status.remote(job_id, {
                        "status": "FAILED",
                        "result": {"error": error_msg},
                        "progress": f"Tuning sweep failed: {error_msg}"
                    }))
                    logger.info(f"✅ Direct error status update sent to actor for job {job_id}")
                except Exception as actor_error:
                    logger.warning(f"⚠️ Failed to send direct error status update to actor: {actor_error}")
            
            raise Exception(error_msg)
    
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
            # Ray Tune stores the trial ID in the result object
            trial_id = getattr(best_result, 'trial_id', None)
            if not trial_id:
                # Fallback: try to extract from metrics or generate a unique ID
                trial_id = best_result.metrics.get("trial_id", f"trial_{int(time.time() * 1000) % 10000}")
            
            best_model_name = f"tune_trial_{trial_id}"
            
            # Source model path (from the trial)
            # Ray Tune stores the trial path in the result object
            trial_path = getattr(best_result, 'path', None)
            if trial_path:
                # Use the actual trial path from Ray Tune
                source_model_path = Path(trial_path) / "model.xgb"
            else:
                # Fallback to our storage path
                source_model_path = self.model_storage_path / best_model_name / "model.xgb"
            
            # Define a stable, "blessed" path for the best model
            blessed_model_name = f"utility_risk_model_latest"
            blessed_model_path = self.model_storage_path / blessed_model_name / "model.xgb"
            blessed_model_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Fix race condition: Wait for model file to be available with retry logic
            max_retries = 10
            retry_delay = 2  # seconds
            
            for attempt in range(max_retries):
                if source_model_path.exists():
                    # File exists, proceed with promotion
                    break
                else:
                    logger.info(f"   Waiting for model file (attempt {attempt + 1}/{max_retries}): {source_model_path}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        # Also check for alternative model file locations
                        if trial_path:
                            trial_dir = Path(trial_path)
                            if trial_dir.exists():
                                # Look for any .xgb files in the trial directory
                                model_files = list(trial_dir.glob("*.xgb"))
                                if model_files:
                                    source_model_path = model_files[0]
                                    logger.info(f"   Found alternative model file: {source_model_path}")
                                    break
            else:
                # All retries exhausted
                logger.error(f"❌ Model file not found after {max_retries} retries: {source_model_path}")
                return {
                    "status": "error",
                    "error": f"Model file not found after {max_retries} retries: {source_model_path}"
                }
            
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
                logger.error(f"   Trial path: {trial_path}")
                logger.error(f"   Trial ID: {trial_id}")
                logger.error(f"   Best result type: {type(best_result)}")
                logger.error(f"   Best result attributes: {dir(best_result)}")
                
                # Try to find any model files in the trial directory
                if trial_path:
                    trial_dir = Path(trial_path)
                    if trial_dir.exists():
                        model_files = list(trial_dir.glob("*.xgb"))
                        logger.info(f"   Found model files in trial directory: {model_files}")
                        
                        if model_files:
                            # Use the first model file found
                            source_model_path = model_files[0]
                            shutil.copy2(source_model_path, blessed_model_path)
                            logger.info(f"✅ Model promoted from alternative path: {source_model_path}")
                            
                            return {
                                "status": "success",
                                "source_path": str(source_model_path),
                                "blessed_path": str(blessed_model_path),
                                "note": "Used alternative model path"
                            }
                
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