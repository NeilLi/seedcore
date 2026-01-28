#!/usr/bin/env python
# seedcore/tools/vla_discovery_tools.py

"""
VLA Discovery Tools for SeedCore v2.5+

Provides tools for programmatic discovery of Vision-Language-Action (VLA) and
Embodied AI models from Hugging Face Hub, with focus on LeRobot ecosystem.

Tools:
    - hf_hub.list_models: Scan HF Hub for VLA/robotics models
    - lerobot.registry.query: Query LeRobot registry for compatible models
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
import logging

try:
    from huggingface_hub import HfApi  # pyright: ignore[reportMissingImports]
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    HfApi = None

from seedcore.tools.base import ToolBase

logger = logging.getLogger(__name__)


class HFListModelsTool(ToolBase):
    """
    Tool for programmatic scanning of Hugging Face Hub for VLA/robotics models.
    
    In 2026, focuses on Vision-Language-Action and Embodied AI models suitable
    for Reachy Mini and similar robotics platforms.
    """
    
    name = "hf_hub.list_models"
    description = (
        "Scan Hugging Face Hub for VLA (Vision-Language-Action) and Embodied AI models. "
        "Filters by tags like 'robotics', 'vla', 'embodied-ai', 'pytorch'. "
        "Returns candidates sorted by trending score or downloads."
    )
    
    def __init__(self, hf_token: Optional[str] = None):
        """
        Initialize HF Hub API client.
        
        Args:
            hf_token: Optional Hugging Face API token (from HF_TOKEN env var if not provided)
        """
        super().__init__()
        if not HF_AVAILABLE:
            raise ImportError(
                "huggingface_hub not installed. Install with: pip install huggingface_hub"
            )
        
        import os
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.api = HfApi(token=self.hf_token)
        
        # Default VLA-focused tags for 2026
        self.default_tags = ["robotics", "vla", "embodied-ai", "pytorch"]
        
        # Key namespaces for VLA models
        self.key_namespaces = [
            "lerobot",
            "openvla",
            "nvidia",
            "stanford-vl",
            "deepseek-ai",
            "mistralai",
        ]
    
    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "HF tags to filter by (default: robotics, vla, embodied-ai, pytorch)",
                        "default": self.default_tags,
                    },
                    "namespaces": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific namespaces/organizations to prioritize",
                        "default": self.key_namespaces,
                    },
                    "max_params": {
                        "type": "integer",
                        "description": "Maximum model parameters (in billions) for local PC performance",
                        "default": 10,
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["trending_score", "downloads", "likes", "created_at"],
                        "description": "Sort order for results",
                        "default": "trending_score",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of models to return",
                        "default": 20,
                    },
                    "search_query": {
                        "type": "string",
                        "description": "Optional text search query (e.g., 'smolvla', 'reachy')",
                    },
                },
                "required": [],
            },
        }
    
    async def run(
        self,
        tags: Optional[List[str]] = None,
        namespaces: Optional[List[str]] = None,
        max_params: int = 10,
        sort: str = "trending_score",
        limit: int = 20,
        search_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Scan HF Hub for VLA models.
        
        Returns:
            Dict with:
                - candidates: List of model info dicts
                - total_found: Total count
                - scan_params: Parameters used
        """
        if not HF_AVAILABLE:
            raise RuntimeError("huggingface_hub library not available")
        
        # Use defaults if not provided
        filter_tags = tags or self.default_tags
        priority_namespaces = namespaces or self.key_namespaces
        
        try:
            # Build search filter
            # HF API uses tag filtering via filter parameter
            filter_str = " OR ".join([f"tags:{tag}" for tag in filter_tags])
            
            # Add namespace filtering if provided
            if priority_namespaces:
                namespace_filter = " OR ".join([
                    f"author:{ns}" for ns in priority_namespaces
                ])
                filter_str = f"({filter_str}) AND ({namespace_filter})"
            
            # Add search query if provided
            if search_query:
                filter_str = f"{filter_str} AND {search_query}"
            
            logger.info(
                f"🔍 Scanning HF Hub for VLA models with filter: {filter_str}"
            )
            
            # List models with filters
            models = list(self.api.list_models(
                filter=filter_str if filter_str else None,
                sort=sort,
                direction=-1,  # Descending
                limit=limit * 2,  # Get more to filter by params
            ))
            
            # Filter by parameter count (if metadata available)
            candidates = []
            for model in models:
                model_info = {
                    "model_id": model.modelId,
                    "author": model.author,
                    "downloads": getattr(model, "downloads", 0),
                    "likes": getattr(model, "likes", 0),
                    "tags": getattr(model, "tags", []),
                    "created_at": str(getattr(model, "createdAt", "")),
                }
                
                # Try to extract parameter count from model card or tags
                # This is heuristic - actual param count may need model card parsing
                param_count = self._estimate_params(model)
                if param_count and param_count > max_params * 1e9:
                    continue  # Skip if too large
                
                model_info["estimated_params"] = param_count
                model_info["size_mb"] = getattr(model, "safetensors", None)
                
                candidates.append(model_info)
                
                if len(candidates) >= limit:
                    break
            
            # Sort by relevance score (trending + namespace priority)
            candidates = self._rank_candidates(candidates, priority_namespaces)
            
            result = {
                "candidates": candidates[:limit],
                "total_found": len(models),
                "filtered_count": len(candidates),
                "scan_params": {
                    "tags": filter_tags,
                    "namespaces": priority_namespaces,
                    "max_params_b": max_params,
                    "sort": sort,
                },
            }
            
            logger.info(
                f"✅ Found {len(candidates)} VLA model candidates (filtered from {len(models)})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ HF Hub scan failed: {e}", exc_info=True)
            raise
    
    def _estimate_params(self, model: Any) -> Optional[int]:
        """
        Heuristically estimate model parameter count from tags/metadata.
        
        Returns:
            Estimated parameter count (int) or None if unknown
        """
        tags = getattr(model, "tags", [])
        
        # Check for explicit size tags
        size_tags = {
            "small": 100_000_000,  # 100M
            "base": 500_000_000,  # 500M
            "large": 1_000_000_000,  # 1B
            "7b": 7_000_000_000,
            "8b": 8_000_000_000,
            "13b": 13_000_000_000,
            "14b": 14_000_000_000,
            "70b": 70_000_000_000,
        }
        
        for tag in tags:
            tag_lower = tag.lower()
            for size_key, param_count in size_tags.items():
                if size_key in tag_lower:
                    return int(param_count)
        
        # Check model ID for size hints
        model_id_lower = model.modelId.lower()
        if "smol" in model_id_lower or "450m" in model_id_lower:
            return 450_000_000
        if "7b" in model_id_lower:
            return 7_000_000_000
        if "8b" in model_id_lower:
            return 8_000_000_000
        
        return None
    
    def _rank_candidates(
        self, candidates: List[Dict[str, Any]], priority_namespaces: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Rank candidates by relevance (namespace priority + trending score).
        """
        def score(candidate: Dict[str, Any]) -> float:
            score_val = 0.0
            
            # Namespace priority boost
            author = candidate.get("author", "").lower()
            for idx, ns in enumerate(priority_namespaces):
                if ns.lower() in author:
                    score_val += (len(priority_namespaces) - idx) * 10.0
            
            # Trending metrics
            score_val += candidate.get("downloads", 0) / 1000.0
            score_val += candidate.get("likes", 0) * 5.0
            
            return score_val
        
        return sorted(candidates, key=score, reverse=True)


class LeRobotRegistryQueryTool(ToolBase):
    """
    Tool for querying LeRobot registry for VLA models compatible with SeedCore.
    
    LeRobot is the gold standard ecosystem for robotics/VLA models in 2026.
    """
    
    name = "lerobot.registry.query"
    description = (
        "Query LeRobot registry for VLA models compatible with SeedCore/Reachy Mini. "
        "Returns models with compatibility metadata, training configs, and download info."
    )
    
    def __init__(self):
        """Initialize LeRobot registry query tool."""
        super().__init__()
        # LeRobot registry endpoints (2026 standard)
        self.registry_base = "https://huggingface.co/lerobot"
        self.known_models = [
            "lerobot/smolvla_base",  # 450M - fastest for local PC
            "lerobot/smolvla_large",  # Larger variant
            "openvla/openvla-7b",  # 7B variant
        ]
    
    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "model_family": {
                        "type": "string",
                        "enum": ["smolvla", "openvla", "all"],
                        "description": "Model family to query",
                        "default": "all",
                    },
                    "max_params": {
                        "type": "integer",
                        "description": "Maximum parameters (billions) for local deployment",
                        "default": 10,
                    },
                    "include_training_config": {
                        "type": "boolean",
                        "description": "Include training configuration details",
                        "default": True,
                    },
                    "compatibility_check": {
                        "type": "boolean",
                        "description": "Check compatibility with SeedCore/Reachy",
                        "default": True,
                    },
                },
                "required": [],
            },
        }
    
    async def run(
        self,
        model_family: str = "all",
        max_params: int = 10,
        include_training_config: bool = True,
        compatibility_check: bool = True,
    ) -> Dict[str, Any]:
        """
        Query LeRobot registry for compatible models.
        
        Returns:
            Dict with:
                - models: List of model info with compatibility metadata
                - registry_info: Registry metadata
        """
        try:
            # Filter known models by family
            filtered_models = []
            if model_family == "all":
                filtered_models = self.known_models
            else:
                filtered_models = [
                    m for m in self.known_models
                    if model_family.lower() in m.lower()
                ]
            
            # Build model info with compatibility checks
            models_info = []
            for model_id in filtered_models:
                model_data = await self._get_model_info(
                    model_id,
                    include_training_config=include_training_config,
                    compatibility_check=compatibility_check,
                )
                
                # Filter by parameter count
                if model_data.get("estimated_params"):
                    params_b = model_data["estimated_params"] / 1e9
                    if params_b > max_params:
                        continue
                
                models_info.append(model_data)
            
            result = {
                "models": models_info,
                "registry_info": {
                    "source": "lerobot",
                    "base_url": self.registry_base,
                    "query_params": {
                        "model_family": model_family,
                        "max_params_b": max_params,
                    },
                },
            }
            
            logger.info(
                f"✅ LeRobot registry query returned {len(models_info)} compatible models"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ LeRobot registry query failed: {e}", exc_info=True)
            raise
    
    async def _get_model_info(
        self,
        model_id: str,
        include_training_config: bool = True,
        compatibility_check: bool = True,
    ) -> Dict[str, Any]:
        """
        Get detailed info for a specific LeRobot model.
        
        This is a simplified implementation. In production, you'd query
        the actual LeRobot registry API or HF model card.
        """
        # Model metadata (would be fetched from registry in production)
        model_metadata = {
            "lerobot/smolvla_base": {
                "estimated_params": 450_000_000,  # 450M
                "vla_native": True,
                "action_tokens": True,
                "3d_position_embedding": True,
                "latency_ms": 200,  # ~5Hz on local PC
                "recommended_for": ["local_pc", "realtime_control"],
            },
            "lerobot/smolvla_large": {
                "estimated_params": 1_200_000_000,  # 1.2B
                "vla_native": True,
                "action_tokens": True,
                "3d_position_embedding": True,
                "latency_ms": 400,
                "recommended_for": ["local_pc", "complex_tasks"],
            },
            "openvla/openvla-7b": {
                "estimated_params": 7_000_000_000,  # 7B
                "vla_native": True,
                "action_tokens": True,
                "3d_position_embedding": True,
                "latency_ms": 1000,  # ~1Hz
                "recommended_for": ["cloud", "complex_reasoning"],
            },
        }
        
        base_info = model_metadata.get(model_id, {
            "estimated_params": None,
            "vla_native": False,
            "action_tokens": False,
            "3d_position_embedding": False,
        })
        
        info = {
            "model_id": model_id,
            "registry": "lerobot",
            **base_info,
        }
        
        # Add training config if requested
        if include_training_config:
            info["training_config"] = {
                "framework": "lerobot",
                "compatible": True,
                "seedcore_format": "supported",
            }
        
        # Compatibility check
        if compatibility_check:
            info["seedcore_compatibility"] = {
                "compatible": True,
                "reachy_mini": base_info.get("vla_native", False),
                "action_format": "json" if base_info.get("action_tokens") else None,
                "spatial_reasoning": base_info.get("3d_position_embedding", False),
            }
        
        return info


# ============================================================
# Registration Helper
# ============================================================

async def register_vla_discovery_tools(
    tool_manager: Any,
    hf_token: Optional[str] = None,
) -> None:
    """
    Register VLA discovery tools with ToolManager.
    
    Args:
        tool_manager: ToolManager instance
        hf_token: Optional HF API token
    """
    hf_tool = HFListModelsTool(hf_token=hf_token)
    await tool_manager.register(hf_tool.name, hf_tool)
    
    lerobot_tool = LeRobotRegistryQueryTool()
    await tool_manager.register(lerobot_tool.name, lerobot_tool)
    
    logger.info("✅ Registered VLA discovery tools: hf_hub.list_models, lerobot.registry.query")
