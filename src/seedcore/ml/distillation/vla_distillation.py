#!/usr/bin/env python
# seedcore/ml/distillation/vla_distillation.py

"""
VLA Distillation Service for SeedCore v2.5+

Provides DISTILLATION WORKFLOWS for Vision-Language-Action (VLA) models using
SeedCore Trace-Replay method. 

Architecture:
    - Distillation workflows USE tuning services (from ml.tuning)
    - This module orchestrates the knowledge transfer from Teacher to Student
    - The actual model training is done by tuners in ml.tuning

Components:
    - TeacherLLMEscalator: Teacher model escalation for high-risk tasks
    - TraceReplayDistiller: SeedCore Trace-Replay distillation pipeline (uses tuners)
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
import logging
import json

from ..tuning.lerobot_tuner import LeRobotFineTuner
from ..tuning.base_tuner import ModelTrainingOrchestrator

logger = logging.getLogger(__name__)


class TeacherLLMEscalator:
    """
    Teacher LLM escalation service for high-risk VLA tasks.
    
    When SeedCore detects high risk (via params.risk), this service bridges to
    remote LLM Teacher (GPT-4o/Claude) to generate high-quality traces for distillation.
    """
    
    def __init__(self, cognitive_client: Optional[Any] = None):
        """
        Initialize Teacher escalation service.
        
        Args:
            cognitive_client: Optional CognitiveServiceClient for LLM calls
        """
        self.cognitive_client = cognitive_client
    
    async def escalate(
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
        
        Returns:
            Dict with teacher_output, reasoning, and formatted trace_data
        """
        # Build Teacher prompt with multi-view contextual prompting
        teacher_prompt = self._build_teacher_prompt(
            multimodal_context,
            role_profile,
            task_description,
            include_spatial_reasoning,
        )
        
        # Call Teacher LLM
        if self.cognitive_client:
            teacher_response = await self._call_teacher_llm(
                teacher_prompt, teacher_model, multimodal_context
            )
        else:
            # Fallback: Return structured format for manual LLM call
            teacher_response = {
                "tool_calls": [],
                "reasoning": "Cognitive client not available - manual LLM call required",
            }
        
        # Format as SeedCore trace for distillation
        trace_data = {
            "multimodal": multimodal_context,
            "teacher_output": {
                "tool_calls": teacher_response.get("tool_calls", []),
                "reasoning": teacher_response.get("reasoning", ""),
                "spatial_explanation": teacher_response.get("spatial_explanation", ""),
            },
            "risk_level": risk_level,
            "teacher_model": teacher_model,
        }
        
        return {
            "teacher_output": teacher_response,
            "trace_data": trace_data,
            "status": "success",
            "teacher_model": teacher_model,
        }
    
    def _build_teacher_prompt(
        self,
        multimodal_context: Dict[str, Any],
        role_profile: Dict[str, Any],
        task_description: str,
        include_spatial_reasoning: bool,
    ) -> str:
        """
        Build multi-view contextual prompt for Teacher LLM.
        
        Format:
        "Based on this camera frame and the reachy.motion.wave tool, generate
        the specific params.tool_calls JSON. Include a _router.reason explaining
        the spatial choice."
        """
        tools = role_profile.get("allowed_tools", [])
        skills = role_profile.get("default_skills", {})
        
        prompt_parts = [
            "You are a Teacher model for SeedCore VLA (Vision-Language-Action) distillation.",
            "",
            "Task:",
            task_description,
            "",
            "Available Tools:",
            json.dumps(tools, indent=2),
            "",
            "Agent Skills:",
            json.dumps(skills, indent=2),
            "",
            "Multimodal Context:",
            f"Source: {multimodal_context.get('source', 'unknown')}",
            f"Media URI: {multimodal_context.get('media_uri', 'N/A')}",
            "",
            "Instructions:",
            "1. Analyze the multimodal context (camera frame/video)",
            "2. Generate specific tool_calls JSON that would control Reachy Mini",
            "3. Include spatial reasoning explanation (_router.reason)",
            "4. Output format:",
            "   {",
            '     "tool_calls": [',
            '       {',
            '         "tool": "reachy.motion.wave",',
            '         "params": {...},',
            '         "_router": {"reason": "spatial choice explanation"}',
            '       }',
            '     ]',
            "   }",
        ]
        
        if include_spatial_reasoning:
            prompt_parts.extend([
                "",
                "Spatial Reasoning:",
                "Explain your spatial choices (e.g., why this [x, y, z] coordinate, "
                "why this joint angle, etc.). This explanation will be used to train "
                "the Student model's spatial understanding.",
            ])
        
        return "\n".join(prompt_parts)
    
    async def _call_teacher_llm(
        self,
        prompt: str,
        model: str,
        multimodal_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Call Teacher LLM via CognitiveServiceClient.
        
        In production, this would:
        1. Send multimodal context (images/video) to vision-capable LLM
        2. Parse structured JSON response
        3. Validate tool_calls format
        """
        if not self.cognitive_client:
            raise RuntimeError("Cognitive client not available")
        
        # This would call cognitive_client with multimodal support
        # For now, return placeholder structure
        # In production: response = await self.cognitive_client.chat_completion(...)
        
        logger.info(f"📞 Calling Teacher LLM ({model}) for VLA task")
        
        return {
            "tool_calls": [
                {
                    "tool": "reachy.motion.wave",
                    "params": {
                        "arm": "left",
                        "speed": 0.5,
                    },
                    "_router": {
                        "reason": "Spatial reasoning: Left arm wave gesture based on camera frame analysis",
                    },
                }
            ],
            "reasoning": "Teacher model analysis of multimodal context",
            "spatial_explanation": "Selected left arm for wave gesture based on current pose and task context",
        }


class TraceReplayDistiller:
    """
    SeedCore Trace-Replay distillation pipeline coordinator.
    
    Orchestrates the complete distillation workflow:
    1. Collect traces from Teacher (via escalation)
    2. Prepare training data in LeRobot format
    3. Fine-tune Student model
    4. Validate and deploy
    """
    
    def __init__(
        self,
        base_model: str,
        fine_tuner: Optional[LeRobotFineTuner] = None,
        teacher_escalator: Optional[TeacherLLMEscalator] = None,
        training_orchestrator: Optional[ModelTrainingOrchestrator] = None,
    ):
        """
        Initialize Trace-Replay distiller.
        
        Args:
            base_model: Base model ID for Student model
            fine_tuner: LeRobot fine-tuner instance (uses base_model)
            teacher_escalator: Teacher escalation service instance
            training_orchestrator: Training orchestrator (optional)
        """
        self.base_model = base_model
        self.fine_tuner = fine_tuner or LeRobotFineTuner(base_model=base_model)
        self.teacher_escalator = teacher_escalator or TeacherLLMEscalator()
        self.training_orchestrator = training_orchestrator or ModelTrainingOrchestrator()
    
    async def distill_from_traces(
        self,
        traces: List[Dict[str, Any]],
        output_dir: Optional[str] = None,
        training_config: Optional[Dict[str, Any]] = None,
        lora_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run complete Trace-Replay distillation from collected traces.
        
        This is a DISTILLATION WORKFLOW that uses the tuning service.
        
        Args:
            traces: List of trace dicts with multimodal, teacher_output, ground_truth
            output_dir: Optional output directory (overrides tuner default)
            training_config: Optional training configuration overrides
            lora_config: Optional LoRA configuration
        
        Returns:
            Dict with training job info and checkpoint paths
        """
        training_data = {"traces": traces}
        
        # Use training orchestrator to submit via tuner
        result = await self.training_orchestrator.submit_training(
            tuner=self.fine_tuner,
            training_data=training_data,
            training_config=training_config,
            lora_config=lora_config,
            seedcore_format=True,
            trace_replay=True,
        )
        
        # Override output dir if provided
        if output_dir and "training_config" in result:
            result["training_config"]["output_dir"] = output_dir
        
        logger.info(
            f"✅ Trace-Replay distillation configured for {self.base_model} "
            f"with {len(traces)} traces"
        )
        
        return result
