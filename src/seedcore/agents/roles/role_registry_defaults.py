# agents/roles/role_registry_defaults.py
"""
Default RoleRegistry for the futuristic hotel scenario.

Each RoleProfile encodes:
- default_skills: baseline skill priors (0..1)
- allowed_tools: RBAC tool identifiers
- visibility_scopes: data partitions (e.g., "guest_profile", "room_iot")
- routing_tags: hints for task routing
- safety_policies: soft/hard operational limits

You can extend or override these profiles at startup by composing registries.
"""

from __future__ import annotations

from typing import Dict
from .specialization import (
    Specialization,
    RoleProfile,
    RoleRegistry,
)

# --- Tool name conventions (examples) ---
# Use consistent, namespaced tool identifiers across your ToolManager.
# Feel free to adjust to your actual catalog.
T = {
    # common
    "mem_read": "mem.read",
    "mem_write": "mem.write",
    "notify": "notify.send",
    "ticket_create": "ticket.create",
    "search_web": "search.web",
    # guest relations
    "crm_lookup": "crm.lookup",
    "crm_update": "crm.update",
    "msg_guest": "guest.message",
    "eta_calc": "dispatch.eta",
    # iot/engineering
    "iot_read": "iot.read",
    "iot_write": "iot.write",
    "eng_dispatch": "eng.dispatch",
    "bms_query": "bms.query",
    # security
    "key_issue": "security.key.issue",
    "key_revoke": "security.key.revoke",
    "access_log": "security.access.log",
    "camera_review": "security.camera.review",
    # f&b
    "kitchen_orchestrate": "kitchen.orchestrate",
    "inventory_query": "inventory.query",
    "vendor_lookup": "vendor.lookup",
    # robots
    "robot_dispatch": "robot.dispatch",
    "robot_track": "robot.track",
    # meta/learning
    "policy_audit": "policy.audit",
    "promote_role": "role.promote",
    "demote_role": "role.demote",
}

# --- Visibility scopes (examples) ---
SCOPE = {
    "guest_profile": "guest_profile",
    "guest_history": "guest_history",
    "room_iot": "room_iot",
    "bms": "bms",  # building management system
    "security_logs": "security_logs",
    "kitchen": "kitchen",
    "inventory": "inventory",
    "swarm_metrics": "swarm_metrics",
    "audit_trail": "audit_trail",
}

# --- Safety policy defaults (examples) ---
SAFE = {
    "low_autonomy": {"max_autonomy": 0.3, "requires_human_review": 0.5},
    "medium_autonomy": {"max_autonomy": 0.6, "requires_human_review": 0.3},
    "high_autonomy": {"max_autonomy": 0.85, "requires_human_review": 0.1},
    "strict_cost": {"max_cost_usd": 5.0},
    "standard_cost": {"max_cost_usd": 20.0},
    "open_cost": {"max_cost_usd": 200.0},
}


def _merge_policies(*dicts: Dict[str, float]) -> Dict[str, float]:
    merged: Dict[str, float] = {}
    for d in dicts:
        merged.update(d)
    return merged


