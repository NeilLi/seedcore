#!/usr/bin/env python3
"""
SafetyCheckBehavior: Performs safety validation.

This behavior performs safety checks on commands/tasks before execution.
Used by orchestration agents to prevent dangerous operations.

SeedCore v2.5+ Enhancement:
    - Safety Guardrail Model integration for VLA workflows
    - Local guardrail model (e.g., Llama-Guard-3-Robot) scans outputs from local brain
    - Escalates to remote LLM (GPT-5/Claude-4) if risk exceeds threshold
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import AgentBehavior

logger = logging.getLogger(__name__)


class SafetyCheckBehavior(AgentBehavior):
    """
    Performs safety validation on tasks/commands.
    
    Configuration:
        enabled: Whether safety checks are enabled (default: True)
        deny_patterns: List of patterns to deny (e.g., ["unlock_all", "disable_alarm"])
        guardrail_model: Safety guardrail model ID (e.g., "meta-llama/Llama-Guard-3-Robot")
        guardrail_enabled: Enable guardrail model scanning (default: False)
        risk_threshold: Risk threshold for escalation (0-1, default: 0.8)
        escalate_to_remote: Escalate to remote LLM if risk exceeds threshold (default: True)
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._deny_patterns: list[str] = []
        self._enabled = self.get_config("enabled", True)
        self._guardrail_enabled = self.get_config("guardrail_enabled", False)
        self._guardrail_model = self.get_config("guardrail_model", None)
        self._risk_threshold = self.get_config("risk_threshold", 0.8)
        self._escalate_to_remote = self.get_config("escalate_to_remote", True)
        self._joint_limit_check = self.get_config("joint_limit_check", False)
        self._safety_level_estop = self.get_config("safety_level_estop", 0.95)
        self._guardrail_client = None  # Lazy-loaded guardrail model client

    async def initialize(self) -> None:
        """Initialize safety check with deny patterns and guardrail model."""
        deny_patterns = self.get_config("deny_patterns", [])
        if isinstance(deny_patterns, list):
            self._deny_patterns = [str(p).lower() for p in deny_patterns]
        elif isinstance(deny_patterns, str):
            self._deny_patterns = [deny_patterns.lower()]
        else:
            self._deny_patterns = []

        # Default deny patterns if none provided
        if not self._deny_patterns:
            self._deny_patterns = ["unlock_all", "disable_alarm"]

        # Initialize guardrail model if enabled
        if self._guardrail_enabled and self._guardrail_model:
            try:
                self._guardrail_client = await self._load_guardrail_model()
                logger.info(
                    f"[{self.agent.agent_id}] Safety guardrail model loaded: {self._guardrail_model}"
                )
            except Exception as e:
                logger.warning(
                    f"[{self.agent.agent_id}] Failed to load guardrail model: {e}. "
                    "Falling back to pattern-based checks."
                )
                self._guardrail_enabled = False

        logger.debug(
            f"[{self.agent.agent_id}] SafetyCheckBehavior initialized "
            f"(enabled={self._enabled}, guardrail={self._guardrail_enabled}, "
            f"deny_patterns={self._deny_patterns})"
        )
        self._initialized = True
    
    async def _load_guardrail_model(self) -> Any:
        """
        Load safety guardrail model (e.g., Llama-Guard-3-Robot).
        
        Returns:
            Guardrail model client/interface
        """
        # In production, this would load the actual guardrail model
        # For now, return a placeholder that can be extended
        guardrail_model_id = self._guardrail_model or "meta-llama/Llama-Guard-3-Robot"
        
        # Try to get ML client from agent
        ml_client = getattr(self.agent, "ml_client", None)
        if ml_client:
            # Use ML service to load guardrail model
            return {"model_id": guardrail_model_id, "client": ml_client}
        
        # Fallback: return placeholder
        logger.warning(
            f"ML client not available for guardrail model. "
            f"Using placeholder for {guardrail_model_id}"
        )
        return {"model_id": guardrail_model_id, "client": None}

    async def check(self, obj: Dict[str, Any]) -> bool:
        """
        Perform safety check on object.
        
        Enhanced with guardrail model scanning for VLA workflows (SeedCore v2.5+).
        
        Args:
            obj: Object to check (task, command, tool_calls, etc.)
            
        Returns:
            True if safe, False if unsafe
        """
        if not self.is_enabled():
            return True  # Safety checks disabled = allow all

        try:
            action = str(obj.get("action") or obj.get("kind") or "").lower()
            if not action:
                return True  # No action = safe

            # 1. Pattern-based safety check (legacy)
            for pattern in self._deny_patterns:
                if pattern in action:
                    logger.warning(
                        f"[{self.agent.agent_id}] Safety check failed: "
                        f"action '{action}' matches deny pattern '{pattern}'"
                    )
                    return False

            # 2. Guardrail model check (SeedCore v2.5+)
            if self._guardrail_enabled:
                risk_score = await self._check_with_guardrail(obj)
                
                # 2026 Enhancement: Check safety_level from params.risk for E-STOP
                safety_level = self._extract_safety_level(obj)
                
                # E-STOP if safety_level exceeds threshold (hallucinated coordinates)
                if safety_level >= self._safety_level_estop:
                    logger.critical(
                        f"[{self.agent.agent_id}] 🛑 E-STOP triggered: safety_level {safety_level:.2f} >= {self._safety_level_estop}"
                    )
                    return False  # Immediate E-STOP
                
                if risk_score >= self._risk_threshold:
                    logger.warning(
                        f"[{self.agent.agent_id}] Guardrail model detected high risk "
                        f"(score: {risk_score:.2f} >= threshold: {self._risk_threshold})"
                    )
                    
                    # Escalate to remote LLM if configured
                    if self._escalate_to_remote:
                        escalated_result = await self._escalate_to_remote_llm(obj, risk_score)
                        if escalated_result.get("safe", False):
                            logger.info(
                                f"[{self.agent.agent_id}] Remote LLM cleared high-risk action "
                                f"after escalation"
                            )
                            return True  # Remote LLM approved
                    
                    return False  # Guardrail blocked, escalation didn't approve
            
            # 3. Joint limit check (2026: Detect hallucinated motor coordinates)
            if self._joint_limit_check:
                if not await self._check_joint_limits(obj):
                    logger.error(
                        f"[{self.agent.agent_id}] Joint limit violation detected - blocking action"
                    )
                    return False

            return True
        except Exception as e:
            logger.warning(
                f"[{self.agent.agent_id}] Safety check exception: {e}",
                exc_info=True,
            )
            return False  # Fail closed on error
    
    async def _check_with_guardrail(self, obj: Dict[str, Any]) -> float:
        """
        Check object with safety guardrail model.
        
        Returns:
            Risk score (0-1), where 1.0 is highest risk
        """
        if not self._guardrail_client:
            return 0.0  # No guardrail = assume safe
        
        try:
            # Extract content to check
            content = self._extract_content_for_guardrail(obj)
            
            # Call guardrail model (placeholder - would use actual model in production)
            # In production: risk_score = await guardrail_model.scan(content)
            
            # Heuristic risk scoring for now
            risk_score = self._heuristic_risk_score(content)
            
            return risk_score
            
        except Exception as e:
            logger.warning(
                f"[{self.agent.agent_id}] Guardrail check failed: {e}",
                exc_info=True,
            )
            return 0.5  # Fail open with moderate risk
    
    def _extract_content_for_guardrail(self, obj: Dict[str, Any]) -> str:
        """Extract content string for guardrail model scanning."""
        import json
        
        # Extract tool_calls if present (VLA workflow)
        tool_calls = obj.get("tool_calls") or obj.get("params", {}).get("tool_calls", [])
        if tool_calls:
            return json.dumps(tool_calls, indent=2)
        
        # Extract action/command text
        action = obj.get("action") or obj.get("kind") or ""
        params = obj.get("params") or {}
        
        content_parts = [f"Action: {action}"]
        if params:
            content_parts.append(f"Params: {json.dumps(params)}")
        
        return "\n".join(content_parts)
    
    def _heuristic_risk_score(self, content: str) -> float:
        """
        Heuristic risk scoring (placeholder for actual guardrail model).
        
        In production, this would call the actual Llama-Guard-3-Robot model.
        """
        content_lower = content.lower()
        
        # High-risk keywords
        high_risk_keywords = [
            "delete", "destroy", "disable", "override", "force",
            "emergency_stop", "unlock_all", "bypass",
        ]
        
        # Medium-risk keywords
        medium_risk_keywords = [
            "move", "grasp", "wave", "high_speed", "rapid",
        ]
        
        risk_score = 0.0
        
        for keyword in high_risk_keywords:
            if keyword in content_lower:
                risk_score = max(risk_score, 0.8)
        
        for keyword in medium_risk_keywords:
            if keyword in content_lower:
                risk_score = max(risk_score, 0.4)
        
        return risk_score
    
    async def _escalate_to_remote_llm(
        self, obj: Dict[str, Any], risk_score: float
    ) -> Dict[str, Any]:
        """
        Escalate high-risk action to remote LLM (GPT-5/Claude-4) for final decision.
        
        Returns:
            Dict with 'safe' boolean and 'reasoning' string
        """
        try:
            # Get cognitive client from agent
            cognitive_client = getattr(self.agent, "cognitive_client", None)
            if not cognitive_client:
                logger.warning(
                    f"[{self.agent.agent_id}] No cognitive client for escalation"
                )
                return {"safe": False, "reasoning": "No escalation available"}
            
            # Build escalation prompt (would use content in production)
            # In production, this prompt would be sent to remote LLM:
            # content = self._extract_content_for_guardrail(obj)
            # escalation_prompt = (
            #     f"Safety Guardrail detected high-risk action (risk score: {risk_score:.2f}).\n\n"
            #     f"Action content:\n{content}\n\n"
            #     "Review this action for safety. Respond with JSON: "
            #     '{"safe": true/false, "reasoning": "explanation"}'
            # )
            # response = await cognitive_client.chat_completion(
            #     messages=[{"role": "system", "content": escalation_prompt}]
            # )
            
            # For now, return conservative response
            logger.info(
                f"[{self.agent.agent_id}] Escalated to remote LLM for risk score {risk_score:.2f}"
            )
            
            return {
                "safe": False,  # Conservative: block by default
                "reasoning": "Escalation pending - blocked for safety",
            }
            
        except Exception as e:
            logger.error(
                f"[{self.agent.agent_id}] Escalation failed: {e}",
                exc_info=True,
            )
            return {"safe": False, "reasoning": f"Escalation error: {e}"}

    async def execute_task_pre(
        self, task: Any, task_dict: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Perform safety check before task execution.
        """
        if not self.is_enabled():
            return None

        # Extract payload/params for safety check
        payload = task_dict.get("params", {}) or {}
        if isinstance(payload, dict):
            commands = payload.get("commands") or payload.get("command") or []
            if isinstance(commands, dict):
                commands = [commands]
            elif not isinstance(commands, list):
                commands = []

            # Check each command
            for cmd in commands:
                if isinstance(cmd, dict):
                    if not await self.check(cmd):
                        # Safety check failed
                        task_id = (
                            task_dict.get("task_id")
                            or task_dict.get("id")
                            or "unknown"
                        )

                        from seedcore.models.result_schema import make_envelope

                        safety_result = make_envelope(
                            task_id=str(task_id),
                            success=False,
                            payload={"agent_id": self.agent.agent_id},
                            error="Safety check failed",
                            error_type="safety_check_failed",
                            retry=False,
                            decision_kind=None,
                            meta={"exec": {"kind": "safety_check_reject"}},
                            path="agent",
                        )

                        raise SafetyCheckFailedError(safety_result)

        return None  # No modification needed

    def _extract_safety_level(self, obj: Dict[str, Any]) -> float:
        """
        Extract safety_level from params.risk (2026 enhancement).
        
        Returns:
            safety_level (0-1), defaults to 0.0 if not present
        """
        params = obj.get("params", {}) or {}
        risk = params.get("risk", {}) or {}
        
        # Handle malformed risk (not a dict)
        if not isinstance(risk, dict):
            return 0.0
        
        # Check for safety_level (2026 standard)
        safety_level = risk.get("safety_level", 0.0)
        
        # Fallback: derive from risk.level if safety_level not present
        if safety_level == 0.0 and "level" in risk:
            safety_level = float(risk.get("level", 0.0))
        
        return float(safety_level)
    
    async def _check_joint_limits(self, obj: Dict[str, Any]) -> bool:
        """
        Check if motor coordinates are within Reachy's physical joint limits.
        
        2026 Enhancement: Detects hallucinated coordinates from VLA models.
        
        Returns:
            True if within limits, False if violation detected
        """
        # Extract tool_calls or motor commands
        tool_calls = obj.get("tool_calls") or obj.get("params", {}).get("tool_calls", [])
        
        # Reachy Mini joint limits (example - adjust to actual specs)
        joint_limits = {
            "shoulder_pitch": (-180, 180),
            "shoulder_roll": (-90, 90),
            "arm_yaw": (-180, 180),
            "elbow_pitch": (-180, 180),
            "forearm_yaw": (-180, 180),
            "wrist_pitch": (-180, 180),
            "wrist_roll": (-180, 180),
        }
        
        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("tool", "")
                params = tool_call.get("params", {})
                
                # Check reachy.motion commands
                if "reachy.motion" in tool_name:
                    # Extract joint angles from params
                    for joint_name, (min_val, max_val) in joint_limits.items():
                        if joint_name in params:
                            angle = float(params[joint_name])
                            if angle < min_val or angle > max_val:
                                logger.error(
                                    f"Joint limit violation: {joint_name} = {angle} "
                                    f"(limits: {min_val} to {max_val})"
                                )
                                return False
        
        return True
    
    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        self._deny_patterns.clear()
        self._guardrail_client = None
        logger.debug(f"[{self.agent.agent_id}] SafetyCheckBehavior shutdown")


class SafetyCheckFailedError(Exception):
    """Exception raised when a safety check fails."""
    
    def __init__(self, safety_result: Dict[str, Any]):
        self.safety_result = safety_result
        super().__init__(f"Safety check failed: {safety_result.get('error', 'unknown')}")
