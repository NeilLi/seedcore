# agents/roles/rbac.py
"""
RBAC: Tool & data access enforcement based on RoleProfile.

This module centralizes authorization checks and policy application for
both tool execution and data visibility. It is intentionally lightweight
and framework-agnostic.

Key concepts:
- RoleProfile.allowed_tools: set[str]  → tool-level RBAC
- RoleProfile.visibility_scopes: set[str] → data partitions/indices
- RoleProfile.safety_policies: dict[str, float] → autonomy/cost/risk limits

Typical safety keys (conventions, not enforced by schema):
- "max_autonomy": float in [0,1]   (how independent the agent may act)
- "requires_human_review": float in [0,1] probability/threshold
- "max_cost_usd": float (upper bound per action/request)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .specialization import RoleProfile


# ---------- Decision & Audit -----------------------------------------------------


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str = ""
    # Optional normalized constraints the caller should respect (e.g., LLM params, cost caps)
    constraints: Dict[str, Any] = field(default_factory=dict)


AuditSink = Callable[[Dict[str, Any]], None]


def null_audit_sink(_: Dict[str, Any]) -> None:
    """Default no-op audit sink."""
    return


# ---------- RBAC Enforcer --------------------------------------------------------


class RbacEnforcer:
    """
    Minimal RBAC engine that:
      - Checks tool permissions against RoleProfile.allowed_tools
      - Checks data scope access against RoleProfile.visibility_scopes
      - Applies safety constraints from RoleProfile.safety_policies
      - Emits structured audit events to an injected sink
    """

    def __init__(self, audit_sink: AuditSink = null_audit_sink) -> None:
        self._audit = audit_sink

    # ---- Tool Authorization -----------------------------------------------------

    def authorize_tool(
        self,
        role: RoleProfile,
        tool_name: str,
        *,
        cost_usd: Optional[float] = None,
        autonomy: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AccessDecision:
        """
        Check if a tool is permitted for this role, and apply safety constraints.
        Returns an AccessDecision with constraints to honor downstream.
        """
        context = context or {}
        if tool_name not in role.allowed_tools:
            self._emit("tool_denied", role, extra={"tool": tool_name, **context})
            return AccessDecision(False, reason=f"tool '{tool_name}' not permitted")

        # Safety constraints
        constraints = dict(role.safety_policies or {})

        # Hard limit: max_cost_usd
        max_cost = _as_float(constraints.get("max_cost_usd"))
        if max_cost is not None and cost_usd is not None and cost_usd > max_cost:
            self._emit(
                "tool_denied_cost_cap",
                role,
                extra={"tool": tool_name, "cost_usd": cost_usd, "max_cost_usd": max_cost, **context},
            )
            return AccessDecision(False, reason=f"cost {cost_usd:.2f} exceeds cap {max_cost:.2f}")

        # Hard/soft autonomy envelope
        max_autonomy = _as_float(constraints.get("max_autonomy"))
        if max_autonomy is not None and autonomy is not None and autonomy > max_autonomy:
            self._emit(
                "tool_denied_autonomy_cap",
                role,
                extra={"tool": tool_name, "autonomy": autonomy, "max_autonomy": max_autonomy, **context},
            )
            return AccessDecision(False, reason=f"autonomy {autonomy:.2f} exceeds cap {max_autonomy:.2f}")

        self._emit("tool_allowed", role, extra={"tool": tool_name, "constraints": constraints, **context})
        return AccessDecision(True, reason="ok", constraints=constraints)

    # ---- Data Scope Authorization ----------------------------------------------

    def authorize_scope(
        self,
        role: RoleProfile,
        scope_name: str,
        *,
        mode: str = "read",
        context: Optional[Dict[str, Any]] = None,
    ) -> AccessDecision:
        """
        Check if a data scope is visible to this role.
        Mode is advisory (e.g., "read"|"write") for logging and future policies.
        """
        context = context or {}
        if scope_name not in role.visibility_scopes:
            self._emit("scope_denied", role, extra={"scope": scope_name, "mode": mode, **context})
            return AccessDecision(False, reason=f"scope '{scope_name}' not visible to role")
        self._emit("scope_allowed", role, extra={"scope": scope_name, "mode": mode, **context})
        return AccessDecision(True, reason="ok")

    # ---- Safety Policy Helpers --------------------------------------------------

    def llm_param_constraints(self, role: RoleProfile) -> Dict[str, Any]:
        """
        Export safety constraints into LLM parameter hints (caller can map these).
        Example mapping (caller-side):
          - max_autonomy → restrict tool-use chain depth
          - requires_human_review → elevate review probability/threshold
          - max_cost_usd → attach to planner budget
        """
        return dict(role.safety_policies or {})

    # ---- Audit ------------------------------------------------------------------

    def _emit(self, event: str, role: RoleProfile, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "event": event,
            "role": role.name.value,
            "routing_tags": sorted(role.routing_tags),
            "allowed_tools": sorted(role.allowed_tools),
            "visibility_scopes": sorted(role.visibility_scopes),
        }
        if extra:
            payload.update(extra)
        try:
            self._audit(payload)
        except Exception:
            # Never fail caller due to audit issues
            pass


def _as_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None
