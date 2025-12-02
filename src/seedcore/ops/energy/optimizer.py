"""
Energy-Aware Agent Selection Optimizer (V2).

This module implements the logic to select the optimal agent for a task
by minimizing the predicted system energy ΔE.

It operates on 'AgentSnapshot' data (from StateService), NOT live Ray actors.
This ensures O(1) decision making without network fan-out.
"""

from typing import Dict, List, Any, Union
import logging

from seedcore.models.task_payload import TaskPayload

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 1. CORE SCORING LOGIC (Stateless)
# ----------------------------------------------------------------------

def calculate_agent_suitability_score(
    agent_data: Dict[str, Any], 
    task_dict: Dict[str, Any]
) -> float:
    """
    Calculate an energy-proxy score for an agent based on its snapshot state.
    Lower Score = Better Fit (Lower System Energy).
    
    Args:
        agent_data: Dict representation of AgentSnapshot (h, p, c, mem_util).
        task_dict: TaskPayload dictionary.
    """
    # 1. Extract Agent Metrics
    capability = float(agent_data.get("c", 0.0))
    mem_util = float(agent_data.get("mem_util", 0.0))
    
    # 2. Extract Task Requirements
    params = task_dict.get("params", {})
    routing = params.get("routing", {})
    required_spec = routing.get("required_specialization")
    required_skills = routing.get("skills", {})
    
    # 3. Term 1: Capability Match (Primary)
    # Higher capability reduces energy cost of execution.
    # Score penalty: (1.0 - capability)
    cap_penalty = (1.0 - capability) * 1.0

    # 4. Term 2: Specialization Match (Hard Constraint Proxy)
    # If the agent is the wrong type, massive penalty.
    agent_spec = str(agent_data.get("specialization", "unknown")).lower()
    spec_penalty = 0.0
    if required_spec and agent_spec != required_spec.lower():
        spec_penalty = 5.0 # Huge penalty for mismatch

    # 5. Term 3: Skill Match (Soft Constraint)
    # We want the agent whose skills overlap most with requirements.
    skill_penalty = 0.0
    if required_skills:
        agent_skills = agent_data.get("learned_skills", {})
        match_score = 0.0
        total_req = 0.0
        for skill, level in required_skills.items():
            agent_level = agent_skills.get(skill, 0.0)
            match_score += min(agent_level, level)
            total_req += level
        
        if total_req > 0:
            # 0.0 = Perfect match, 1.0 = No skills match
            skill_penalty = 1.0 - (match_score / total_req)

    # 6. Term 4: Load / Memory Pressure
    # High memory util means higher risk of OOM or latency (Regularization term).
    load_penalty = mem_util * 0.3

    # 7. Total Score (Proxy for ΔE)
    total_score = cap_penalty + spec_penalty + skill_penalty + load_penalty
    return total_score


def rank_agents_by_suitability(
    suitability_scores: Dict[str, float]
) -> List[str]:
    """
    Sort agent IDs by score (ascending = best first).
    """
    # Sort dict items by value
    sorted_items = sorted(suitability_scores.items(), key=lambda item: item[1])
    return [agent_id for agent_id, score in sorted_items]


# ----------------------------------------------------------------------
# 2. HELPER UTILITIES
# ----------------------------------------------------------------------

def estimate_task_complexity(task_payload: Union[Dict[str, Any], TaskPayload]) -> float:
    """
    Estimates task complexity (0.0 - 1.0) based on type and description length.
    Used to scale the regularization penalty.
    """
    if hasattr(task_payload, "model_dump"):
        t = task_payload.model_dump()
    else:
        t = task_payload

    base = 0.5
    
    # Type modifiers
    tt = str(t.get("type", "")).lower()
    if "plan" in tt or "reason" in tt or "graph" in tt:
        base += 0.3
    elif "chat" in tt:
        base -= 0.1
        
    # Text length modifier
    desc = str(t.get("description", ""))
    if len(desc) > 500:
        base += 0.2
        
    return max(0.1, min(1.0, base))


def get_ideal_role_for_task(
    agent_data: Dict[str, Any], 
    task_dict: Dict[str, Any]
) -> str:
    """
    Predicts the ideal role (E/S/O) an agent should adopt for this task.
    This helps the 'Flywheel' adjust agent role probabilities.
    """
    tt = str(task_dict.get("type", "")).lower()
    
    # Simple Heuristic Map
    if "exec" in tt or "action" in tt or "robot" in tt:
        return "E" # Execution
    elif "plan" in tt or "reason" in tt or "chat" in tt:
        return "S" # Synthesis/Social
    elif "sensor" in tt or "monitor" in tt or "graph" in tt:
        return "O" # Observation
        
    # Fallback: Stick to agent's current dominant role
    p = agent_data.get("p", {})
    if p:
        return max(p, key=p.get)
    return "S"