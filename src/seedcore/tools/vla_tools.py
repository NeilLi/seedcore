#!/usr/bin/env python
# seedcore/tools/vla_tools.py

"""
VLA Tools Registration Helper for SeedCore v2.5+

Convenience module for registering all VLA-related tools at once.
"""

from __future__ import annotations

from typing import Any, Optional
import logging

from .vla_discovery_tools import register_vla_discovery_tools
from .vla_analysis_tools import register_vla_analysis_tools
from .distillation_tools import register_distillation_tools

logger = logging.getLogger(__name__)


async def register_all_vla_tools(
    tool_manager: Any,
    *,
    hf_token: Optional[str] = None,
    ml_client: Optional[Any] = None,
    cognitive_client: Optional[Any] = None,
) -> None:
    """
    Register all VLA-related tools with ToolManager.
    
    This registers:
        - Discovery tools: hf_hub.list_models, lerobot.registry.query
        - Analysis tools: vla.analyze_model, vla.score_candidate
        - Distillation tools: finetune.run_lerobot, teacher.escalate_gpt4
    
    Args:
        tool_manager: ToolManager instance
        hf_token: Optional Hugging Face API token
        ml_client: Optional MLServiceClient for training jobs
        cognitive_client: Optional CognitiveServiceClient for Teacher escalation
    """
    logger.info("🔧 Registering VLA tools for SeedCore v2.5+...")
    
    # Register discovery tools
    await register_vla_discovery_tools(tool_manager, hf_token=hf_token)
    
    # Register analysis tools
    await register_vla_analysis_tools(tool_manager)
    
    # Register distillation tools
    await register_distillation_tools(
        tool_manager,
        ml_client=ml_client,
        cognitive_client=cognitive_client,
    )
    
    logger.info("✅ All VLA tools registered successfully")
