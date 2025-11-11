# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Lifecycle transitions (Scout <-> Employed <-> Specialist, plus Onlooker, Archived).

Features:
- Tunable thresholds via LifecycleConfig
- Hysteresis & cooldowns to prevent flapping
- Demotion & idle archiving
- Event hooks for audit/telemetry
- Metric helpers integrated with AgentState
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Any, Optional

from .base import BaseAgent
from .state import AgentState


# ----------------------------------------------------------------------
# Types & Configuration
# ----------------------------------------------------------------------

class LifecycleState(str, Enum):
    SCOUT = "Scout"
    EMPLOYED = "Employed"
    SPECIALIST = "Specialist"
    ONLOOKER = "Onlooker"
    ARCHIVED = "Archived"


@dataclass
class LifecycleConfig:
    # Promotion thresholds
    theta_evolve: float = 0.65          # Employed -> Scout
    theta_specialize: float = 0.80      # Scout -> Specialist

    # Demotion thresholds (hysteresis: lower than promotions)
    theta_demote_scout: float = 0.58    # Scout -> Employed
    theta_demote_specialist: float = 0.72  # Specialist -> Employed

    # Aux conditions
    min_success_rate: float = 0.55      # require over last window
    max_mem_util_for_promo: float = 0.85  # avoid promotion under heavy load

    # Idling / archival
    max_idle_ticks: int = 1000
    archive_on_idle: bool = True

    # Cooldowns (seconds) to avoid state flapping
    cooldown_promotion_s: float = 300.0
    cooldown_demotion_s: float = 300.0

    # Specialization extras
    require_discovery_for_specialist: bool = True   # discovered_pattern gate
    spawn_suborgan_on_specialist: bool = True       # signal spawner

    # Onlooker demotion triggers
    q_drop_onlooker: float = 0.45                   # very low quality avg
    success_rate_onlooker: float = 0.35             # very low success rate


@dataclass
class LifecycleDecision:
    new_state: str
    spawn_suborgan: bool = False
    archive: bool = False
    reason: str = ""


EmitFn = Callable[[Dict[str, Any]], None]


def _null_emit(_: Dict[str, Any]) -> None:
    return


# ----------------------------------------------------------------------
# Core Lifecycle Evaluation
# ----------------------------------------------------------------------

