"""
Predicate-based router for Coordinator service.

This module provides the main routing logic that evaluates predicates and
makes routing decisions based on the YAML configuration.
"""

import time
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

from .schema import PredicatesConfig, EvaluationContext, TaskContext, DecisionContext
from .evaluator import PredicateEvaluator
from .metrics import get_metrics
from .gpu_guard import GpuGuardSystem
from .signals import create_signal_context

logger = logging.getLogger(__name__)

@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    action: str
    organ_id: Optional[str] = None
    reason: str = ""
    rule_matched: Optional[str] = None
    confidence: float = 1.0

@dataclass
class MutationDecision:
    """Result of a mutation decision."""
    action: str
    job_id: Optional[str] = None
    reason: str = ""
    rule_matched: Optional[str] = None
    confidence: float = 1.0

class PredicateRouter:
    """Main predicate-based router."""
    
    def __init__(self, config: PredicatesConfig):
        self.config = config
        self.evaluator = PredicateEvaluator()
        self.metrics = get_metrics()
        
        # GPU guard is optional based on feature flag
        gpu_guard_enabled = getattr(config, 'gpu_guard_enabled', False)
        if gpu_guard_enabled:
            self.gpu_guard = GpuGuardSystem(config.gpu_guard)
        else:
            self.gpu_guard = None
            logger.info("GPU guard disabled by feature flag")
        
        # Signal context cache
        self._signal_cache: Dict[str, Any] = {}
        self._cache_ttl = 30.0  # 30 seconds
        self._last_cache_update = 0.0
        
        logger.info(f"✅ PredicateRouter initialized with {len(config.routing)} routing rules and {len(config.mutations)} mutation rules")
    
    def update_signals(self, **signals):
        """Update signal values."""
        self._signal_cache.update(signals)
        self._last_cache_update = time.time()
        
        # Update metrics
        if "p_fast" in signals and "s_drift" in signals:
            escalation_ratio = self._calculate_escalation_ratio()
            self.metrics.update_ocps_signals(
                p_fast=signals["p_fast"],
                s_drift=signals["s_drift"],
                escalation_ratio=escalation_ratio
            )
        
        if "ΔE_est" in signals or "ΔE_realized" in signals or "energy_cost" in signals:
            self.metrics.update_energy_signals(
                deltaE_est=signals.get("ΔE_est"),
                deltaE_realized=signals.get("ΔE_realized"),
                energy_cost=signals.get("energy_cost")
            )
        
        if "memory_utilization" in signals or "cpu_utilization" in signals:
            self.metrics.update_resource_signals(
                memory_utilization=signals.get("memory_utilization"),
                cpu_utilization=signals.get("cpu_utilization")
            )
    
    def _calculate_escalation_ratio(self) -> float:
        """Calculate current escalation ratio."""
        # This would typically come from metrics, but for now return a default
        return 0.2  # 20% escalation rate
    
    def _get_evaluation_context(self, task: Dict[str, Any], decision: Optional[Dict[str, Any]] = None) -> EvaluationContext:
        """Create evaluation context from task and decision data."""
        # Extract task context
        task_context = TaskContext(
            type=task.get("type", "unknown"),
            domain=task.get("domain"),
            priority=task.get("priority", 5),
            complexity=task.get("complexity", 0.5),
            features=task.get("features", {})
        )
        
        # Extract decision context
        decision_context = DecisionContext(
            action=decision.get("action", "hold") if decision else "hold",
            confidence=decision.get("confidence", 0.5) if decision else 0.5,
            reasoning=decision.get("reasoning") if decision else None
        )
        
        # Get GPU guard status (if enabled)
        gpu_status = self.gpu_guard.get_status() if self.gpu_guard else {"guard_ok": True}
        
        # Create signal context
        signal_context = create_signal_context(**self._signal_cache)
        
        return EvaluationContext(
            task=task_context,
            decision=decision_context,
            signals=signal_context,
            gpu=gpu_status
        )
    
    def route_task(self, task: Dict[str, Any]) -> RoutingDecision:
        """
        Route a task based on predicate rules.
        
        Args:
            task: Task data dictionary
            
        Returns:
            RoutingDecision with action and reasoning
        """
        start_time = time.time()
        
        # Check if routing is enabled
        if not getattr(self.config, 'routing_enabled', True):
            return RoutingDecision(
                action="fast_path",
                organ_id="utility_organ_1",
                reason="Routing disabled by feature flag",
                confidence=0.5
            )
        
        try:
            # Create evaluation context
            context = self._get_evaluation_context(task)
            context_dict = context.to_dict()
            
            # Evaluate routing rules in priority order
            sorted_rules = sorted(self.config.routing, key=lambda r: r.priority, reverse=True)
            
            for rule in sorted_rules:
                try:
                    rule_start = time.time()
                    result = self.evaluator.eval_predicate(rule.when, context_dict)
                    rule_duration = time.time() - rule_start
                    
                    # Record evaluation metrics
                    self.metrics.record_predicate_evaluation("routing", result, rule_duration)
                    
                    if result:
                        # Parse action
                        action_parts = rule.do.split(":", 1)
                        action = action_parts[0]
                        organ_id = action_parts[1] if len(action_parts) > 1 else None
                        
                        decision = RoutingDecision(
                            action=action,
                            organ_id=organ_id,
                            reason=f"Matched rule: {rule.description or rule.do}",
                            rule_matched=rule.description or rule.do,
                            confidence=0.9  # High confidence for matched rules
                        )
                        
                        # Record routing decision
                        self.metrics.record_routing_decision(action, rule.description or "rule_match")
                        
                        logger.info(f"🎯 Routing decision: {action} (organ: {organ_id}) - {rule.description or rule.do}")
                        return decision
                        
                except Exception as e:
                    logger.warning(f"Error evaluating routing rule '{rule.description or rule.do}': {e}")
                    continue
            
            # No rules matched - use fallback
            fallback_action = self.config.fallback.get("routing", "escalate") if self.config.fallback else "escalate"
            
            decision = RoutingDecision(
                action=fallback_action,
                reason="No routing rules matched, using fallback",
                confidence=0.5
            )
            
            self.metrics.record_routing_decision(fallback_action, "fallback")
            
            logger.info(f"🎯 Fallback routing decision: {fallback_action}")
            return decision
            
        except Exception as e:
            logger.error(f"Error in task routing: {e}")
            
            # Emergency fallback
            decision = RoutingDecision(
                action="escalate",
                reason=f"Routing error: {str(e)}",
                confidence=0.1
            )
            
            self.metrics.record_routing_decision("escalate", "error")
            return decision
        
        finally:
            # Record total routing time
            total_duration = time.time() - start_time
            self.metrics.record_latency("router", total_duration * 1000)
    
    def evaluate_mutation(self, task: Dict[str, Any], decision: Dict[str, Any]) -> MutationDecision:
        """
        Evaluate whether to submit a mutation (tuning/retraining) job.
        
        Args:
            task: Task data dictionary
            decision: Decision data dictionary
            
        Returns:
            MutationDecision with action and reasoning
        """
        start_time = time.time()
        
        # Check if mutations are enabled
        if not getattr(self.config, 'mutations_enabled', True):
            return MutationDecision(
                action="hold",
                reason="Mutations disabled by feature flag",
                confidence=0.5
            )
        
        try:
            # Create evaluation context
            context = self._get_evaluation_context(task, decision)
            context_dict = context.to_dict()
            
            # Evaluate mutation rules in priority order
            sorted_rules = sorted(self.config.mutations, key=lambda r: r.priority, reverse=True)
            
            for rule in sorted_rules:
                try:
                    rule_start = time.time()
                    result = self.evaluator.eval_predicate(rule.when, context_dict)
                    rule_duration = time.time() - rule_start
                    
                    # Record evaluation metrics
                    self.metrics.record_predicate_evaluation("mutation", result, rule_duration)
                    
                    if result:
                        # Parse action
                        action_parts = rule.do.split(":", 1)
                        action = action_parts[0]
                        job_id = action_parts[1] if len(action_parts) > 1 else None
                        
                        # If submitting a job, check GPU guard
                        if action in ["submit_tuning", "submit_retrain"]:
                            can_submit, reason = self.gpu_guard.can_submit_job(action.replace("submit_", ""))
                            if not can_submit:
                                decision = MutationDecision(
                                    action="hold",
                                    reason=f"GPU guard blocked: {reason}",
                                    rule_matched=rule.description or rule.do,
                                    confidence=0.8
                                )
                                self.metrics.record_mutation_decision("hold", "gpu_guard_blocked")
                                return decision
                            
                            # Submit the job
                            if self.gpu_guard.submit_job(job_id or f"job_{int(time.time())}", action.replace("submit_", "")):
                                decision = MutationDecision(
                                    action=action,
                                    job_id=job_id,
                                    reason=f"Matched rule: {rule.description or rule.do}",
                                    rule_matched=rule.description or rule.do,
                                    confidence=0.9
                                )
                            else:
                                decision = MutationDecision(
                                    action="hold",
                                    reason="Failed to submit job to GPU guard",
                                    rule_matched=rule.description or rule.do,
                                    confidence=0.7
                                )
                        else:
                            decision = MutationDecision(
                                action=action,
                                reason=f"Matched rule: {rule.description or rule.do}",
                                rule_matched=rule.description or rule.do,
                                confidence=0.9
                            )
                        
                        # Record mutation decision
                        self.metrics.record_mutation_decision(action, rule.description or "rule_match")
                        
                        logger.info(f"🧬 Mutation decision: {action} (job: {job_id}) - {rule.description or rule.do}")
                        return decision
                        
                except Exception as e:
                    logger.warning(f"Error evaluating mutation rule '{rule.description or rule.do}': {e}")
                    continue
            
            # No rules matched - use fallback
            fallback_action = self.config.fallback.get("mutation", "hold") if self.config.fallback else "hold"
            
            decision = MutationDecision(
                action=fallback_action,
                reason="No mutation rules matched, using fallback",
                confidence=0.5
            )
            
            self.metrics.record_mutation_decision(fallback_action, "fallback")
            
            logger.info(f"🧬 Fallback mutation decision: {fallback_action}")
            return decision
            
        except Exception as e:
            logger.error(f"Error in mutation evaluation: {e}")
            
            # Emergency fallback
            decision = MutationDecision(
                action="hold",
                reason=f"Mutation evaluation error: {str(e)}",
                confidence=0.1
            )
            
            self.metrics.record_mutation_decision("hold", "error")
            return decision
        
        finally:
            # Record total evaluation time
            total_duration = time.time() - start_time
            self.metrics.record_latency("router", total_duration * 1000)
    
    def get_gpu_guard_status(self) -> Dict[str, Any]:
        """Get current GPU guard status."""
        if self.gpu_guard:
            return self.gpu_guard.get_status()
        else:
            return {"guard_ok": True, "enabled": False, "reason": "GPU guard disabled by feature flag"}
    
    def update_gpu_job_status(self, job_id: str, status: str, success: bool = True):
        """Update GPU job status."""
        if self.gpu_guard:
            if status == "started":
                self.gpu_guard.start_job(job_id)
            elif status == "completed":
                self.gpu_guard.complete_job(job_id, success)
            elif status == "failed":
                self.gpu_guard.fail_job(job_id)
    
    async def start_background_tasks(self):
        """Start background maintenance tasks."""
        if self.gpu_guard:
            await self.gpu_guard.start_background_tasks()
        logger.info("🚀 Started predicate router background tasks")
