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
Hourly Flywheel Control Loop - Global weight adaptation.
Implements the hourly flywheel described in the energy validation blueprint §21.1.
"""

import asyncio
import logging
import time
import numpy as np
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from ..ops.energy.api import _ledger
# SOLUTION: Remove module-level import to avoid accessing organism_manager before initialization
# from ..organs.organism_manager import organism_manager

logger = logging.getLogger(__name__)

@dataclass
class FlywheelMetrics:
    """Metrics tracked by the flywheel for weight adaptation."""
    delta_spec: float = 0.0  # Specialization improvement
    delta_acc: float = 0.0   # Accuracy improvement  
    delta_smart: float = 0.0 # Smartness improvement
    delta_reason: float = 0.0 # Reasoning improvement

class HourlyFlywheel:
    """
    Hourly global weight adaptation using windowed metrics.
    Implements the adaptive formula from §21.1 of the energy validation blueprint.
    """
    
    def __init__(self, organism_manager, energy_ledger):
        self.organism = organism_manager
        self.ledger = energy_ledger
        self.weight_history = []
        self.metrics_history = []
        self.is_running = False
        self.cycle_interval = 3600  # 1 hour in seconds
        
        # Performance tracking windows
        self.performance_window = 3600  # 1 hour of data points
        self.min_data_points = 10
        
        # Weight adaptation parameters
        self.adaptation_rate = 0.05  # 5% change per cycle
        self.weight_bounds = {
            "alpha": (0.1, 2.0),      # Entropy weight bounds
            "lambda_reg": (0.001, 0.1), # Regularization weight bounds
            "beta_mem": (0.05, 0.5)   # Memory weight bounds
        }
    
    async def start(self):
        """Start the hourly flywheel loop."""
        if self.is_running:
            logger.warning("Flywheel is already running")
            return
        
        self.is_running = True
        logger.info("Starting hourly flywheel control loop")
        
        try:
            while self.is_running:
                await self.run_flywheel_cycle()
                await asyncio.sleep(self.cycle_interval)
        except Exception as e:
            logger.error(f"Error in flywheel loop: {e}")
            self.is_running = False
            raise
    
    async def stop(self):
        """Stop the hourly flywheel loop."""
        self.is_running = False
        logger.info("Stopping hourly flywheel control loop")
    
    async def run_flywheel_cycle(self):
        """Run a single flywheel cycle with weight adaptation."""
        logger.info("Running hourly flywheel cycle...")
        
        try:
            # Calculate windowed performance metrics
            recent_energy = self.ledger.get_recent_energy(self.performance_window)
            
            if len(recent_energy.get("total", [])) < self.min_data_points:
                logger.warning(f"Insufficient data for flywheel cycle. Need {self.min_data_points}, have {len(recent_energy.get('total', []))}")
                return
            
            # Calculate adaptive formula from §21.1
            metrics = self.calculate_performance_deltas(recent_energy)
            
            # Update global weights based on performance
            old_weights = self.get_current_weights()
            self.update_global_weights(metrics)
            new_weights = self.get_current_weights()
            
            # Log results
            cycle_result = {
                "timestamp": time.time(),
                "metrics": metrics,
                "old_weights": old_weights,
                "new_weights": new_weights,
                "weight_changes": {
                    key: new_weights[key] - old_weights[key] 
                    for key in old_weights.keys()
                }
            }
            
            self.weight_history.append(cycle_result)
            self.metrics_history.append(metrics)
            
            # Log summary
            logger.info(f"Flywheel cycle complete:")
            logger.info(f"  ΔSpec: {metrics.delta_spec:.4f}, ΔAcc: {metrics.delta_acc:.4f}")
            logger.info(f"  ΔSmart: {metrics.delta_smart:.4f}, ΔReason: {metrics.delta_reason:.4f}")
            logger.info(f"  Weight changes: {cycle_result['weight_changes']}")
            
        except Exception as e:
            logger.error(f"Error in flywheel cycle: {e}")
            raise
    
    def calculate_performance_deltas(self, recent_energy: Dict[str, List[float]]) -> FlywheelMetrics:
        """
        Calculate performance deltas using the adaptive formula from §21.1.
        
        Args:
            recent_energy: Recent energy values for all terms
            
        Returns:
            FlywheelMetrics with calculated deltas
        """
        metrics = FlywheelMetrics()
        
        try:
            # Calculate deltas based on energy trends
            total_energy = recent_energy.get("total", [])
            pair_energy = recent_energy.get("pair", [])
            entropy_energy = recent_energy.get("entropy", [])
            reg_energy = recent_energy.get("reg", [])
            mem_energy = recent_energy.get("mem", [])
            
            if len(total_energy) < 2:
                return metrics
            
            # ΔSpec: Specialization improvement (entropy reduction)
            if len(entropy_energy) >= 2:
                metrics.delta_spec = entropy_energy[-1] - entropy_energy[0]  # Negative is good
            
            # ΔAcc: Accuracy improvement (regularization reduction)
            if len(reg_energy) >= 2:
                metrics.delta_acc = reg_energy[0] - reg_energy[-1]  # Positive is good
            
            # ΔSmart: Smartness improvement (memory efficiency)
            if len(mem_energy) >= 2:
                metrics.delta_smart = mem_energy[0] - mem_energy[-1]  # Positive is good
            
            # ΔReason: Reasoning improvement (pair energy reduction)
            if len(pair_energy) >= 2:
                metrics.delta_reason = pair_energy[0] - pair_energy[-1]  # Positive is good (pair should be negative)
            
        except Exception as e:
            logger.error(f"Error calculating performance deltas: {e}")
        
        return metrics
    
    def update_global_weights(self, metrics: FlywheelMetrics):
        """
        Update global weights based on performance deltas.
        
        Args:
            metrics: Performance metrics from calculate_performance_deltas
        """
        try:
            # Adaptive weight updates based on §21.1 formula
            
            # Alpha (entropy weight): increase if specialization improving
            if metrics.delta_spec < 0:  # Specialization improving (entropy decreasing)
                self.ledger.alpha *= (1 + self.adaptation_rate)
                logger.debug(f"Increased alpha to {self.ledger.alpha:.4f} (specialization improving)")
            else:
                self.ledger.alpha *= (1 - self.adaptation_rate)
                logger.debug(f"Decreased alpha to {self.ledger.alpha:.4f} (specialization declining)")
            
            # Lambda_reg (regularization weight): decrease if accuracy improving
            if metrics.delta_acc > 0:  # Accuracy improving (reg decreasing)
                self.ledger.lambda_reg *= (1 - self.adaptation_rate)
                logger.debug(f"Decreased lambda_reg to {self.ledger.lambda_reg:.4f} (accuracy improving)")
            else:
                self.ledger.lambda_reg *= (1 + self.adaptation_rate)
                logger.debug(f"Increased lambda_reg to {self.ledger.lambda_reg:.4f} (accuracy declining)")
            
            # Beta_mem (memory weight): increase if smartness improving
            if metrics.delta_smart > 0:  # Smartness improving (memory efficiency increasing)
                self.ledger.beta_mem *= (1 + self.adaptation_rate)
                logger.debug(f"Increased beta_mem to {self.ledger.beta_mem:.4f} (smartness improving)")
            else:
                self.ledger.beta_mem *= (1 - self.adaptation_rate)
                logger.debug(f"Decreased beta_mem to {self.ledger.beta_mem:.4f} (smartness declining)")
            
            # Clamp weights to reasonable ranges
            self.clamp_weights()
            
        except Exception as e:
            logger.error(f"Error updating global weights: {e}")
    
    def clamp_weights(self):
        """Clamp weights to their defined bounds."""
        try:
            # Clamp alpha
            min_alpha, max_alpha = self.weight_bounds["alpha"]
            self.ledger.alpha = np.clip(self.ledger.alpha, min_alpha, max_alpha)
            
            # Clamp lambda_reg
            min_lambda, max_lambda = self.weight_bounds["lambda_reg"]
            self.ledger.lambda_reg = np.clip(self.ledger.lambda_reg, min_lambda, max_lambda)
            
            # Clamp beta_mem
            min_beta, max_beta = self.weight_bounds["beta_mem"]
            self.ledger.beta_mem = np.clip(self.ledger.beta_mem, min_beta, max_beta)
            
        except Exception as e:
            logger.error(f"Error clamping weights: {e}")
    
    def get_current_weights(self) -> Dict[str, float]:
        """Get current weight values."""
        return {
            "alpha": self.ledger.alpha,
            "lambda_reg": self.ledger.lambda_reg,
            "beta_mem": self.ledger.beta_mem
        }
    
    def get_weight_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent weight history."""
        if limit > 0:
            return self.weight_history[-limit:]
        return self.weight_history
    
    def get_metrics_history(self, limit: int = 100) -> List[FlywheelMetrics]:
        """Get recent metrics history."""
        if limit > 0:
            return self.metrics_history[-limit:]
        return self.metrics_history
    
    def get_flywheel_stats(self) -> Dict[str, Any]:
        """Get flywheel statistics and performance metrics."""
        try:
            if not self.weight_history:
                return {"error": "No flywheel history available"}
            
            recent_cycles = self.weight_history[-10:]  # Last 10 cycles
            
            # Calculate average weight changes
            avg_changes = {}
            for weight_name in ["alpha", "lambda_reg", "beta_mem"]:
                changes = [cycle["weight_changes"].get(weight_name, 0) for cycle in recent_cycles]
                avg_changes[weight_name] = np.mean(changes) if changes else 0.0
            
            # Calculate performance trends
            recent_metrics = self.metrics_history[-10:] if self.metrics_history else []
            avg_metrics = FlywheelMetrics()
            if recent_metrics:
                avg_metrics.delta_spec = np.mean([m.delta_spec for m in recent_metrics])
                avg_metrics.delta_acc = np.mean([m.delta_acc for m in recent_metrics])
                avg_metrics.delta_smart = np.mean([m.delta_smart for m in recent_metrics])
                avg_metrics.delta_reason = np.mean([m.delta_reason for m in recent_metrics])
            
            return {
                "is_running": self.is_running,
                "total_cycles": len(self.weight_history),
                "current_weights": self.get_current_weights(),
                "average_weight_changes": avg_changes,
                "average_metrics": {
                    "delta_spec": avg_metrics.delta_spec,
                    "delta_acc": avg_metrics.delta_acc,
                    "delta_smart": avg_metrics.delta_smart,
                    "delta_reason": avg_metrics.delta_reason
                },
                "last_cycle": self.weight_history[-1] if self.weight_history else None
            }
            
        except Exception as e:
            logger.error(f"Error getting flywheel stats: {e}")
            return {"error": str(e)}

# Global flywheel instance - lazy initialization to avoid accessing organism_manager before it's ready
_flywheel_instance = None

def get_flywheel_instance():
    """Get the global flywheel instance with lazy initialization."""
    global _flywheel_instance
    if _flywheel_instance is None:
        # Lazy import to avoid circular dependencies
        from ..organs.organism_manager import organism_manager
        if organism_manager is None:
            raise RuntimeError("OrganismManager not yet initialized. Please wait for startup to complete.")
        _flywheel_instance = HourlyFlywheel(organism_manager, _ledger)
    return _flywheel_instance

async def start_flywheel():
    """Start the global flywheel instance."""
    await get_flywheel_instance().start()

async def stop_flywheel():
    """Stop the global flywheel instance."""
    if _flywheel_instance is not None:
        await _flywheel_instance.stop() 