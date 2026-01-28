#!/usr/bin/env python
# seedcore/tools/vla_analysis_tools.py

"""
VLA Analysis Tools for SeedCore v2.5+

Provides tools for analyzing and scoring VLA models based on "Spatial-Behavioral" metrics.
These metrics determine if a model can effectively control Reachy Mini and understand
3D coordinates and motor primitives.

Tools:
    - vla.analyze_model: Analyze a VLA model's spatial-behavioral capabilities
    - vla.score_candidate: Score a model candidate for Reachy Mini compatibility
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
import logging

from seedcore.tools.base import ToolBase

logger = logging.getLogger(__name__)


class VLAAnalyzeModelTool(ToolBase):
    """
    Tool for analyzing VLA models based on spatial-behavioral metrics.
    
    In 2026, a model might be "smart" at coding but terrible at "knowing where
    Reachy's hand is." This tool analyzes three critical dimensions:
    
    1. VLA Native (Action Tokens): Can output motor coordinates directly?
    2. 3D Position Embedding: Understands [x, y, z] vs just "left/right"?
    3. Latency/Throughput: Can run at 5Hz+ on local PC?
    """
    
    name = "vla.analyze_model"
    description = (
        "Analyze a VLA model's spatial-behavioral capabilities for robotics control. "
        "Evaluates VLA-native action tokens, 3D position understanding, and latency/throughput. "
        "Returns a detailed analysis with scores for each dimension."
    )
    
    def __init__(self):
        """Initialize VLA analysis tool."""
        super().__init__()
        
        # 2026 top candidates for reference scoring
        self.reference_models = {
            "lerobot/smolvla_base": {
                "vla_native_score": 0.95,
                "3d_position_score": 0.90,
                "latency_score": 0.95,  # ~5Hz on local PC
            },
            "openvla-7b": {
                "vla_native_score": 0.92,
                "3d_position_score": 0.88,
                "latency_score": 0.70,  # ~1Hz, needs cloud
            },
            "nvidia/gr00t-n1.6": {
                "vla_native_score": 0.90,
                "3d_position_score": 0.95,  # Best spatial reasoning
                "latency_score": 0.60,  # Optimized for Jetson/DGX
            },
            "DeepSeek-R1-Distill-Qwen-7B": {
                "vla_native_score": 0.75,
                "3d_position_score": 0.70,
                "latency_score": 0.65,
            },
        }
    
    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {
                        "type": "string",
                        "description": "Hugging Face model ID (e.g., 'lerobot/smolvla_base')",
                    },
                    "model_metadata": {
                        "type": "object",
                        "description": "Optional model metadata from HF Hub or registry",
                    },
                    "target_platform": {
                        "type": "string",
                        "enum": ["local_pc", "jetson", "cloud", "reachy_mini"],
                        "description": "Target deployment platform",
                        "default": "reachy_mini",
                    },
                    "min_latency_hz": {
                        "type": "number",
                        "description": "Minimum required control frequency (Hz)",
                        "default": 5.0,
                    },
                },
                "required": ["model_id"],
            },
        }
    
    async def run(
        self,
        model_id: str,
        model_metadata: Optional[Dict[str, Any]] = None,
        target_platform: str = "reachy_mini",
        min_latency_hz: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Analyze a VLA model's spatial-behavioral capabilities.
        
        Returns:
            Dict with:
                - model_id: Model identifier
                - scores: Dict of metric scores (0-1)
                - analysis: Detailed analysis breakdown
                - recommendation: Overall recommendation
        """
        try:
            # Check if we have reference data
            reference = self.reference_models.get(model_id)
            
            # Extract metadata or use heuristics
            metadata = model_metadata or {}
            
            # 1. VLA Native Score (Action Tokens)
            vla_native_score = self._score_vla_native(model_id, metadata, reference)
            
            # 2. 3D Position Embedding Score
            position_score = self._score_3d_position(model_id, metadata, reference)
            
            # 3. Latency/Throughput Score
            latency_score = self._score_latency(
                model_id, metadata, target_platform, min_latency_hz, reference
            )
            
            # Overall spatial-behavioral score (weighted)
            overall_score = (
                vla_native_score * 0.4 +  # Most important for VLA
                position_score * 0.35 +   # Critical for spatial control
                latency_score * 0.25      # Important but can be optimized
            )
            
            # Generate recommendation
            recommendation = self._generate_recommendation(
                overall_score, vla_native_score, position_score, latency_score, target_platform
            )
            
            result = {
                "model_id": model_id,
                "scores": {
                    "vla_native": vla_native_score,
                    "3d_position_embedding": position_score,
                    "latency_throughput": latency_score,
                    "overall_spatial_behavioral": overall_score,
                },
                "analysis": {
                    "vla_native": {
                        "score": vla_native_score,
                        "has_action_tokens": vla_native_score > 0.7,
                        "can_output_motor_coords": vla_native_score > 0.8,
                        "details": self._explain_vla_native(vla_native_score),
                    },
                    "3d_position": {
                        "score": position_score,
                        "understands_xyz": position_score > 0.7,
                        "spatial_reasoning": position_score > 0.8,
                        "details": self._explain_3d_position(position_score),
                    },
                    "latency": {
                        "score": latency_score,
                        "meets_target_hz": latency_score > 0.7,
                        "estimated_hz": self._estimate_hz(latency_score, target_platform),
                        "details": self._explain_latency(latency_score, target_platform),
                    },
                },
                "recommendation": recommendation,
                "target_platform": target_platform,
            }
            
            logger.info(
                f"✅ Analyzed {model_id}: overall score {overall_score:.2f} "
                f"(VLA: {vla_native_score:.2f}, 3D: {position_score:.2f}, Latency: {latency_score:.2f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ VLA analysis failed for {model_id}: {e}", exc_info=True)
            raise
    
    def _score_vla_native(
        self,
        model_id: str,
        metadata: Dict[str, Any],
        reference: Optional[Dict[str, Any]],
    ) -> float:
        """Score VLA-native capabilities (action tokens, motor coordinate output)."""
        # Use reference if available
        if reference and "vla_native_score" in reference:
            return reference["vla_native_score"]
        
        # Check metadata
        if metadata.get("vla_native") or metadata.get("action_tokens"):
            return 0.90
        
        # Heuristic: Check model ID/tags
        model_lower = model_id.lower()
        if "vla" in model_lower or "smolvla" in model_lower:
            return 0.85
        if "lerobot" in model_lower:
            return 0.80
        
        # Default: assume not VLA-native unless proven otherwise
        return 0.30
    
    def _score_3d_position(
        self,
        model_id: str,
        metadata: Dict[str, Any],
        reference: Optional[Dict[str, Any]],
    ) -> float:
        """Score 3D position embedding capabilities."""
        # Use reference if available
        if reference and "3d_position_score" in reference:
            return reference["3d_position_score"]
        
        # Check metadata
        if metadata.get("3d_position_embedding"):
            return 0.90
        
        # Heuristic: Check for spatial reasoning models
        model_lower = model_id.lower()
        if "gr00t" in model_lower or "nvidia" in model_lower:
            return 0.95  # NVIDIA models excel at spatial reasoning
        if "vla" in model_lower or "smolvla" in model_lower:
            return 0.85
        
        # Default: assume limited spatial understanding
        return 0.40
    
    def _score_latency(
        self,
        model_id: str,
        metadata: Dict[str, Any],
        target_platform: str,
        min_hz: float,
        reference: Optional[Dict[str, Any]],
    ) -> float:
        """Score latency/throughput for target platform."""
        # Use reference if available
        if reference and "latency_score" in reference:
            base_score = reference["latency_score"]
            # Adjust for platform
            if target_platform == "jetson" and "nvidia" in model_id.lower():
                return min(1.0, base_score + 0.15)  # NVIDIA models optimized for Jetson
            return base_score
        
        # Check metadata
        latency_ms = metadata.get("latency_ms")
        if latency_ms:
            target_ms = 1000.0 / min_hz  # Target latency in ms
            if latency_ms <= target_ms:
                return 0.95
            elif latency_ms <= target_ms * 2:
                return 0.75
            elif latency_ms <= target_ms * 4:
                return 0.50
            else:
                return 0.25
        
        # Heuristic: Estimate from model size
        params = metadata.get("estimated_params", 0)
        if params < 1e9:  # < 1B params
            return 0.90  # Should be fast
        elif params < 8e9:  # < 8B params
            return 0.70  # Moderate
        else:
            return 0.40  # Large models slower
        
        return 0.50  # Default
    
    def _explain_vla_native(self, score: float) -> str:
        """Generate explanation for VLA-native score."""
        if score >= 0.9:
            return "Excellent VLA-native capabilities. Can output motor coordinates directly as action tokens."
        elif score >= 0.7:
            return "Good VLA support. May need minor adaptation for motor coordinate output."
        elif score >= 0.5:
            return "Limited VLA capabilities. Requires significant fine-tuning for robotics."
        else:
            return "Not VLA-native. Primarily a language model, not suitable for direct motor control."
    
    def _explain_3d_position(self, score: float) -> str:
        """Generate explanation for 3D position score."""
        if score >= 0.9:
            return "Excellent 3D spatial understanding. Understands [x, y, z] coordinates natively."
        elif score >= 0.7:
            return "Good spatial reasoning. Can work with 3D coordinates with some adaptation."
        elif score >= 0.5:
            return "Limited 3D understanding. May only understand relative directions (left/right)."
        else:
            return "Poor spatial reasoning. Not suitable for precise 3D control tasks."
    
    def _explain_latency(self, score: float, platform: str) -> str:
        """Generate explanation for latency score."""
        if score >= 0.9:
            return f"Excellent latency. Can achieve 5Hz+ on {platform}."
        elif score >= 0.7:
            return f"Good latency. Can achieve 3-5Hz on {platform} with optimization."
        elif score >= 0.5:
            return f"Moderate latency. May need cloud deployment or hardware acceleration for {platform}."
        else:
            return f"High latency. Not suitable for real-time control on {platform}."
    
    def _estimate_hz(self, latency_score: float, platform: str) -> float:
        """Estimate control frequency (Hz) from latency score."""
        # Rough estimate: higher score = higher Hz
        base_hz = latency_score * 10.0  # Scale 0-1 to 0-10 Hz
        
        # Platform adjustments
        if platform == "jetson":
            base_hz *= 1.2  # Jetson optimized for edge AI
        elif platform == "cloud":
            base_hz *= 0.8  # Cloud has network latency
        
        return max(0.5, min(10.0, base_hz))
    
    def _generate_recommendation(
        self,
        overall: float,
        vla: float,
        position: float,
        latency: float,
        platform: str,
    ) -> Dict[str, Any]:
        """Generate overall recommendation."""
        if overall >= 0.85:
            verdict = "highly_recommended"
            reason = "Excellent spatial-behavioral capabilities for Reachy Mini"
        elif overall >= 0.70:
            verdict = "recommended"
            reason = "Good capabilities, may need minor optimization"
        elif overall >= 0.55:
            verdict = "conditional"
            reason = "Workable but requires significant fine-tuning"
        else:
            verdict = "not_recommended"
            reason = "Insufficient spatial-behavioral capabilities"
        
        # Identify strengths/weaknesses
        strengths = []
        weaknesses = []
        
        if vla >= 0.8:
            strengths.append("VLA-native action tokens")
        else:
            weaknesses.append("Limited VLA-native capabilities")
        
        if position >= 0.8:
            strengths.append("Strong 3D spatial reasoning")
        else:
            weaknesses.append("Limited 3D position understanding")
        
        if latency >= 0.8:
            strengths.append("Good latency/throughput")
        else:
            weaknesses.append("Latency may be limiting")
        
        return {
            "verdict": verdict,
            "reason": reason,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "platform_suitability": {
                platform: "good" if overall >= 0.70 else "needs_optimization",
            },
        }


