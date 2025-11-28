# src/seedcore/organs/tunnel_activation.py
from typing import Any, Set

class TunnelActivationPolicy:
    """
    Determines whether an Agent's output warrants activating a persistent tunnel.
    Purely local heuristic — OrganismCore owns all tunnel lifecycle decisions.
    """

    # Tunable parameters
    CONTINUATION_THRESHOLD: float = 0.7
    INTERACTIVE_INTENTS: Set[str] = {"follow_up", "clarify", "question"}

    def should_activate(self, agent_output: Any) -> bool:
        """
        Evaluate whether the agent output signals conversational continuity.
        Safe against None or malformed input.
        """
        if agent_output is None:
            return False

        # Support Pydantic or custom objects (convert to dict if needed)
        if not isinstance(agent_output, dict):
            try:
                agent_output = agent_output.dict()
            except Exception:
                return False

        # --- 1. Explicit activation flags (highest priority) ---
        if agent_output.get("activate_tunnel") is True:
            return True
        if agent_output.get("request_tunnel") is True:
            return True  # legacy compat

        # --- 2. Intent-based heuristic ---
        intent = agent_output.get("intent")
        if isinstance(intent, str) and intent in self.INTERACTIVE_INTENTS:
            return True

        # --- 3. Statistical continuity signal ---
        try:
            prob = float(agent_output.get("continuation_prob", 0.0))
            if prob > self.CONTINUATION_THRESHOLD:
                return True
        except (TypeError, ValueError):
            # If model returned weird values ("high", "", None, etc.)
            pass

        return False
