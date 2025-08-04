"""
XGBoost Service for SeedCore ML Platform

This module provides distributed XGBoost training and inference using Ray Data.
It integrates seamlessly with the existing SeedCore ML service architecture.
"""

import ray
import pandas as pd
import numpy as np
import xgboost as xgb
import logging
import time
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass
from xgboost_ray import RayDMatrix, train
from ray.air.config import ScalingConfig
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split
import tempfile

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class XGBoostConfig:
    """Configuration for XGBoost training."""
    objective: str = "binary:logistic"
    eval_metric: List[str] = None
    eta: float = 0.1
    max_depth: int = 5
    tree_method: str = "hist"
    num_boost_round: int = 50
    early_stopping_rounds: int = 10
    
    def __post_init__(self):
        if self.eval_metric is None:
            self.eval_metric = ["logloss", "auc"]

@dataclass
class TrainingConfig:
    """Configuration for distributed training."""
    num_workers: int = 3
    use_gpu: bool = False
    cpu_per_worker: int = 1
    memory_per_worker: int = 2000000000  # 2GB
    
    def to_scaling_config(self) -> ScalingConfig:
        """Convert to Ray ScalingConfig."""
        return ScalingConfig(
            num_workers=self.num_workers,
            use_gpu=self.use_gpu,
            resources_per_worker={
                "CPU": self.cpu_per_worker,
                "memory": self.memory_per_worker
            }
        )