class VLAScoreCandidateTool(ToolBase):
    """
    Tool for scoring VLA model candidates specifically for Reachy Mini compatibility.
    
    Combines discovery results with analysis to provide ranked recommendations.
    """
    
    name = "vla.score_candidate"
    description = (
        "Score a VLA model candidate for Reachy Mini compatibility. "
        "Takes model discovery results and returns ranked scores with recommendations."
    )
    
    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of model candidates from discovery tools",
                    },
                    "prioritize_speed": {
                        "type": "boolean",
                        "description": "Prioritize low-latency models (for real-time control)",
                        "default": True,
                    },
                    "prioritize_spatial": {
                        "type": "boolean",
                        "description": "Prioritize strong 3D spatial reasoning",
                        "default": True,
                    },
                },
                "required": ["candidates"],
            },
        }
    
    async def run(
        self,
        candidates: List[Dict[str, Any]],
        prioritize_speed: bool = True,
        prioritize_spatial: bool = True,
    ) -> Dict[str, Any]:
        """
        Score and rank VLA model candidates.
        
        Returns:
            Dict with ranked candidates and top recommendations.
        """
        analyze_tool = VLAAnalyzeModelTool()
        
        scored_candidates = []
        for candidate in candidates:
            model_id = candidate.get("model_id", "")
            if not model_id:
                continue
            
            try:
                # Analyze the candidate
                analysis = await analyze_tool.run(
                    model_id=model_id,
                    model_metadata=candidate,
                    target_platform="reachy_mini",
                )
                
                # Calculate weighted score
                scores = analysis["scores"]
                weighted_score = (
                    scores["vla_native"] * 0.35 +
                    scores["3d_position_embedding"] * 0.30 +
                    scores["latency_throughput"] * (0.35 if prioritize_speed else 0.20) +
                    (scores["3d_position_embedding"] * 0.15 if prioritize_spatial else 0.0)
                )
                
                scored_candidates.append({
                    "model_id": model_id,
                    "weighted_score": weighted_score,
                    "analysis": analysis,
                    "original_metadata": candidate,
                })
                
            except Exception as e:
                logger.warning(f"Failed to analyze candidate {model_id}: {e}")
                continue
        
        # Sort by weighted score
        scored_candidates.sort(key=lambda x: x["weighted_score"], reverse=True)
        
        # Get top 3 recommendations
        top_recommendations = scored_candidates[:3]
        
        result = {
            "ranked_candidates": scored_candidates,
            "top_recommendations": [
                {
                    "rank": idx + 1,
                    "model_id": rec["model_id"],
                    "score": rec["weighted_score"],
                    "verdict": rec["analysis"]["recommendation"]["verdict"],
                    "reason": rec["analysis"]["recommendation"]["reason"],
                }
                for idx, rec in enumerate(top_recommendations)
            ],
            "total_scored": len(scored_candidates),
        }
        
        logger.info(
            f"✅ Scored {len(scored_candidates)} candidates. "
            f"Top: {top_recommendations[0]['model_id'] if top_recommendations else 'N/A'}"
        )
        
        return result


# ============================================================
# Registration Helper
# ============================================================

async def register_vla_analysis_tools(tool_manager: Any) -> None:
    """Register VLA analysis tools with ToolManager."""
    analyze_tool = VLAAnalyzeModelTool()
    await tool_manager.register(analyze_tool.name, analyze_tool)
    
    score_tool = VLAScoreCandidateTool()
    await tool_manager.register(score_tool.name, score_tool)
    
    logger.info("✅ Registered VLA analysis tools: vla.analyze_model, vla.score_candidate")
