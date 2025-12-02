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
    compute_energy_unified,
    SystemParameters,
    EnergyResult,
    EnergyWeights,
)
from .ledger import EnergyTerms, EnergyLedger

from .optimizer import (
    calculate_agent_suitability_score,
    rank_agents_by_suitability,
    get_ideal_role_for_task,
    estimate_task_complexity
)

__all__ = [
    # Calculator functions
    'compute_energy_unified',
    'SystemParameters',
    'EnergyResult',
    'EnergyWeights',

    # Ledger functions
    'EnergyTerms',
    'EnergyLedger',
    
    # Optimizer functions
    'calculate_agent_suitability_score',
    'rank_agents_by_suitability',
    'get_ideal_role_for_task',
    'estimate_task_complexity'
]