def evaluate_lifecycle(
    agent: BaseAgent,
    cfg: Optional[LifecycleConfig] = None,
    emit: EmitFn = _null_emit,
) -> LifecycleDecision:
    """
    Decide lifecycle transitions based on AgentState KPIs + configuration.

    Reads:
      - agent.lifecycle_state (string or LifecycleState)
      - agent.idle_ticks / agent.max_idle
      - agent._archived (optional)
      - agent.state (AgentState)
      - agent.discovered_pattern (optional bool for specialization)

    Writes (the caller typically applies these on the agent):
      - lifecycle_state
      - _archived
      - spawn suborgan signal (returned in decision)
    """
    cfg = cfg or LifecycleConfig()

    # Resolve current state (tolerate legacy string values)
    current_state = str(getattr(agent, "lifecycle_state", LifecycleState.EMPLOYED.value))
    if current_state not in LifecycleState._value2member_map_:
        current_state = LifecycleState.EMPLOYED.value

    state = agent.state if isinstance(agent.state, AgentState) else None
    c = state.c if state else float(getattr(agent, "capability", 0.0))
    mem_util = state.mem_util if state else float(getattr(agent, "mem_util", 0.0))
    success_rate = state.rolling_success_rate() if state else None
    quality_avg = state.rolling_quality_avg() if state else None

    idle_ticks = int(getattr(agent, "idle_ticks", 0))
    max_idle = int(getattr(agent, "max_idle", cfg.max_idle_ticks))
    archived_flag = bool(getattr(agent, "_archived", False))
    discovered_pattern = bool(getattr(agent, "discovered_pattern", False))

    # Early exit if already archived
    if archived_flag or current_state == LifecycleState.ARCHIVED.value:
        return LifecycleDecision(new_state=LifecycleState.ARCHIVED.value, archive=True, reason="already_archived")

    # Cooldown guards (we read last change timestamps if the agent maintains them)
    last_promo_ts = float(getattr(agent, "_last_promotion_ts", 0.0))
    last_demo_ts = float(getattr(agent, "_last_demotion_ts", 0.0))
    now = getattr(agent, "_now", None)
    # Allow testability: agent._now can be injected; otherwise monotonic-ish approximation
    import time as _t
    now = float(now if isinstance(now, (int, float)) else _t.time())

    can_promote = (now - last_promo_ts) >= cfg.cooldown_promotion_s
    can_demote = (now - last_demo_ts) >= cfg.cooldown_demotion_s

    # Qualification helpers
    sr_ok = (success_rate is None) or (success_rate >= cfg.min_success_rate)
    not_overloaded = mem_util <= cfg.max_mem_util_for_promo

    # --- Idle archiving ---
    if cfg.archive_on_idle and idle_ticks > max_idle:
        emit({"event": "lifecycle_archive_idle", "agent_id": agent.agent_id, "idle_ticks": idle_ticks})
        return LifecycleDecision(new_state=LifecycleState.ARCHIVED.value, archive=True, reason="idle_archive")

    # --- Onlooker demotion (harsh drop) ---
    if current_state in (LifecycleState.EMPLOYED.value, LifecycleState.SCOUT.value, LifecycleState.SPECIALIST.value):
        if (quality_avg is not None and quality_avg <= cfg.q_drop_onlooker) or (
            success_rate is not None and success_rate <= cfg.success_rate_onlooker
        ):
            if can_demote:
                emit({
                    "event": "lifecycle_to_onlooker",
                    "agent_id": agent.agent_id,
                    "from": current_state,
                    "quality_avg": quality_avg,
                    "success_rate": success_rate,
                })
                return LifecycleDecision(new_state=LifecycleState.ONLOOKER.value, reason="onlooker_drop")

    # --- Promotions / Demotions with hysteresis ---
    if current_state == LifecycleState.EMPLOYED.value:
        # Promote to SCOUT
        if can_promote and c >= cfg.theta_evolve and sr_ok and not_overloaded:
            emit({
                "event": "lifecycle_promote",
                "agent_id": agent.agent_id,
                "from": current_state,
                "to": LifecycleState.SCOUT.value,
                "c": c, "mem_util": mem_util, "success_rate": success_rate,
            })
            setattr(agent, "_last_promotion_ts", now)
            return LifecycleDecision(new_state=LifecycleState.SCOUT.value, reason="promote_evolve")
        # Stay
        return LifecycleDecision(new_state=current_state, reason="stay_employed")

    if current_state == LifecycleState.SCOUT.value:
        # Specialize if strong & discovered pattern
        if can_promote and c >= cfg.theta_specialize and sr_ok and not_overloaded:
            if (not cfg.require_discovery_for_specialist) or discovered_pattern:
                emit({
                    "event": "lifecycle_specialize",
                    "agent_id": agent.agent_id,
                    "from": current_state,
                    "to": LifecycleState.SPECIALIST.value,
                    "c": c, "discovered_pattern": discovered_pattern,
                })
                setattr(agent, "_last_promotion_ts", now)
                return LifecycleDecision(
                    new_state=LifecycleState.SPECIALIST.value,
                    spawn_suborgan=cfg.spawn_suborgan_on_specialist,
                    reason="promote_specialist",
                )
        # Demote back to EMPLOYED (hysteresis)
        if can_demote and (c <= cfg.theta_demote_scout or not sr_ok):
            emit({
                "event": "lifecycle_demote",
                "agent_id": agent.agent_id,
                "from": current_state,
                "to": LifecycleState.EMPLOYED.value,
                "c": c, "success_rate": success_rate,
            })
            setattr(agent, "_last_demotion_ts", now)
            return LifecycleDecision(new_state=LifecycleState.EMPLOYED.value, reason="demote_scout")
        # Stay
        return LifecycleDecision(new_state=current_state, reason="stay_scout")

    if current_state == LifecycleState.SPECIALIST.value:
        # Demote if capability slips (hysteresis)
        if can_demote and (c <= cfg.theta_demote_specialist or not sr_ok):
            emit({
                "event": "lifecycle_demote",
                "agent_id": agent.agent_id,
                "from": current_state,
                "to": LifecycleState.EMPLOYED.value,
                "c": c, "success_rate": success_rate,
            })
            setattr(agent, "_last_demotion_ts", now)
            return LifecycleDecision(new_state=LifecycleState.EMPLOYED.value, reason="demote_specialist")
        # Stay
        return LifecycleDecision(new_state=current_state, reason="stay_specialist")

    if current_state == LifecycleState.ONLOOKER.value:
        # Recovery path: if capability & success recover above evolve threshold, rejoin Employed
        if can_promote and c >= cfg.theta_evolve and sr_ok:
            emit({
                "event": "lifecycle_rejoin",
                "agent_id": agent.agent_id,
                "from": current_state,
                "to": LifecycleState.EMPLOYED.value,
                "c": c, "success_rate": success_rate,
            })
            setattr(agent, "_last_promotion_ts", now)
            return LifecycleDecision(new_state=LifecycleState.EMPLOYED.value, reason="onlooker_rejoin")
        # Optional idle archive from Onlooker
        if cfg.archive_on_idle and idle_ticks > max_idle:
            emit({"event": "lifecycle_archive_idle", "agent_id": agent.agent_id})
            return LifecycleDecision(new_state=LifecycleState.ARCHIVED.value, archive=True, reason="idle_archive")
        return LifecycleDecision(new_state=current_state, reason="stay_onlooker")

    # Fallback: unknown -> Employed
    emit({"event": "lifecycle_reset_unknown", "agent_id": agent.agent_id, "from": current_state})
    return LifecycleDecision(new_state=LifecycleState.EMPLOYED.value, reason="reset_unknown")


