# agents/roles/skill_learning.py
"""
Outcome-driven skill updates and specialization adjustment.

This module provides:
- LearningConfig: tuning knobs for per-outcome skill updates.
- PromotionPolicy: criteria and cooldowns for role changes (promotion/demotion).
- SkillLearner: stateful helper that updates SkillVector and recommends specialization changes.

It is *pure-python* and only depends on RoleRegistry / Specialization / RoleProfile and SkillVector.
Hook it up from your agent after each task outcome.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from statistics import mean
from typing import Deque, Dict, Optional, Tuple, Any, List

from .specialization import Specialization, RoleRegistry, RoleProfile
from .skill_vector import SkillVector


@dataclass
class LearningConfig:
    """
    Controls how outcomes translate into skill delta updates.
    """
    # Base learning rates
    lr_success: float = 0.02
    lr_failure: float = -0.015
    lr_escalation_penalty: float = -0.01

    # Amplifiers / gates
    salience_gain: float = 0.5          # high-salience events weigh more
    quality_center: float = 0.7         # anchor around which success/failure is judged
    max_abs_delta_per_update: float = 0.08

    # Decay
    decay_rate_per_tick: float = 0.002  # small decay every outcome (toward neutrality)

    # Optional mapping from outcome keys to skill bumps (role-agnostic)
    # e.g., {"de_escalation": +0.01 when escalated&resolved}
    outcome_skill_map: Dict[str, float] = field(default_factory=dict)


@dataclass
class PromotionPolicy:
    """
    Criteria for proposing specialization changes.
    """
    window: int = 50                    # rolling window of outcomes
    min_tasks: int = 20                 # minimum observations before decisions
    min_quality_avg: float = 0.78       # promotion threshold
    demote_quality_avg: float = 0.55    # demotion threshold
    min_capability: float = 0.6         # require base capability
    cooldown_s: float = 3600.0          # 1 hour cooldown between changes

    # Optional role-to-role mapping preferences (e.g., pathing)
    preferred_promotions: Dict[Specialization, List[Specialization]] = field(default_factory=dict)
    preferred_demotions: Dict[Specialization, List[Specialization]] = field(default_factory=dict)


@dataclass
class Outcome:
    """
    A normalized view of a completed task/event used for learning.
    """
    success: bool
    quality: float               # 0..1
    escalated: bool
    salience: float              # 0..1
    duration_s: float = 0.0
    cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _History:
    qualities: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    successes: Deque[int] = field(default_factory=lambda: deque(maxlen=100))
    escalations: Deque[int] = field(default_factory=lambda: deque(maxlen=100))
    last_role_change_ts: float = 0.0


class SkillLearner:
    """
    Maintains per-agent rolling history and applies outcome-based learning
    to the SkillVector. Optionally suggests specialization changes.

    Usage:
        learner = SkillLearner(registry, LearningConfig(), PromotionPolicy())
        deltas_changed, new_spec, diag = learner.learn(agent_id, spec, role_profile, skills, outcome, capability)
        if deltas_changed: skills.persist_debounced(agent_id)
        if new_spec: agent._switch_specialization(new_spec)
    """
    def __init__(self, registry: RoleRegistry, lcfg: LearningConfig, ppol: PromotionPolicy):
        self._registry = registry
        self._lcfg = lcfg
        self._ppol = ppol
        self._histories: Dict[str, _History] = {}

    # ---- Public API ---------------------------------------------------------------

    def learn(
        self,
        agent_id: str,
        current_spec: Specialization,
        role_prof: RoleProfile,
        skills: SkillVector,
        outcome: Outcome,
        capability: float,
    ) -> Tuple[bool, Optional[Specialization], Dict[str, Any]]:
        """
        Apply skill updates and maybe propose a specialization change.

        Returns:
            (deltas_changed, new_specialization or None, diagnostics)
        """
        hist = self._histories.setdefault(agent_id, _History())

        # 1) Update rolling history
        hist.qualities.append(float(outcome.quality))
        hist.successes.append(1 if outcome.success else 0)
        hist.escalations.append(1 if outcome.escalated else 0)

        # 2) Apply decay
        if self._lcfg.decay_rate_per_tick > 0:
            skills.decay(self._lcfg.decay_rate_per_tick)

        # 3) Compute learning signal
        signal = self._compute_signal(outcome)
        # Bound per-update absolute magnitude
        if abs(signal) > self._lcfg.max_abs_delta_per_update:
            signal = self._lcfg.max_abs_delta_per_update if signal > 0 else -self._lcfg.max_abs_delta_per_update

        # 4) Map signal to relevant skills (default: role routing tags → mapped skills)
        # You can make this smarter (per-role mapping). For now, push generic skills often used by cognition:
        target_skills = self._default_target_skills_for_role(role_prof)

        deltas_changed = False
        for sk in target_skills:
            before = skills.deltas.get(sk, 0.0)
            after = skills.bump(sk, signal, clamp_delta=True)
            deltas_changed = deltas_changed or (abs(after - before) > 1e-9)

        # 5) Outcome-specific nudges (optional map)
        for sk, dv in (self._lcfg.outcome_skill_map or {}).items():
            if dv != 0.0:
                before = skills.deltas.get(sk, 0.0)
                after = skills.bump(sk, dv, clamp_delta=True)
                deltas_changed = deltas_changed or (abs(after - before) > 1e-9)

        # 6) Promotion/demotion suggestion
        new_spec, promo_diag = self._maybe_suggest_role_change(
            agent_id=agent_id,
            current_spec=current_spec,
            hist=hist,
            capability=capability,
        )

        # 7) Diagnostics
        diag = {
            "signal": signal,
            "rolling_quality_avg": mean(hist.qualities) if len(hist.qualities) > 0 else None,
            "rolling_success_rate": (sum(hist.successes) / len(hist.successes)) if len(hist.successes) > 0 else None,
            "rolling_escalation_rate": (sum(hist.escalations) / len(hist.escalations)) if len(hist.escalations) > 0 else None,
            "proposed_specialization": new_spec.value if new_spec else None,
            **promo_diag,
        }

        return deltas_changed, new_spec, diag

    # ---- Internals ----------------------------------------------------------------

    def _compute_signal(self, outcome: Outcome) -> float:
        """
        Convert an outcome into a scalar delta (positive improves, negative reduces).
        """
        # Success/failure baseline around quality_center
        if outcome.quality >= self._lcfg.quality_center:
            base = self._lcfg.lr_success
        else:
            base = self._lcfg.lr_failure

        # Escalation penalty
        if outcome.escalated:
            base += self._lcfg.lr_escalation_penalty

        # Salience amplifier
        base *= (1.0 + self._lcfg.salience_gain * float(outcome.salience))

        # Normalize by distance from center so near-threshold updates are smaller
        distance = abs(outcome.quality - self._lcfg.quality_center)
        base *= (0.5 + distance)  # 0.5..1.5

        return base

    def _default_target_skills_for_role(self, role_prof: RoleProfile) -> List[str]:
        """
        Heuristic mapping of generic learning signals to a small subset of skills per role.
        You can override this with a registry-driven mapping if needed.
        """
        defaults = role_prof.default_skills
        if not defaults:
            return ["analysis", "planning", "communication"]  # general fallbacks
        # Choose top-3 default skills by baseline value
        return [k for k, _ in sorted(defaults.items(), key=lambda kv: kv[1], reverse=True)[:3]]

    def _maybe_suggest_role_change(
        self,
        agent_id: str,
        current_spec: Specialization,
        hist: _History,
        capability: float,
    ) -> Tuple[Optional[Specialization], Dict[str, Any]]:
        """
        Evaluate promotion/demotion criteria and propose a new specialization if eligible.
        Applies cooldown to avoid thrashing. Returns (new_spec_or_None, diagnostics).
        """
        now = time.time()
        window = self._ppol.window

        if len(hist.qualities) < max(self._ppol.min_tasks, 1):
            return None, {"role_change_reason": "insufficient_history"}

        q_list = list(hist.qualities)[-window:]
        q_avg = mean(q_list) if q_list else 0.0

        # Cooldown check
        if (now - hist.last_role_change_ts) < self._ppol.cooldown_s:
            return None, {"role_change_reason": "cooldown_active", "q_avg": q_avg}

        # Capability guard
        if capability < self._ppol.min_capability:
            return None, {"role_change_reason": "capability_below_threshold", "q_avg": q_avg}

        # Promotion path preference
        promo_path = self._ppol.preferred_promotions.get(current_spec, [])
        demo_path = self._ppol.preferred_demotions.get(current_spec, [])

        # Promotion criteria
        if q_avg >= self._ppol.min_quality_avg and promo_path:
            hist.last_role_change_ts = now
            return promo_path[0], {"role_change_reason": "promotion", "q_avg": q_avg}

        # Demotion criteria
        if q_avg <= self._ppol.demote_quality_avg and demo_path:
            hist.last_role_change_ts = now
            return demo_path[0], {"role_change_reason": "demotion", "q_avg": q_avg}

        return None, {"role_change_reason": "no_change", "q_avg": q_avg}
