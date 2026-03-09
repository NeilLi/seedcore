#!/usr/bin/env python3
"""
Shared PKG result normalization utilities.

These helpers convert raw evaluator output into the stable
"decision + emissions + provenance" shape exposed by the API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class PolicyGateBlockedError(Exception):
    """Raised when a policy gate blocks execution and the caller wants an HTTP-style error."""

    def __init__(
        self,
        rule_id: Optional[str],
        rule_name: Optional[str],
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.reason = reason


def normalize_policy_result(
    result: Dict[str, Any],
    *,
    raise_on_gate_block: bool = True,
) -> Dict[str, Any]:
    """
    Convert evaluator output into the stable API contract.

    Args:
        result: Raw evaluator output from PKGManager/PKGEvaluator.
        raise_on_gate_block: When True, policy gates raise PolicyGateBlockedError.
            When False, blocked gates are represented as a denied decision.
    """
    subtasks = result.get("subtasks", []) or []
    rules = result.get("rules") or []
    dag = result.get("dag", []) or []

    gate_emissions_in_dag = [
        edge
        for edge in dag
        if isinstance(edge, dict) and edge.get("type") == "gate"
    ]

    gate_rules: List[Dict[str, Any]] = []
    for rule in rules:
        emissions = rule.get("emissions", [])
        if not isinstance(emissions, list):
            continue
        for emission in emissions:
            if (
                isinstance(emission, dict)
                and emission.get("relationship_type") == "GATE"
            ):
                gate_rules.append(rule)
                break

    has_gate_emissions = bool(gate_emissions_in_dag or gate_rules)
    gate_rule_id: Optional[str] = None
    gate_rule_name: Optional[str] = None

    if has_gate_emissions and len(subtasks) == 0:
        if gate_rules:
            gate_rule = gate_rules[0]
            gate_rule_id = gate_rule.get("rule_id") or gate_rule.get("rule_name")
            gate_rule_name = gate_rule.get("rule_name")
        elif gate_emissions_in_dag:
            gate_rule_name = gate_emissions_in_dag[0].get("rule")
            for rule in rules:
                if rule.get("rule_name") == gate_rule_name:
                    gate_rule_id = rule.get("rule_id") or rule.get("rule_name")
                    break

        reason = f"Policy gate blocked request: {gate_rule_name or 'unknown'}"
        if raise_on_gate_block:
            raise PolicyGateBlockedError(
                gate_rule_id or gate_rule_name or "unknown_gate",
                gate_rule_name,
                reason,
            )

    if has_gate_emissions and len(subtasks) == 0:
        decision_reason = gate_rule_name or gate_rule_id or "blocked_by_policy_gate"
    elif rules:
        decision_reason = rules[0].get("rule_name") or rules[0].get("rule_id") or "matched_rule"
    else:
        decision_reason = "blocked_by_default" if len(subtasks) == 0 else "no_policy_emissions"

    provenance: Dict[str, Any] = {
        "rules": rules,
        "snapshot": result.get("snapshot"),
    }

    hydrated = result.get("_hydrated") if isinstance(result.get("_hydrated"), dict) else {}
    if hydrated.get("governed_facts") is not None:
        provenance["governed_facts"] = hydrated.get("governed_facts")
    if hydrated.get("semantic_context") is not None:
        provenance["semantic_context"] = hydrated.get("semantic_context")

    return {
        "decision": {
            "allowed": len(subtasks) > 0,
            "reason": decision_reason,
        },
        "emissions": {
            "subtasks": subtasks,
            "dag": dag,
        },
        "provenance": provenance,
        "meta": result.get("meta", {}),
    }
