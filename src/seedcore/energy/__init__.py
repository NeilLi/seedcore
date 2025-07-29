"""
Energy Model Foundation Package

This package implements the energy-aware agent selection and optimization system
as defined by the Cognitive Organism Architecture (COA).

The energy model provides:
- Unified Energy Function calculation
- Energy-aware agent selection
- Task complexity estimation
- Role-based task assignment
"""

from .calculator import (
    calculate_pair_energy,
    calculate_entropy_energy,
    calculate_reg_energy,
    calculate_mem_energy,
    calculate_total_energy
)

from .optimizer import (
    calculate_agent_suitability_score,
    select_best_agent,
    rank_agents_by_suitability,
    get_ideal_role_for_task,
    estimate_task_complexity
)

__all__ = [
    # Calculator functions
    'calculate_pair_energy',
    'calculate_entropy_energy', 
    'calculate_reg_energy',
    'calculate_mem_energy',
    'calculate_total_energy',
    
    # Optimizer functions
    'calculate_agent_suitability_score',
    'select_best_agent',
    'rank_agents_by_suitability',
    'get_ideal_role_for_task',
    'estimate_task_complexity'
]
