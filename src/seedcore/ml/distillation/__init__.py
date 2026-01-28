"""
SeedCore ML Distillation Module

Provides DISTILLATION WORKFLOWS for knowledge transfer from Teacher to Student models.

Architecture:
    - Distillation workflows USE tuning services (from ml.tuning)
    - This module orchestrates knowledge transfer, not model training
    - Model training is done by tuners in ml.tuning

Distillation vs Tuning:
    - DISTILLATION: Knowledge transfer workflows (this module)
    - TUNING: Model training operations (ml.tuning module)

Components:
    - System-level distillation: Regime classification, action labeling
    - VLA distillation: Trace-Replay method for Vision-Language-Action models
"""

from .teacher_llm import build_distillation_prompt, label_episode_with_llm
from .vla_distillation import (
    TeacherLLMEscalator,
    TraceReplayDistiller,
)

__all__ = [
    # System distillation
    "build_distillation_prompt",
    "label_episode_with_llm",
    # VLA distillation (workflows that use tuners)
    "TeacherLLMEscalator",
    "TraceReplayDistiller",
]