class XGBoostService:
    """
    XGBoost service for distributed training and inference using Ray Data.
    
    This service provides:
    - Distributed training using Ray Data and xgboost_ray
    - Model persistence and loading
    - Batch and real-time inference
    - Integration with SeedCore ML pipeline
    """
    
    def __init__(self, model_storage_path: str = "/data/models"):
        """
        Initialize XGBoost service.
        
        Args:
            model_storage_path: Path to store trained models
        """
        self.model_storage_path = Path(model_storage_path)
        self.model_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize Ray if not already initialized
        # When running in the Ray head container, we should connect to the existing Ray instance
        if not ray.is_initialized():
            # Check if we're in the Ray head container by looking for Ray processes
            import subprocess
            try:
                result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
                if 'ray' in result.stdout and ('gcs_server' in result.stdout or 'raylet' in result.stdout):
                    # We're in the head container, connect to the existing Ray instance
                    ray.init()
                    logger.info("✅ Connected to existing Ray instance in head container")
                else:
                    # We're in a worker or external environment, connect via RAY_ADDRESS
                    ray_address = os.getenv("RAY_ADDRESS")
                    if ray_address:
                        ray.init(address=ray_address, log_to_driver=False)
                        logger.info(f"✅ Connected to Ray cluster at {ray_address}")
                    else:
                        # Fallback to local initialization if RAY_ADDRESS not set
                        ray.init()
                        logger.info("✅ Connected to local Ray instance")
            except Exception:
                # Fallback to simple initialization
                ray.init()
                logger.info("✅ Connected to Ray instance (fallback)")
        else:
            logger.info("✅ Ray is already initialized, skipping initialization")
        
        # Model state
        self.current_model = None
        self.current_model_path = None
        self.model_metadata = {}
        
        logger.info(f"✅ XGBoostService initialized with model storage: {self.model_storage_path}")
    
    def create_sample_dataset(self, n_samples: int = 10000, n_features: int = 20) -> ray.data.Dataset:
        """
        Create a sample dataset for testing and demonstration.
        
        Args:
            n_samples: Number of samples
            n_features: Number of features
            
        Returns:
            Ray Dataset with synthetic data
        """
        logger.info(f"Creating sample dataset with {n_samples} samples and {n_features} features")
        
        # Generate synthetic data
        X, y = make_classification(
            n_samples=n_samples,
            n_features=n_features,
            n_informative=min(10, n_features),
            n_redundant=max(0, n_features - 10),
            random_state=42
        )
        
        # Create DataFrame
        feature_cols = [f"feature_{i}" for i in range(n_features)]
        df = pd.DataFrame(X, columns=feature_cols)
        df["target"] = y
        
        # Convert to Ray Dataset
        dataset = ray.data.from_pandas(df)
        
        logger.info(f"✅ Created Ray Dataset with {dataset.count()} samples")
        return dataset
    
    def load_dataset_from_source(self, source_path: str, format: str = "auto") -> ray.data.Dataset:
        """
        Load dataset from various sources (CSV, Parquet, etc.).
        
        Args:
            source_path: Path to data source
            format: Data format ('csv', 'parquet', 'auto')
            
        Returns:
            Ray Dataset
        """
        logger.info(f"Loading dataset from: {source_path}")
        
        try:
            if format == "auto":
                if source_path.endswith('.csv'):
                    dataset = ray.data.read_csv(source_path)
                elif source_path.endswith('.parquet'):
                    dataset = ray.data.read_parquet(source_path)
                else:
                    # Try to infer format
                    dataset = ray.data.read_csv(source_path)
            elif format == "csv":
                dataset = ray.data.read_csv(source_path)
            elif format == "parquet":
                dataset = ray.data.read_parquet(source_path)
            else:
                raise ValueError(f"Unsupported format: {format}")
            
            logger.info(f"✅ Loaded dataset with {dataset.count()} samples")
            return dataset
            
        except Exception as e:
            logger.error(f"Failed to load dataset from {source_path}: {e}")
            raise
    
    def train_model(
        self,
        dataset: ray.data.Dataset,
        label_column: str = "target",
        feature_columns: Optional[List[str]] = None,
        xgb_config: Optional[XGBoostConfig] = None,
        training_config: Optional[TrainingConfig] = None,
        model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Train XGBoost model using distributed Ray training.
        
        Args:
            dataset: Ray Dataset for training
            label_column: Name of the target column
            xgb_config: XGBoost hyperparameters
            training_config: Distributed training configuration
            model_name: Optional name for the model
            
        Returns:
            Training result with model path and metrics
        """
        start_time = time.time()
        
        # Set default configurations
        if xgb_config is None:
            xgb_config = XGBoostConfig()
        
        if training_config is None:
            training_config = TrainingConfig()
        
        if model_name is None:
            model_name = f"xgboost_model_{int(time.time())}"
        
        # Extract feature columns if not provided
        if feature_columns is None:
            # Get schema from dataset to extract feature columns
            schema = dataset.schema()
            if hasattr(schema, 'names'):
                # Ray Dataset schema
                feature_columns = [col for col in schema.names if col != label_column]
            else:
                # Fallback: take a sample to get columns
                sample_df = dataset.take(1)[0]
                if isinstance(sample_df, dict):
                    feature_columns = [col for col in sample_df.keys() if col != label_column]
                else:
                    # Assume it's a pandas DataFrame
                    feature_columns = [col for col in sample_df.columns if col != label_column]
        
        logger.info(f"📊 Training with {len(feature_columns)} features: {feature_columns[:5]}{'...' if len(feature_columns) > 5 else ''}")
        
        logger.info(f"🚀 Starting distributed XGBoost training with {training_config.num_workers} workers")
        
        try:
            # Configure XGBoost parameters
            xgb_params = {
                "tree_method": xgb_config.tree_method,
                "objective": xgb_config.objective,
                "eval_metric": xgb_config.eval_metric,
                "eta": xgb_config.eta,
                "max_depth": xgb_config.max_depth,
            }
            
            # Convert Ray Dataset to RayDMatrix
            logger.info("Converting dataset to RayDMatrix...")
            dtrain = RayDMatrix(
                data=dataset,
                label=label_column,
                num_actors=training_config.num_workers
            )
            
            # Execute distributed training with fallback to local training
            logger.info("Training in progress...")
            
            try:
                # Try distributed training first
                logger.info("Attempting distributed training...")
                result = train(
                    params=xgb_params,
                    dtrain=dtrain,
                    num_boost_round=xgb_config.num_boost_round,
                    ray_params={
                        "num_actors": training_config.num_workers,
                        "cpus_per_actor": training_config.cpu_per_worker,
                        "gpus_per_actor": 1 if training_config.use_gpu else 0,
                    }
                )
                logger.info("✅ Distributed training completed successfully")
                
            except Exception as e:
                logger.warning(f"❌ Distributed training failed: {e}")
                logger.info("🔄 Falling back to local XGBoost training...")
                
                # Fallback to local training using standard XGBoost
                import xgboost as xgb
                import pandas as pd
                
                # Convert Ray Dataset to pandas DataFrame for local training
                logger.info("Converting Ray Dataset to pandas DataFrame...")
                df_list = dataset.take_all()
                # Convert each item to DataFrame if it's a dict
                df_list = [pd.DataFrame([item]) if isinstance(item, dict) else item for item in df_list]
                df = pd.concat(df_list, ignore_index=True)
                
                # Prepare data for XGBoost
                X = df.drop(columns=[label_column])
                y = df[label_column]
                
                # Create DMatrix
                dtrain_local = xgb.DMatrix(X, label=y)
                
                # Train locally
                logger.info("Training XGBoost model locally...")
                # Ensure eval_metric is properly formatted for local training
                local_params = xgb_params.copy()
                if isinstance(local_params.get('eval_metric'), list):
                    local_params['eval_metric'] = local_params['eval_metric'][0]  # Use first metric
                
                bst = xgb.train(
                    local_params,
                    dtrain_local,
                    num_boost_round=xgb_config.num_boost_round
                )
                
                # Create a mock result object to maintain compatibility
                class MockResult:
                    def __init__(self, booster):
                        self.booster = booster
                        self.checkpoint = type('obj', (object,), {
                            'to_xgboost': lambda: booster
                        })()
                    
                    def save_model(self, path):
                        """Save the model to the specified path."""
                        self.booster.save_model(path)
                    
                    def predict(self, dmatrix):
                        """Predict using the booster."""
                        return self.booster.predict(dmatrix)
                
                result = MockResult(bst)
                logger.info("✅ Local training completed successfully")
            
            # Save model
            model_path = self._save_model(result, model_name)
            
            # Update service state
            self.current_model = result
            self.current_model_path = model_path
            
            # Store metadata
            self.model_metadata = {
                "name": model_name,
                "path": str(model_path),
                "training_time": time.time() - start_time,
                "metrics": {"status": "completed"},  # xgboost-ray train doesn't return detailed metrics
                "feature_columns": feature_columns,  # Store feature columns for validation
                "config": {
                    "xgb_config": xgb_config.__dict__,
                    "training_config": training_config.__dict__
                }
            }
            
            logger.info(f"✅ Training completed in {self.model_metadata['training_time']:.2f}s")
            logger.info(f"Model saved to: {model_path}")
            
            return {
                "status": "success",
                "path": str(model_path),
                "name": model_name,
                "training_time": self.model_metadata['training_time'],
                "metrics": {"status": "completed"},
                "config": self.model_metadata['config']
            }
            
        except Exception as e:
            logger.error(f"❌ Training failed: {e}")
            raise
    
    def _save_model(self, result, model_name: str) -> Path:
        """Save trained model to storage."""
        model_dir = self.model_storage_path / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        
        # Save XGBoost model
        model_path = model_dir / "model.xgb"
        result.save_model(str(model_path))
        
        # Save metadata
        metadata_path = model_dir / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(self.model_metadata, f, indent=2)
        
        return model_path
    
    def load_model(self, model_path: str) -> bool:
        """
        Load a trained XGBoost model.
        
        Args:
            model_path: Path to the model file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Loading model from: {model_path}")
            
            # Load XGBoost model
            self.current_model = xgb.Booster()
            self.current_model.load_model(model_path)
            
            # Load metadata if available
            metadata_path = Path(model_path).parent / "metadata.json"
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    self.model_metadata = json.load(f)
            
            self.current_model_path = model_path
            
            logger.info("✅ Model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            return False
    
    def predict(self, features: Union[List, np.ndarray, pd.DataFrame]) -> np.ndarray:
        """
        Make predictions using the loaded model.
        
        Args:
            features: Input features (list, numpy array, or pandas DataFrame)
            
        Returns:
            Predictions as numpy array
        """
        if self.current_model is None:
            raise ValueError("No model loaded. Please load a model first.")
        
        try:
            # Convert input to DMatrix
            if isinstance(features, list):
                features = np.array(features)
            
            if isinstance(features, pd.DataFrame):
                features = features.values
            
            # Ensure 2D array
            if features.ndim == 1:
                features = features.reshape(1, -1)
            
            # Get actual feature names from the loaded XGBoost model
            if hasattr(self.current_model, 'feature_names') and self.current_model.feature_names:
                feature_names = self.current_model.feature_names
                if len(feature_names) != features.shape[1]:
                    logger.warning(f"⚠️  Feature count mismatch: expected {len(feature_names)}, got {features.shape[1]}")
                    # Fallback to default names
                    feature_names = [f"feature_{i}" for i in range(features.shape[1])]
            else:
                # Fallback to metadata if model doesn't have feature names
                if hasattr(self, 'model_metadata') and self.model_metadata.get('feature_columns'):
                    feature_names = self.model_metadata['feature_columns']
                    if len(feature_names) != features.shape[1]:
                        logger.warning(f"⚠️  Feature count mismatch: expected {len(feature_names)}, got {features.shape[1]}")
                        # Fallback to default names
                        feature_names = [f"feature_{i}" for i in range(features.shape[1])]
                else:
                    # Create default feature names
                    n_features = features.shape[1]
                    feature_names = [f"feature_{i}" for i in range(n_features)]
            
            # Create DMatrix with feature names
            dmatrix = xgb.DMatrix(features, feature_names=feature_names)
            
            # Make prediction
            predictions = self.current_model.predict(dmatrix)
            
            return predictions
            
        except Exception as e:
            logger.error(f"❌ Prediction failed: {e}")
            raise
    
    def batch_predict(self, dataset: ray.data.Dataset, feature_columns: List[str]) -> ray.data.Dataset:
        """
        Make batch predictions on a Ray Dataset.
        
        Args:
            dataset: Ray Dataset to predict on
            feature_columns: List of feature column names
            
        Returns:
            Ray Dataset with predictions added
        """
        if self.current_model is None:
            raise ValueError("No model loaded. Please load a model first.")
        
        # Ensure feature_columns is a list of strings
        if not isinstance(feature_columns, list):
            feature_columns = list(feature_columns)
        
        # Get actual feature names from the loaded XGBoost model
        if hasattr(self.current_model, 'feature_names'):
            expected_features = self.current_model.feature_names
            if expected_features:
                missing_features = set(expected_features) - set(feature_columns)
                extra_features = set(feature_columns) - set(expected_features)
                
                if missing_features:
                    raise ValueError(f"❌ Batch prediction failed: Missing required features: {list(missing_features)}")
                
                if extra_features:
                    logger.warning(f"⚠️  Extra features provided (will be ignored): {list(extra_features)}")
                
                # Ensure correct order
                if feature_columns != expected_features:
                    logger.info(f"🔄 Reordering features to match training order")
                    feature_columns = expected_features
        else:
            # Fallback to metadata if model doesn't have feature names
            if hasattr(self, 'model_metadata') and self.model_metadata.get('feature_columns'):
                expected_features = self.model_metadata['feature_columns']
                missing_features = set(expected_features) - set(feature_columns)
                extra_features = set(feature_columns) - set(expected_features)
                
                if missing_features:
                    raise ValueError(f"❌ Batch prediction failed: Missing required features: {list(missing_features)}")
                
                if extra_features:
                    logger.warning(f"⚠️  Extra features provided (will be ignored): {list(extra_features)}")
                
                # Ensure correct order
                if feature_columns != expected_features:
                    logger.info(f"🔄 Reordering features to match training order")
                    feature_columns = expected_features
        
        logger.info(f"📊 Batch prediction with {len(feature_columns)} features: {feature_columns[:5]}{'...' if len(feature_columns) > 5 else ''}")
        
        def predict_batch(batch):
            """Predict on a batch of data."""
            import pandas as pd
            
            # Convert batch to pandas DataFrame if it's not already
            if not isinstance(batch, pd.DataFrame):
                batch = pd.DataFrame(batch)
            
            # Extract features and make predictions
            try:
                features = batch[feature_columns].values
                predictions = self.predict(features)
                batch['predictions'] = predictions
            except Exception as e:
                logger.error(f"❌ Batch prediction failed: {e}")
                logger.error(f"Batch type: {type(batch)}")
                logger.error(f"Feature columns: {feature_columns}")
                logger.error(f"Available columns: {list(batch.columns) if hasattr(batch, 'columns') else 'No columns'}")
                raise
            
            return batch
        
        # Apply prediction to dataset
        result_dataset = dataset.map_batches(predict_batch)
        
        return result_dataset
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model."""
        if self.current_model is None:
            return {"status": "no_model_loaded"}
        
        return {
            "status": "model_loaded",
            "path": self.current_model_path,
            "metadata": self.model_metadata
        }
    
    def list_models(self) -> List[Dict[str, Any]]:
        """List all available models in storage."""
        models = []
        
        for model_dir in self.model_storage_path.iterdir():
            if model_dir.is_dir():
                model_info = {
                    "name": model_dir.name,
                    "path": str(model_dir / "model.xgb"),
                    "created": model_dir.stat().st_ctime
                }
                
                # Load metadata if available
                metadata_path = model_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path, 'r') as f:
                            metadata = json.load(f)
                            model_info.update(metadata)
                    except:
                        pass
                
                models.append(model_info)
        
        return sorted(models, key=lambda x: x["created"], reverse=True)
    
    def delete_model(self, model_name: str) -> bool:
        """Delete a model from storage."""
        try:
            model_dir = self.model_storage_path / model_name
            if model_dir.exists():
                import shutil
                shutil.rmtree(model_dir)
                logger.info(f"✅ Deleted model: {model_name}")
                return True
            else:
                logger.warning(f"Model not found: {model_name}")
                return False
        except Exception as e:
            logger.error(f"❌ Failed to delete model {model_name}: {e}")
            return False

# Global service instance
_xgboost_service = None

def get_xgboost_service() -> XGBoostService:
    """Get or create global XGBoost service instance."""
    global _xgboost_service
    if _xgboost_service is None:
        _xgboost_service = XGBoostService()
    return _xgboost_service 