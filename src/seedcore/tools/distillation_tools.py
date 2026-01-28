#!/usr/bin/env python
# seedcore/tools/distillation_tools.py

"""
Distillation Tools for SeedCore v2.5+ VLA Workflows

Thin tool wrappers that call the ML distillation service.
The actual ML logic lives in seedcore.ml.distillation.vla_distillation.

Tools:
    - finetune.run_lerobot: Run LeRobot-compatible fine-tuning for VLA models
    - teacher.escalate_gpt4: Escalate to GPT-4o/Claude as Teacher for high-risk tasks
"""

from __future__ import annotations

from typing import Dict, Any, Optional
import logging

from seedcore.tools.base import ToolBase
from seedcore.ml.tuning.lerobot_tuner import LeRobotFineTuner
from seedcore.ml.distillation.vla_distillation import TeacherLLMEscalator

logger = logging.getLogger(__name__)


class FinetuneLeRobotTool(ToolBase):
    """
    Tool for running LeRobot-compatible fine-tuning on VLA models.
    
    Implements SeedCore Trace-Replay distillation method:
    1. Multi-view contextual prompting with Teacher model
    2. Behavioral grounding via LeRobot training pipeline
    3. Alignment of Teacher JSON outputs with Reachy motor states
    """
    
    name = "finetune.run_lerobot"
    description = (
        "Run LeRobot-compatible fine-tuning for VLA models using SeedCore Trace-Replay distillation. "
        "Takes teacher-generated traces and aligns them with Reachy Mini motor states. "
        "Supports LoRA tuning and full fine-tuning."
    )
    
    def __init__(self, ml_client: Optional[Any] = None, output_base_dir: Optional[str] = None):
        """
        Initialize LeRobot fine-tuning tool.
        
        Args:
            ml_client: Optional MLServiceClient for training job management
            output_base_dir: Base directory for checkpoints
        """
        super().__init__()
        self.fine_tuner = LeRobotFineTuner(
            ml_client=ml_client,
            output_base_dir=output_base_dir
        )
    
    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "base_model": {
                        "type": "string",
                        "description": "Base model ID (e.g., 'lerobot/smolvla_base')",
                    },
                    "training_data": {
                        "type": "object",
                        "description": "Training data configuration (traces, episodes, etc.)",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory for checkpoints",
                    },
                    "training_config": {
                        "type": "object",
                        "description": "LeRobot training configuration",
                    },
                    "lora_config": {
                        "type": "object",
                        "description": "LoRA adapter configuration (optional)",
                    },
                    "seedcore_format": {
                        "type": "boolean",
                        "description": "Use SeedCore JSON format for action outputs",
                        "default": True,
                    },
                    "trace_replay": {
                        "type": "boolean",
                        "description": "Enable Trace-Replay distillation method",
                        "default": True,
                    },
                },
                "required": ["base_model", "training_data"],
            },
        }
    
    async def run(
        self,
        base_model: str,
        training_data: Dict[str, Any],
        output_dir: Optional[str] = None,
        training_config: Optional[Dict[str, Any]] = None,
        lora_config: Optional[Dict[str, Any]] = None,
        seedcore_format: bool = True,
        trace_replay: bool = True,
    ) -> Dict[str, Any]:
        """
        Run LeRobot fine-tuning with SeedCore Trace-Replay distillation.
        
        Delegates to ML distillation service for actual implementation.
        
        Returns:
            Dict with training job info, checkpoint paths, and metrics.
        """
        try:
            # Prepare training config via ML service
            training_job_config = await self.fine_tuner.prepare_training_config(
                base_model=base_model,
                training_data=training_data,
                training_config=training_config,
                lora_config=lora_config,
                seedcore_format=seedcore_format,
                trace_replay=trace_replay,
            )
            
            if output_dir:
                training_job_config["output_dir"] = output_dir
            
            # Submit training job via ML service
            result = await self.fine_tuner.submit_training_job(training_job_config)
            
            logger.info(
                f"✅ Configured LeRobot fine-tuning for {base_model} "
                f"(LoRA: {lora_config is not None}, Trace-Replay: {trace_replay})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ LeRobot fine-tuning setup failed: {e}", exc_info=True)
            raise


