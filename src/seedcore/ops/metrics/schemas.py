"""Structured schemas for metrics data models.

This module provides type-safe dataclasses for metrics with validation
to ensure data integrity when working with dynamic metrics keys.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Literal, Set
import logging

logger = logging.getLogger(__name__)

# Type literals for valid metric keys
RoutingDecision = Literal["fast", "planner", "hgnn"]
DispatchStatus = Literal["ok", "err"]
UpsertStatus = Literal["ok", "err", "truncated"]
EnqueueStatus = Literal["ok", "dup", "err"]
DispatchRoute = Literal["planner", "hgnn"]


# Valid metric keys for validation
VALID_ROUTING_KEYS: Set[str] = {
    "fast_routed_total",
    "planner_routed_total",
    "hgnn_routed_total",
    "hgnn_plan_generated_total",
    "hgnn_plan_empty_total",
}

VALID_EXECUTION_KEYS: Set[str] = {
    "total_tasks",
    "successful_tasks",
    "failed_tasks",
    "fast_path_tasks",
    "hgnn_tasks",
    "escalation_failures",
}

VALID_LATENCY_KEYS: Set[str] = {
    "fast_path_latency_ms",
    "hgnn_latency_ms",
    "escalation_latency_ms",
    "route_remote_latency_ms",
    "route_and_execute_latency_ms",
}

VALID_DISPATCH_KEYS: Set[str] = {
    "dispatch_planner_ok_total",
    "dispatch_planner_err_total",
    "dispatch_hgnn_ok_total",
    "dispatch_hgnn_err_total",
}

VALID_PERSISTENCE_KEYS: Set[str] = {
    "proto_plan_upsert_ok_total",
    "proto_plan_upsert_err_total",
    "proto_plan_upsert_truncated_total",
    "outbox_embed_enqueue_ok_total",
    "outbox_embed_enqueue_dup_total",
    "outbox_embed_enqueue_err_total",
}


def validate_non_negative(value: int, field_name: str) -> None:
    """Validate that a value is non-negative."""
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative, got {value}")


def validate_positive_if_present(value: Optional[float], field_name: str) -> None:
    """Validate that a value is positive if not None."""
    if value is not None and value < 0:
        raise ValueError(f"{field_name} must be non-negative if provided, got {value}")


@dataclass
class RoutingMetrics:
    """Routing decision metrics with validation."""
    total: int = 0
    fast: int = 0
    planner: int = 0
    hgnn: int = 0
    hgnn_plan_generated: int = 0
    hgnn_plan_empty: int = 0
    
    def __post_init__(self):
        """Validate routing metrics values."""
        validate_non_negative(self.total, "total")
        validate_non_negative(self.fast, "fast")
        validate_non_negative(self.planner, "planner")
        validate_non_negative(self.hgnn, "hgnn")
        validate_non_negative(self.hgnn_plan_generated, "hgnn_plan_generated")
        validate_non_negative(self.hgnn_plan_empty, "hgnn_plan_empty")
        
        # Validate consistency: total should match sum if set manually
        calculated_total = self.fast + self.planner + self.hgnn
        if self.total > 0 and calculated_total > 0 and self.total != calculated_total:
            logger.warning(
                f"RoutingMetrics total ({self.total}) doesn't match sum of routes ({calculated_total})"
            )
    
    @property
    def fast_rate(self) -> Optional[float]:
        """Fast path routing rate."""
        if self.total == 0:
            return None
        return self.fast / self.total
    
    @property
    def planner_rate(self) -> Optional[float]:
        """Planner routing rate."""
        if self.total == 0:
            return None
        return self.planner / self.total
    
    @property
    def hgnn_rate(self) -> Optional[float]:
        """HGNN routing rate."""
        if self.total == 0:
            return None
        return self.hgnn / self.total
    
    @property
    def hgnn_plan_success_rate(self) -> Optional[float]:
        """HGNN plan generation success rate."""
        if self.hgnn == 0:
            return None
        return self.hgnn_plan_generated / self.hgnn
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoutingMetrics":
        """
        Create RoutingMetrics from dictionary with validation.
        
        Args:
            data: Dictionary containing routing metrics
        
        Returns:
            RoutingMetrics instance
        
        Raises:
            ValueError: If invalid metric keys or negative values are present
        """
        # Extract and validate keys
        fast = data.get("fast_routed_total", 0)
        planner = data.get("planner_routed_total", 0)
        hgnn = data.get("hgnn_routed_total", 0)
        hgnn_plan_gen = data.get("hgnn_plan_generated_total", 0)
        hgnn_plan_empty = data.get("hgnn_plan_empty_total", 0)
        
        total = data.get("total", fast + planner + hgnn)
        
        return cls(
            total=total,
            fast=fast,
            planner=planner,
            hgnn=hgnn,
            hgnn_plan_generated=hgnn_plan_gen,
            hgnn_plan_empty=hgnn_plan_empty,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "fast": self.fast,
            "planner": self.planner,
            "hgnn": self.hgnn,
            "hgnn_plan_generated": self.hgnn_plan_generated,
            "hgnn_plan_empty": self.hgnn_plan_empty,
            "fast_rate": self.fast_rate,
            "planner_rate": self.planner_rate,
            "hgnn_rate": self.hgnn_rate,
            "hgnn_plan_success_rate": self.hgnn_plan_success_rate,
        }


@dataclass
class ExecutionMetrics:
    """Task execution metrics with validation."""
    total: int = 0
    successful: int = 0
    failed: int = 0
    fast_path: int = 0
    hgnn: int = 0
    escalation_failures: int = 0
    
    def __post_init__(self):
        """Validate execution metrics values."""
        validate_non_negative(self.total, "total")
        validate_non_negative(self.successful, "successful")
        validate_non_negative(self.failed, "failed")
        validate_non_negative(self.fast_path, "fast_path")
        validate_non_negative(self.hgnn, "hgnn")
        validate_non_negative(self.escalation_failures, "escalation_failures")
        
        # Validate consistency
        if self.total > 0:
            expected_total = self.successful + self.failed
            if expected_total > 0 and self.total != expected_total:
                logger.warning(
                    f"ExecutionMetrics total ({self.total}) doesn't match successful + failed ({expected_total})"
                )
    
    @property
    def success_rate(self) -> Optional[float]:
        """Overall success rate."""
        if self.total == 0:
            return None
        return self.successful / self.total
    
    @property
    def fast_path_rate(self) -> Optional[float]:
        """Fast path execution rate."""
        if self.total == 0:
            return None
        return self.fast_path / self.total
    
    @property
    def hgnn_rate(self) -> Optional[float]:
        """HGNN execution rate."""
        if self.total == 0:
            return None
        return self.hgnn / self.total
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionMetrics":
        """
        Create ExecutionMetrics from dictionary with validation.
        
        Args:
            data: Dictionary containing execution metrics
        
        Returns:
            ExecutionMetrics instance
        
        Raises:
            ValueError: If invalid metric keys or negative values are present
        """
        return cls(
            total=data.get("total_tasks", 0),
            successful=data.get("successful_tasks", 0),
            failed=data.get("failed_tasks", 0),
            fast_path=data.get("fast_path_tasks", 0),
            hgnn=data.get("hgnn_tasks", 0),
            escalation_failures=data.get("escalation_failures", 0),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "fast_path": self.fast_path,
            "hgnn": self.hgnn,
            "escalation_failures": self.escalation_failures,
            "success_rate": self.success_rate,
            "fast_path_rate": self.fast_path_rate,
            "hgnn_rate": self.hgnn_rate,
        }


@dataclass
class LatencyMetrics:
    """Latency statistics with validation."""
    samples: List[float] = field(default_factory=list)
    count: int = 0
    min_ms: Optional[float] = None
    max_ms: Optional[float] = None
    mean_ms: Optional[float] = None
    
    def __post_init__(self):
        """Validate latency metrics values."""
        validate_non_negative(self.count, "count")
        validate_positive_if_present(self.min_ms, "min_ms")
        validate_positive_if_present(self.max_ms, "max_ms")
        validate_positive_if_present(self.mean_ms, "mean_ms")
        
        # Validate samples are non-negative
        if self.samples:
            for i, sample in enumerate(self.samples):
                if sample < 0:
                    raise ValueError(f"Latency sample at index {i} must be non-negative, got {sample}")
        
        # Validate min/max consistency
        if self.min_ms is not None and self.max_ms is not None:
            if self.min_ms > self.max_ms:
                raise ValueError(
                    f"min_ms ({self.min_ms}) cannot be greater than max_ms ({self.max_ms})"
                )
    
    @property
    def avg_ms(self) -> Optional[float]:
        """Average latency (alias for mean_ms)."""
        return self.mean_ms
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], key: str) -> "LatencyMetrics":
        """
        Create LatencyMetrics from dictionary with validation.
        
        Args:
            data: Dictionary containing metrics
            key: Latency metric key (e.g., "fast_path_latency_ms")
        
        Returns:
            LatencyMetrics instance
        
        Raises:
            ValueError: If invalid metric key or negative values are present
        """
        if key not in VALID_LATENCY_KEYS:
            logger.warning(f"Unknown latency key: {key}, expected one of {VALID_LATENCY_KEYS}")
        
        samples = data.get(key, [])
        if not isinstance(samples, list):
            samples = []
        
        # Calculate statistics if samples exist
        count = len(samples)
        min_ms = min(samples) if samples else None
        max_ms = max(samples) if samples else None
        mean_ms = sum(samples) / count if count > 0 else None
        
        return cls(
            samples=samples,
            count=count,
            min_ms=min_ms,
            max_ms=max_ms,
            mean_ms=mean_ms,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "count": self.count,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "avg_ms": self.avg_ms,
        }


@dataclass
class DispatchMetrics:
    """Dispatch operation metrics with validation."""
    planner_ok: int = 0
    planner_err: int = 0
    hgnn_ok: int = 0
    hgnn_err: int = 0
    
    def __post_init__(self):
        """Validate dispatch metrics values."""
        validate_non_negative(self.planner_ok, "planner_ok")
        validate_non_negative(self.planner_err, "planner_err")
        validate_non_negative(self.hgnn_ok, "hgnn_ok")
        validate_non_negative(self.hgnn_err, "hgnn_err")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DispatchMetrics":
        """
        Create DispatchMetrics from dictionary with validation.
        
        Args:
            data: Dictionary containing dispatch metrics
        
        Returns:
            DispatchMetrics instance
        
        Raises:
            ValueError: If invalid metric keys or negative values are present
        """
        return cls(
            planner_ok=data.get("dispatch_planner_ok_total", 0),
            planner_err=data.get("dispatch_planner_err_total", 0),
            hgnn_ok=data.get("dispatch_hgnn_ok_total", 0),
            hgnn_err=data.get("dispatch_hgnn_err_total", 0),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "planner_ok": self.planner_ok,
            "planner_err": self.planner_err,
            "hgnn_ok": self.hgnn_ok,
            "hgnn_err": self.hgnn_err,
        }


@dataclass
class PersistenceMetrics:
    """Persistence operation metrics with validation."""
    proto_plan_upsert_ok: int = 0
    proto_plan_upsert_err: int = 0
    proto_plan_upsert_truncated: int = 0
    outbox_embed_enqueue_ok: int = 0
    outbox_embed_enqueue_dup: int = 0
    outbox_embed_enqueue_err: int = 0
    
    def __post_init__(self):
        """Validate persistence metrics values."""
        validate_non_negative(self.proto_plan_upsert_ok, "proto_plan_upsert_ok")
        validate_non_negative(self.proto_plan_upsert_err, "proto_plan_upsert_err")
        validate_non_negative(self.proto_plan_upsert_truncated, "proto_plan_upsert_truncated")
        validate_non_negative(self.outbox_embed_enqueue_ok, "outbox_embed_enqueue_ok")
        validate_non_negative(self.outbox_embed_enqueue_dup, "outbox_embed_enqueue_dup")
        validate_non_negative(self.outbox_embed_enqueue_err, "outbox_embed_enqueue_err")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersistenceMetrics":
        """
        Create PersistenceMetrics from dictionary with validation.
        
        Args:
            data: Dictionary containing persistence metrics
        
        Returns:
            PersistenceMetrics instance
        
        Raises:
            ValueError: If invalid metric keys or negative values are present
        """
        return cls(
            proto_plan_upsert_ok=data.get("proto_plan_upsert_ok_total", 0),
            proto_plan_upsert_err=data.get("proto_plan_upsert_err_total", 0),
            proto_plan_upsert_truncated=data.get("proto_plan_upsert_truncated_total", 0),
            outbox_embed_enqueue_ok=data.get("outbox_embed_enqueue_ok_total", 0),
            outbox_embed_enqueue_dup=data.get("outbox_embed_enqueue_dup_total", 0),
            outbox_embed_enqueue_err=data.get("outbox_embed_enqueue_err_total", 0),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "proto_plan_upsert_ok": self.proto_plan_upsert_ok,
            "proto_plan_upsert_err": self.proto_plan_upsert_err,
            "proto_plan_upsert_truncated": self.proto_plan_upsert_truncated,
            "outbox_embed_enqueue_ok": self.outbox_embed_enqueue_ok,
            "outbox_embed_enqueue_dup": self.outbox_embed_enqueue_dup,
            "outbox_embed_enqueue_err": self.outbox_embed_enqueue_err,
        }


def validate_metric_key(key: str, valid_keys: Set[str], metric_type: str = "metric") -> None:
    """
    Validate that a metric key is in the set of valid keys.
    
    Args:
        key: Metric key to validate
        valid_keys: Set of valid keys
        metric_type: Type of metric for error messages
    
    Raises:
        ValueError: If key is not in valid_keys
    """
    if key not in valid_keys:
        raise ValueError(
            f"Invalid {metric_type} key: {key}. "
            f"Expected one of: {sorted(valid_keys)}"
        )
