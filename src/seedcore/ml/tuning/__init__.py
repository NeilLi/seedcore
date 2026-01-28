"""
SeedCore ML Tuning Module

Provides core model fine-tuning and training services.

Architecture:
    - Base classes: Abstract interfaces for all tuners
    - Specific tuners: LeRobot, FunctionGemma, etc.
    - Orchestration: Unified training job management
    - Traditional ML: Legacy training scripts moved to domain modules (e.g., ml/salience/)

Tuning vs Distillation:
    - TUNING: Model training/fine-tuning operations (this module)
      - Fine-tuning pre-trained models (LLMs, VLAs) - PRIMARY USE CASE
      - Traditional ML training from scratch - LEGACY (moved to domain modules)
    - DISTILLATION: Knowledge transfer workflows that USE tuning (ml.distillation)

Note: In 2026+, SeedCore focuses on fine-tuning pre-trained models rather than
training from scratch. Traditional ML training scripts are kept in domain-specific
modules (e.g., ml/salience/train_*.py) for legacy support.
"""

from .base_tuner import (
    BaseTuner,
    LoRATuner,
    ModelTrainingOrchestrator,
)
from .lerobot_tuner import LeRobotFineTuner
from .tuning_service import HyperparameterTuningService

__all__ = [
    # Base classes
    "BaseTuner",
    "LoRATuner",
    "ModelTrainingOrchestrator",
    # Specific tuners
    "LeRobotFineTuner",
    # Hyperparameter tuning
    "HyperparameterTuningService",
]
