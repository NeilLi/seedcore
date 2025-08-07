"""
Cognitive task monitoring and metrics for SeedCore.

This module provides comprehensive observability for cognitive reasoning tasks,
including token usage, latency, error rates, and performance metrics.
"""

import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from prometheus_client import Counter, Histogram, Gauge, Summary
import json

logger = logging.getLogger(__name__)


class CognitiveTaskStatus(Enum):
    """Status of cognitive tasks."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    INVALID_INPUT = "invalid_input"


@dataclass
class CognitiveMetrics:
    """Metrics for cognitive task execution."""
    task_type: str
    agent_id: str
    start_time: float
    end_time: Optional[float] = None
    status: CognitiveTaskStatus = CognitiveTaskStatus.SUCCESS
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    error_message: Optional[str] = None
    model_used: Optional[str] = None
    provider: Optional[str] = None
    confidence_score: Optional[float] = None
    energy_cost: float = 0.0


class CognitiveMetricsCollector:
    """
    Collects and manages metrics for cognitive tasks.
    
    This class provides comprehensive monitoring for:
    - Task execution metrics (latency, success rates)
    - Token usage and costs
    - Error tracking and analysis
    - Performance trends
    """
    
    def __init__(self):
        # Prometheus metrics
        self.task_counter = Counter(
            'cognitive_tasks_total',
            'Total number of cognitive tasks',
            ['task_type', 'status', 'model', 'provider']
        )
        
        self.task_duration = Histogram(
            'cognitive_task_duration_seconds',
            'Duration of cognitive tasks',
            ['task_type', 'model', 'provider'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
        )
        
        self.token_usage = Counter(
            'cognitive_tokens_total',
            'Total token usage',
            ['task_type', 'token_type', 'model', 'provider']
        )
        
        self.error_rate = Counter(
            'cognitive_errors_total',
            'Total number of cognitive task errors',
            ['task_type', 'error_type', 'model', 'provider']
        )
        
        self.active_tasks = Gauge(
            'cognitive_active_tasks',
            'Number of currently active cognitive tasks',
            ['task_type']
        )
        
        self.confidence_score = Histogram(
            'cognitive_confidence_score',
            'Confidence scores for cognitive tasks',
            ['task_type', 'model'],
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        self.energy_cost = Counter(
            'cognitive_energy_cost',
            'Total energy cost for cognitive tasks',
            ['task_type', 'model', 'provider']
        )
        
        # Internal storage for detailed metrics
        self._task_history: List[CognitiveMetrics] = []
        self._max_history_size = 1000
        
        logger.info("✅ Cognitive metrics collector initialized")
    
    def start_task(self, task_type: str, agent_id: str, model: str = "unknown", provider: str = "unknown") -> str:
        """
        Start tracking a cognitive task.
        
        Args:
            task_type: Type of cognitive task
            agent_id: ID of the agent performing the task
            model: LLM model being used
            provider: LLM provider being used
            
        Returns:
            Task ID for tracking
        """
        task_id = f"{task_type}_{agent_id}_{int(time.time() * 1000)}"
        
        metrics = CognitiveMetrics(
            task_type=task_type,
            agent_id=agent_id,
            start_time=time.time(),
            model_used=model,
            provider=provider
        )
        
        # Store metrics with task ID
        self._task_history.append(metrics)
        
        # Update Prometheus metrics
        self.active_tasks.labels(task_type=task_type).inc()
        
        logger.debug(f"Started tracking cognitive task: {task_id}")
        return task_id
    
    def complete_task(
        self,
        task_id: str,
        status: CognitiveTaskStatus,
        input_tokens: int = 0,
        output_tokens: int = 0,
        confidence_score: Optional[float] = None,
        error_message: Optional[str] = None,
        energy_cost: float = 0.0
    ) -> None:
        """
        Complete tracking of a cognitive task.
        
        Args:
            task_id: Task ID from start_task
            status: Final status of the task
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            confidence_score: Confidence score if applicable
            error_message: Error message if failed
            energy_cost: Energy cost of the task
        """
        # Find the task in history
        task = None
        for t in self._task_history:
            if f"{t.task_type}_{t.agent_id}_{int(t.start_time * 1000)}" == task_id:
                task = t
                break
        
        if not task:
            logger.warning(f"Task {task_id} not found in history")
            return
        
        # Update task metrics
        task.end_time = time.time()
        task.status = status
        task.input_tokens = input_tokens
        task.output_tokens = output_tokens
        task.total_tokens = input_tokens + output_tokens
        task.latency_ms = (task.end_time - task.start_time) * 1000
        task.confidence_score = confidence_score
        task.error_message = error_message
        task.energy_cost = energy_cost
        
        # Update Prometheus metrics
        self.task_counter.labels(
            task_type=task.task_type,
            status=status.value,
            model=task.model_used or "unknown",
            provider=task.provider or "unknown"
        ).inc()
        
        self.task_duration.labels(
            task_type=task.task_type,
            model=task.model_used or "unknown",
            provider=task.provider or "unknown"
        ).observe(task.latency_ms / 1000.0)
        
        self.token_usage.labels(
            task_type=task.task_type,
            token_type="input",
            model=task.model_used or "unknown",
            provider=task.provider or "unknown"
        ).inc(input_tokens)
        
        self.token_usage.labels(
            task_type=task.task_type,
            token_type="output",
            model=task.model_used or "unknown",
            provider=task.provider or "unknown"
        ).inc(output_tokens)
        
        if status != CognitiveTaskStatus.SUCCESS:
            self.error_rate.labels(
                task_type=task.task_type,
                error_type=status.value,
                model=task.model_used or "unknown",
                provider=task.provider or "unknown"
            ).inc()
        
        if confidence_score is not None:
            self.confidence_score.labels(
                task_type=task.task_type,
                model=task.model_used or "unknown"
            ).observe(confidence_score)
        
        self.energy_cost.labels(
            task_type=task.task_type,
            model=task.model_used or "unknown",
            provider=task.provider or "unknown"
        ).inc(energy_cost)
        
        # Decrement active tasks
        self.active_tasks.labels(task_type=task.task_type).dec()
        
        # Clean up old history
        if len(self._task_history) > self._max_history_size:
            self._task_history = self._task_history[-self._max_history_size:]
        
        logger.debug(f"Completed tracking cognitive task: {task_id} (status: {status.value})")
    
    def get_task_metrics(self, task_type: Optional[str] = None, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get metrics for tasks matching the criteria.
        
        Args:
            task_type: Filter by task type
            agent_id: Filter by agent ID
            
        Returns:
            List of task metrics
        """
        filtered_tasks = self._task_history
        
        if task_type:
            filtered_tasks = [t for t in filtered_tasks if t.task_type == task_type]
        
        if agent_id:
            filtered_tasks = [t for t in filtered_tasks if t.agent_id == agent_id]
        
        return [self._task_to_dict(t) for t in filtered_tasks]
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics for all cognitive tasks.
        
        Returns:
            Dictionary with summary statistics
        """
        if not self._task_history:
            return {
                "total_tasks": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "total_tokens": 0,
                "total_energy_cost": 0.0
            }
        
        completed_tasks = [t for t in self._task_history if t.end_time is not None]
        
        if not completed_tasks:
            return {
                "total_tasks": len(self._task_history),
                "active_tasks": len(self._task_history),
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "total_tokens": 0,
                "total_energy_cost": 0.0
            }
        
        successful_tasks = [t for t in completed_tasks if t.status == CognitiveTaskStatus.SUCCESS]
        
        return {
            "total_tasks": len(self._task_history),
            "completed_tasks": len(completed_tasks),
            "active_tasks": len(self._task_history) - len(completed_tasks),
            "success_rate": len(successful_tasks) / len(completed_tasks) if completed_tasks else 0.0,
            "avg_latency_ms": sum(t.latency_ms for t in completed_tasks) / len(completed_tasks),
            "total_tokens": sum(t.total_tokens for t in completed_tasks),
            "total_energy_cost": sum(t.energy_cost for t in completed_tasks),
            "tasks_by_type": self._get_tasks_by_type(),
            "tasks_by_status": self._get_tasks_by_status(),
            "recent_errors": self._get_recent_errors()
        }
    
    def _task_to_dict(self, task: CognitiveMetrics) -> Dict[str, Any]:
        """Convert task metrics to dictionary."""
        return {
            "task_type": task.task_type,
            "agent_id": task.agent_id,
            "start_time": task.start_time,
            "end_time": task.end_time,
            "status": task.status.value,
            "input_tokens": task.input_tokens,
            "output_tokens": task.output_tokens,
            "total_tokens": task.total_tokens,
            "latency_ms": task.latency_ms,
            "confidence_score": task.confidence_score,
            "error_message": task.error_message,
            "model_used": task.model_used,
            "provider": task.provider,
            "energy_cost": task.energy_cost
        }
    
    def _get_tasks_by_type(self) -> Dict[str, int]:
        """Get count of tasks by type."""
        counts = {}
        for task in self._task_history:
            counts[task.task_type] = counts.get(task.task_type, 0) + 1
        return counts
    
    def _get_tasks_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status."""
        counts = {}
        for task in self._task_history:
            if task.end_time is not None:  # Only completed tasks
                counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts
    
    def _get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent error details."""
        errors = []
        for task in reversed(self._task_history):
            if task.status != CognitiveTaskStatus.SUCCESS and task.error_message:
                errors.append({
                    "task_type": task.task_type,
                    "agent_id": task.agent_id,
                    "error_message": task.error_message,
                    "timestamp": task.start_time
                })
                if len(errors) >= limit:
                    break
        return errors


# Global metrics collector instance
_metrics_collector: Optional[CognitiveMetricsCollector] = None


def get_metrics_collector() -> CognitiveMetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = CognitiveMetricsCollector()
    return _metrics_collector


def track_cognitive_task(task_type: str, agent_id: str, model: str = "unknown", provider: str = "unknown") -> str:
    """
    Start tracking a cognitive task.
    
    Args:
        task_type: Type of cognitive task
        agent_id: ID of the agent
        model: LLM model being used
        provider: LLM provider being used
        
    Returns:
        Task ID for tracking
    """
    collector = get_metrics_collector()
    return collector.start_task(task_type, agent_id, model, provider)


def complete_cognitive_task(
    task_id: str,
    status: CognitiveTaskStatus,
    input_tokens: int = 0,
    output_tokens: int = 0,
    confidence_score: Optional[float] = None,
    error_message: Optional[str] = None,
    energy_cost: float = 0.0
) -> None:
    """
    Complete tracking of a cognitive task.
    
    Args:
        task_id: Task ID from track_cognitive_task
        status: Final status of the task
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        confidence_score: Confidence score if applicable
        error_message: Error message if failed
        energy_cost: Energy cost of the task
    """
    collector = get_metrics_collector()
    collector.complete_task(
        task_id, status, input_tokens, output_tokens,
        confidence_score, error_message, energy_cost
    )


def get_cognitive_metrics(task_type: Optional[str] = None, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get cognitive task metrics.
    
    Args:
        task_type: Filter by task type
        agent_id: Filter by agent ID
        
    Returns:
        List of task metrics
    """
    collector = get_metrics_collector()
    return collector.get_task_metrics(task_type, agent_id)


def get_cognitive_summary_stats() -> Dict[str, Any]:
    """
    Get summary statistics for cognitive tasks.
    
    Returns:
        Dictionary with summary statistics
    """
    collector = get_metrics_collector()
    return collector.get_summary_stats() 