# ----------------------------------------------------------------------
# Metric Helpers (integrated with AgentState)
# ----------------------------------------------------------------------

def update_agent_metrics(
    agent_state: AgentState,
    task_success: bool,
    task_quality: float,
    mem_stats: Dict[str, float],
    *,
    observed_capability: Optional[float] = None,
    salience: Optional[float] = None,
    duration_s: Optional[float] = None,
) -> None:
    """
    Update agent capability (EWMA), memory utility, and rolling KPIs.

    This version uses AgentState's built-ins:
      - record_task_outcome()
      - update_capability()
    It also computes a simple memory utility update from mem_stats.
    """
    # Record outcome metrics first
    agent_state.record_task_outcome(
        success=bool(task_success),
        quality=float(task_quality),
        salience=float(salience) if salience is not None else None,
        duration_s=float(duration_s) if duration_s is not None else None,
        capability_observed=float(observed_capability) if observed_capability is not None else None,
    )

    # Memory utility: normalized combination (0..1). You can replace with a learned model.
    # Expect mem_stats keys: hits (0..1), compr_gain (0..1), salience (0..1)
    w_hit, w_compr, w_sal = 0.5, 0.3, 0.2
    hits = float(mem_stats.get("hits", 0.0))
    compr = float(mem_stats.get("compr_gain", 0.0))
    sal = float(mem_stats.get("salience", 0.0))
    mem_perf = max(0.0, min(1.0, w_hit * hits + w_compr * compr + w_sal * sal))

    agent_state.update_mem_util(mem_perf)


def calculate_pair_weight(agent_i_state: AgentState, agent_j_state: AgentState) -> float:
    """
    Pair weight is min(ci, cj), as specified in the blueprint.
    """
    return float(min(agent_i_state.c, agent_j_state.c))


def apply_memory_discount(agent_state: AgentState, base_cost: float) -> float:
    """
    Apply memory cost discount based on agent's memory utility (ui).
    Higher mem_util reduces memory cost; floor at 50% of base.
    """
    ui = float(agent_state.mem_util)
    discount_factor = max(0.5, 1.0 - 0.5 * ui)  # 0.5 .. 1.0
    return float(base_cost) * discount_factor