def build_default_role_registry() -> RoleRegistry:
    reg = RoleRegistry()

    # --- Generalist ---
    reg.register(RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={
            "analysis": 0.6,
            "planning": 0.6,
            "communication": 0.6,
        },
        allowed_tools={
            T["mem_read"], T["mem_write"], T["notify"], T["search_web"], T["ticket_create"]
        },
        visibility_scopes={SCOPE["guest_profile"], SCOPE["room_iot"], SCOPE["bms"]},
        routing_tags={"default"},
        safety_policies=_merge_policies(SAFE["medium_autonomy"], SAFE["standard_cost"]),
    ))

    # --- Guest Empathy Agent (GEA) ---
    reg.register(RoleProfile(
        name=Specialization.GEA,
        default_skills={
            "empathy": 0.9,
            "service_recovery": 0.8,
            "language_finesse": 0.8,
            "de_escalation": 0.7,
        },
        allowed_tools={
            T["mem_read"], T["mem_write"], T["notify"],
            T["crm_lookup"], T["crm_update"], T["msg_guest"], T["ticket_create"]
        },
        visibility_scopes={SCOPE["guest_profile"], SCOPE["guest_history"], SCOPE["audit_trail"]},
        routing_tags={"guest_relations", "vip"},
        safety_policies=_merge_policies(SAFE["medium_autonomy"], SAFE["standard_cost"]),
    ))

    # --- Proactive Experience Agent (PEA) ---
    reg.register(RoleProfile(
        name=Specialization.PEA,
        default_skills={
            "anomaly_detection": 0.85,
            "proactive_planning": 0.8,
            "iot_contexting": 0.8,
        },
        allowed_tools={T["mem_read"], T["notify"], T["iot_read"], T["eng_dispatch"], T["bms_query"]},
        visibility_scopes={SCOPE["room_iot"], SCOPE["bms"], SCOPE["audit_trail"]},
        routing_tags={"proactive", "monitoring"},
        safety_policies=_merge_policies(SAFE["high_autonomy"], SAFE["standard_cost"]),
    ))

    # --- Robotic Concierge Dispatcher (RCD) ---
    reg.register(RoleProfile(
        name=Specialization.RCD,
        default_skills={
            "dispatch_planning": 0.8,
            "route_optimization": 0.8,
            "guest_coordination": 0.7,
        },
        allowed_tools={T["robot_dispatch"], T["robot_track"], T["eta_calc"], T["notify"], T["mem_read"]},
        visibility_scopes={SCOPE["guest_profile"], SCOPE["room_iot"]},
        routing_tags={"concierge", "logistics"},
        safety_policies=_merge_policies(SAFE["high_autonomy"], SAFE["standard_cost"]),
    ))

    # --- Asset & Access Controller (AAC) ---
    reg.register(RoleProfile(
        name=Specialization.AAC,
        default_skills={
            "key_management": 0.85,
            "access_policy": 0.85,
            "identity_resolution": 0.75,
        },
        allowed_tools={T["key_issue"], T["key_revoke"], T["access_log"], T["camera_review"], T["mem_read"], T["notify"]},
        visibility_scopes={SCOPE["security_logs"], SCOPE["audit_trail"], SCOPE["guest_profile"]},
        routing_tags={"security", "access"},
        safety_policies=_merge_policies(SAFE["medium_autonomy"], SAFE["strict_cost"]),
    ))

    # --- Digital Security Sentinel (DSS) ---
    reg.register(RoleProfile(
        name=Specialization.DSS,
        default_skills={
            "intrusion_detection": 0.9,
            "policy_auditing": 0.85,
            "incident_triage": 0.8,
        },
        allowed_tools={T["policy_audit"], T["access_log"], T["camera_review"], T["mem_read"], T["notify"]},
        visibility_scopes={SCOPE["security_logs"], SCOPE["audit_trail"], SCOPE["swarm_metrics"]},
        routing_tags={"security", "monitoring"},
        safety_policies=_merge_policies(SAFE["high_autonomy"], SAFE["strict_cost"]),
    ))

    # --- Culinary Innovation Scout (CIS) ---
    reg.register(RoleProfile(
        name=Specialization.CIS,
        default_skills={
            "allergen_safety": 0.9,
            "vendor_scouting": 0.8,
            "substitution_planning": 0.8,
        },
        allowed_tools={T["vendor_lookup"], T["inventory_query"], T["mem_read"], T["notify"], T["ticket_create"]},
        visibility_scopes={SCOPE["guest_profile"], SCOPE["inventory"], SCOPE["audit_trail"]},
        routing_tags={"fnb", "scout"},
        safety_policies=_merge_policies(SAFE["medium_autonomy"], SAFE["standard_cost"]),
    ))

    # --- Robotic Kitchen Orchestrator (RKO) ---
    reg.register(RoleProfile(
        name=Specialization.RKO,
        default_skills={
            "recipe_compilation": 0.85,
            "allergen_isolation": 0.9,
            "line_orchestration": 0.85,
        },
        allowed_tools={T["kitchen_orchestrate"], T["inventory_query"], T["mem_read"], T["notify"]},
        visibility_scopes={SCOPE["kitchen"], SCOPE["inventory"], SCOPE["audit_trail"]},
        routing_tags={"fnb", "kitchen"},
        safety_policies=_merge_policies(SAFE["high_autonomy"], SAFE["standard_cost"]),
    ))

    # --- Building Health Monitor (BHM) ---
    reg.register(RoleProfile(
        name=Specialization.BHM,
        default_skills={
            "fault_forecasting": 0.9,
            "hvac_diagnostics": 0.85,
            "trend_modeling": 0.85,
        },
        allowed_tools={T["iot_read"], T["bms_query"], T["notify"], T["mem_read"], T["eng_dispatch"]},
        visibility_scopes={SCOPE["bms"], SCOPE["room_iot"], SCOPE["audit_trail"]},
        routing_tags={"engineering", "monitoring"},
        safety_policies=_merge_policies(SAFE["high_autonomy"], SAFE["standard_cost"]),
    ))

    # --- Robotic Maintenance Dispatcher (RMD) ---
    reg.register(RoleProfile(
        name=Specialization.RMD,
        default_skills={
            "dispatch_optimization": 0.85,
            "spare_parts_matching": 0.8,
            "work_order_planning": 0.8,
        },
        allowed_tools={T["eng_dispatch"], T["iot_read"], T["bms_query"], T["notify"], T["mem_read"]},
        visibility_scopes={SCOPE["bms"], SCOPE["room_iot"], SCOPE["audit_trail"]},
        routing_tags={"engineering", "logistics"},
        safety_policies=_merge_policies(SAFE["high_autonomy"], SAFE["open_cost"]),
    ))

    # --- Incident Resolution Specialist (IRS) ---
    reg.register(RoleProfile(
        name=Specialization.IRS,
        default_skills={
            "cross_organ_coordination": 0.9,
            "crisis_playbooks": 0.9,
            "authority_escalation": 0.85,
        },
        allowed_tools={
            T["notify"], T["ticket_create"], T["crm_lookup"], T["eng_dispatch"],
            T["robot_dispatch"], T["policy_audit"], T["mem_read"], T["mem_write"]
        },
        visibility_scopes={
            SCOPE["guest_profile"], SCOPE["guest_history"], SCOPE["room_iot"],
            SCOPE["bms"], SCOPE["security_logs"], SCOPE["audit_trail"]
        },
        routing_tags={"incident_response", "cross_organ"},
        safety_policies=_merge_policies(SAFE["medium_autonomy"], SAFE["open_cost"]),
    ))

    # --- Utility & Learning Agent (ULA) ---
    reg.register(RoleProfile(
        name=Specialization.ULA,
        default_skills={
            "meta_rl_tuning": 0.85,
            "consolidation_selection": 0.85,
            "kpi_monitoring": 0.9,
        },
        allowed_tools={T["policy_audit"], T["mem_read"], T["mem_write"], T["notify"]},
        visibility_scopes={SCOPE["swarm_metrics"], SCOPE["audit_trail"]},
        routing_tags={"learning", "observer"},
        safety_policies=_merge_policies(SAFE["low_autonomy"], SAFE["strict_cost"]),
    ))

    return reg


# Export a ready-to-use default registry
DEFAULT_ROLE_REGISTRY: RoleRegistry = build_default_role_registry()
