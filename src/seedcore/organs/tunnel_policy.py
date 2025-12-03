# src/seedcore/organs/tunnel_activation.py
from typing import Any, Set, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class TunnelActivationPolicy:
    """
    Determines whether an Agent's output warrants activating a persistent tunnel.
    Purely local heuristic — OrganismCore owns all tunnel lifecycle decisions.
    """

    def __init__(
        self,
        continuation_threshold: float = 0.7,
        interactive_intents: Optional[Set[str]] = None,
    ):
        self.continuation_threshold = continuation_threshold
        self.interactive_intents = interactive_intents or {
            "follow_up",
            "clarify",
            "question",
            "intermediate_step",
        }
        # Explicitly blocking intents (e.g., if agent says "task_complete", don't tunnel)
        self.terminal_statuses = {"completed", "finished", "final_answer"}

    def should_activate(self, agent_output: Any) -> bool:
        """
        Evaluate whether the agent output signals conversational continuity.
        Safe against None, malformed input, or Pydantic version mismatches.
        """
        data = self._normalize_to_dict(agent_output)
        if not data:
            return False

        # --- 0. Safety Check: Is task explicitly done? ---
        # If status is "completed", we should probably NOT tunnel,
        # even if the score is high (unless explicitly overridden).
        status = data.get("status")
        if isinstance(status, str) and status in self.terminal_statuses:
            # Check if explicit override exists, otherwise deny
            if not data.get("activate_tunnel"):
                return False

        # --- 1. explicit activation flags (highest priority) ---
        # Check root AND metadata
        meta = data.get("metadata", {})
        if not isinstance(meta, dict):
            meta = {}

        if data.get("activate_tunnel") is True or meta.get("activate_tunnel") is True:
            return True
        if data.get("request_tunnel") is True:  # legacy
            return True

        # --- 2. Intent-based heuristic ---
        # Check root intent or metadata intent
        intent = data.get("intent") or meta.get("intent")
        if isinstance(intent, str) and intent in self.interactive_intents:
            return True

        # --- 3. Statistical continuity signal ---
        # Often found in 'ocps' block or root
        try:
            prob = self._extract_continuation_prob(data, meta)
            if prob > self.continuation_threshold:
                return True
        except Exception:
            pass

        return False

    def _normalize_to_dict(self, obj: Any) -> Optional[Dict[str, Any]]:
        """Helper to safely convert Pydantic models (v1/v2) or dataclasses."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj

        # Pydantic V2
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        # Pydantic V1
        if hasattr(obj, "dict"):
            return obj.dict()
        # Standard object
        if hasattr(obj, "__dict__"):
            return obj.__dict__

        return None

    def _extract_continuation_prob(self, data: Dict, meta: Dict) -> float:
        """Scans common locations for probability scores."""
        # 1. Root level
        if "continuation_prob" in data:
            return float(data["continuation_prob"])

        # 2. Metadata level
        if "continuation_prob" in meta:
            return float(meta["continuation_prob"])

        # 3. OCPS block (common in your architecture)
        ocps = data.get("ocps", {})
        if isinstance(ocps, dict) and "uncertainty_score" in ocps:
            # Inverting uncertainty? Or logic specific to your model?
            # Assuming you might have a continuity score here too.
            return float(ocps.get("continuity", 0.0))

        return 0.0