class TeacherEscalateGPT4Tool(ToolBase):
    """
    Tool for escalating to GPT-4o/Claude as Teacher for high-risk distillation tasks.
    
    When SeedCore detects high risk (via params.risk), this tool bridges to the
    remote LLM Teacher to generate high-quality traces for distillation.
    """
    
    name = "teacher.escalate_gpt4"
    description = (
        "Escalate to GPT-4o/Claude as Teacher model for high-risk VLA tasks. "
        "Generates high-quality tool_calls JSON based on multimodal context and RoleProfile. "
        "Used in SeedCore Trace-Replay distillation workflow."
    )
    
    def __init__(self, cognitive_client: Optional[Any] = None):
        """
        Initialize Teacher escalation tool.
        
        Args:
            cognitive_client: Optional CognitiveServiceClient for LLM calls
        """
        super().__init__()
        self.escalator = TeacherLLMEscalator(cognitive_client=cognitive_client)
    
    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "multimodal_context": {
                        "type": "object",
                        "description": "Multimodal input (image/video frames from Reachy vision)",
                    },
                    "role_profile": {
                        "type": "object",
                        "description": "Agent RoleProfile with tools and capabilities",
                    },
                    "task_description": {
                        "type": "string",
                        "description": "Description of the VLA task to perform",
                    },
                    "risk_level": {
                        "type": "number",
                        "description": "Risk level (0-1) that triggered escalation",
                    },
                    "teacher_model": {
                        "type": "string",
                        "enum": ["gpt-4o", "claude-3-5-sonnet", "gpt-4-turbo"],
                        "description": "Teacher model to use",
                        "default": "gpt-4o",
                    },
                    "include_spatial_reasoning": {
                        "type": "boolean",
                        "description": "Request spatial reasoning explanation",
                        "default": True,
                    },
                },
                "required": ["multimodal_context", "role_profile", "task_description"],
            },
        }
    
    async def run(
        self,
        multimodal_context: Dict[str, Any],
        role_profile: Dict[str, Any],
        task_description: str,
        risk_level: float = 0.8,
        teacher_model: str = "gpt-4o",
        include_spatial_reasoning: bool = True,
    ) -> Dict[str, Any]:
        """
        Escalate to Teacher LLM for high-risk VLA task.
        
        Delegates to ML distillation service for actual implementation.
        
        Returns:
            Dict with:
                - teacher_output: Generated tool_calls JSON
                - reasoning: Teacher's spatial reasoning explanation
                - trace_data: Formatted trace for distillation
        """
        try:
            # Delegate to ML service
            result = await self.escalator.escalate(
                multimodal_context=multimodal_context,
                role_profile=role_profile,
                task_description=task_description,
                risk_level=risk_level,
                teacher_model=teacher_model,
                include_spatial_reasoning=include_spatial_reasoning,
            )
            
            logger.info(
                f"✅ Teacher escalation completed (model: {teacher_model}, "
                f"risk: {risk_level:.2f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Teacher escalation failed: {e}", exc_info=True)
            raise


# ============================================================
# Registration Helper
# ============================================================

async def register_distillation_tools(
    tool_manager: Any,
    ml_client: Optional[Any] = None,
    cognitive_client: Optional[Any] = None,
) -> None:
    """
    Register distillation tools with ToolManager.
    
    Args:
        tool_manager: ToolManager instance
        ml_client: Optional MLServiceClient for training jobs
        cognitive_client: Optional CognitiveServiceClient for Teacher escalation
    """
    finetune_tool = FinetuneLeRobotTool(ml_client=ml_client, output_base_dir=None)
    await tool_manager.register(finetune_tool.name, finetune_tool)
    
    teacher_tool = TeacherEscalateGPT4Tool(cognitive_client=cognitive_client)
    await tool_manager.register(teacher_tool.name, teacher_tool)
    
    logger.info(
        "✅ Registered distillation tools: finetune.run_lerobot, teacher.escalate_gpt4"
    )
