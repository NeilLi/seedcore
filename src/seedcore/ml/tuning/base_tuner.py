#!/usr/bin/env python
# seedcore/ml/tuning/base_tuner.py

"""
Base Tuning Classes for SeedCore ML Module

Provides abstract base classes and common interfaces for model fine-tuning operations.
All specific tuners (LoRA, LeRobot, FunctionGemma, etc.) should inherit from these.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BaseTuner(ABC):
    """
    Abstract base class for model fine-tuning operations.
    
    All tuners (LoRA, full fine-tuning, etc.) should inherit from this class
    to provide a consistent interface for the ML service.
    """
    
    def __init__(
        self,
        base_model: str,
        output_base_dir: Optional[str] = None,
        ml_client: Optional[Any] = None,
    ):
        """
        Initialize base tuner.
        
        Args:
            base_model: Base model identifier (HF model ID or path)
            output_base_dir: Base directory for checkpoints
            ml_client: Optional MLServiceClient for job management
        """
        self.base_model = base_model
        self.ml_client = ml_client
        self.output_base_dir = Path(output_base_dir or "./checkpoints")
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    async def prepare_training_config(
        self,
        training_data: Dict[str, Any],
        training_config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Prepare training configuration.
        
        Args:
            training_data: Training data in format expected by tuner
            training_config: Optional training hyperparameters
            **kwargs: Additional tuner-specific parameters
        
        Returns:
            Complete training job configuration
        """
        pass
    
    @abstractmethod
    async def submit_training_job(
        self,
        training_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Submit training job to ML service or return config for manual execution.
        
        Args:
            training_config: Training configuration from prepare_training_config()
        
        Returns:
            Dict with job_id (if submitted) or training command (if manual)
        """
        pass
    
    def get_output_dir(self, model_name: Optional[str] = None) -> str:
        """Get output directory for this tuner."""
        if model_name:
            safe_name = model_name.replace("/", "_")
        else:
            safe_name = self.base_model.replace("/", "_")
        return str(self.output_base_dir / safe_name)


class LoRATuner(BaseTuner):
    """
    Base class for LoRA (Low-Rank Adaptation) fine-tuning.
    
    Provides common LoRA configuration and data preparation logic.
    Specific implementations (FunctionGemma, LeRobot, etc.) should inherit from this.
    """
    
    def __init__(
        self,
        base_model: str,
        output_base_dir: Optional[str] = None,
        ml_client: Optional[Any] = None,
        default_lora_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize LoRA tuner.
        
        Args:
            base_model: Base model identifier
            output_base_dir: Base directory for checkpoints
            ml_client: Optional MLServiceClient
            default_lora_config: Default LoRA configuration
        """
        super().__init__(base_model, output_base_dir, ml_client)
        
        # Default LoRA config (can be overridden by subclasses)
        self.default_lora_config = default_lora_config or {
            "r": 16,
            "lora_alpha": 32,
            "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
            "lora_dropout": 0.1,
            "task_type": "CAUSAL_LM",
        }
    
    def merge_lora_config(
        self,
        provided_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Merge provided LoRA config with defaults.
        
        Args:
            provided_config: Optional LoRA config to merge
        
        Returns:
            Merged LoRA configuration
        """
        if provided_config is None:
            return self.default_lora_config.copy()
        
        merged = self.default_lora_config.copy()
        merged.update(provided_config)
        return merged


class ModelTrainingOrchestrator:
    """
    Orchestrator for model training operations.
    
    Provides a unified interface for submitting training jobs to ML service,
    managing checkpoints, and tracking training progress.
    """
    
    def __init__(self, ml_client: Optional[Any] = None):
        """
        Initialize training orchestrator.
        
        Args:
            ml_client: Optional MLServiceClient for job management
        """
        self.ml_client = ml_client
    
    async def submit_training(
        self,
        tuner: BaseTuner,
        training_data: Dict[str, Any],
        training_config: Optional[Dict[str, Any]] = None,
        **tuner_kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Submit training job using a tuner.
        
        Args:
            tuner: Tuner instance (LoRA, LeRobot, etc.)
            training_data: Training data
            training_config: Optional training config
            **tuner_kwargs: Tuner-specific parameters
        
        Returns:
            Training job result with job_id or command
        """
        # Prepare training config via tuner
        training_job_config = await tuner.prepare_training_config(
            training_data=training_data,
            training_config=training_config,
            **tuner_kwargs,
        )
        
        # Submit via tuner
        result = await tuner.submit_training_job(training_job_config)
        
        logger.info(
            f"✅ Training job configured for {tuner.base_model} "
            f"(tuner: {tuner.__class__.__name__})"
        )
        
        return result
