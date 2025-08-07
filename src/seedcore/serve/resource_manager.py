"""
Resource management for Ray Serve deployments.

This module provides comprehensive resource management including:
- Concurrency limits and timeouts
- Rate limiting and backoff strategies
- Graceful failure handling
- Resource monitoring and scaling
"""

import asyncio
import time
import logging
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum
import threading
from collections import defaultdict, deque
import random

logger = logging.getLogger(__name__)


class ResourceStatus(Enum):
    """Resource status indicators."""
    AVAILABLE = "available"
    LIMITED = "limited"
    OVERLOADED = "overloaded"
    FAILED = "failed"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_second: int = 10
    burst_size: int = 5
    window_size: float = 60.0  # seconds


@dataclass
class TimeoutConfig:
    """Configuration for timeouts."""
    request_timeout: float = 30.0  # seconds
    connection_timeout: float = 10.0  # seconds
    retry_timeout: float = 5.0  # seconds
    max_retries: int = 3


@dataclass
class ConcurrencyConfig:
    """Configuration for concurrency limits."""
    max_concurrent_requests: int = 10
    max_queue_size: int = 100
    worker_timeout: float = 60.0  # seconds


class RateLimiter:
    """Token bucket rate limiter implementation."""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.tokens = config.burst_size
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens from the rate limiter.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            True if tokens were acquired, False otherwise
        """
        with self.lock:
            now = time.time()
            
            # Refill tokens based on time passed
            time_passed = now - self.last_refill
            tokens_to_add = time_passed * (self.config.requests_per_minute / 60.0)
            self.tokens = min(self.config.burst_size, self.tokens + tokens_to_add)
            self.last_refill = now
            
            # Check if we have enough tokens
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            return False
    
    def wait_for_tokens(self, tokens: int = 1, timeout: float = 10.0) -> bool:
        """
        Wait for tokens to become available.
        
        Args:
            tokens: Number of tokens needed
            timeout: Maximum time to wait
            
        Returns:
            True if tokens were acquired, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.acquire(tokens):
                return True
            time.sleep(0.1)  # Small delay to avoid busy waiting
        
        return False


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit breaker is open or function fails
        """
        if not self._can_execute():
            raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _can_execute(self) -> bool:
        """Check if execution is allowed."""
        with self.lock:
            if self.state == "CLOSED":
                return True
            elif self.state == "OPEN":
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    return True
                return False
            else:  # HALF_OPEN
                return True
    
    def _on_success(self):
        """Handle successful execution."""
        with self.lock:
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
    
    def _on_failure(self):
        """Handle failed execution."""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


class ResourceManager:
    """
    Comprehensive resource manager for Ray Serve deployments.
    
    This class manages:
    - Rate limiting for API calls
    - Concurrency limits
    - Timeouts and retries
    - Circuit breaker pattern
    - Resource monitoring
    """
    
    def __init__(
        self,
        rate_limit_config: Optional[RateLimitConfig] = None,
        timeout_config: Optional[TimeoutConfig] = None,
        concurrency_config: Optional[ConcurrencyConfig] = None
    ):
        self.rate_limit_config = rate_limit_config or RateLimitConfig()
        self.timeout_config = timeout_config or TimeoutConfig()
        self.concurrency_config = concurrency_config or ConcurrencyConfig()
        
        # Initialize components
        self.rate_limiter = RateLimiter(self.rate_limit_config)
        self.circuit_breaker = CircuitBreaker()
        
        # Concurrency tracking
        self.active_requests = 0
        self.request_queue = deque()
        self.request_history = deque(maxlen=1000)
        
        # Monitoring
        self.start_time = time.time()
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.timeout_requests = 0
        
        # Thread safety
        self.lock = threading.Lock()
        
        logger.info("✅ Resource manager initialized")
    
    async def execute_with_limits(
        self,
        func: Callable,
        *args,
        priority: int = 0,
        **kwargs
    ) -> Any:
        """
        Execute a function with resource limits and monitoring.
        
        Args:
            func: Function to execute
            *args: Function arguments
            priority: Request priority (higher = more important)
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If limits are exceeded or function fails
        """
        request_id = f"req_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        start_time = time.time()
        
        # Check concurrency limits
        if not await self._check_concurrency_limits():
            raise Exception("Concurrency limit exceeded")
        
        # Check rate limits
        if not self.rate_limiter.acquire():
            raise Exception("Rate limit exceeded")
        
        # Execute with circuit breaker and timeout
        try:
            with self.lock:
                self.active_requests += 1
                self.total_requests += 1
            
            # Execute with timeout
            result = await asyncio.wait_for(
                asyncio.to_thread(self.circuit_breaker.call, func, *args, **kwargs),
                timeout=self.timeout_config.request_timeout
            )
            
            # Record success
            with self.lock:
                self.successful_requests += 1
                self.active_requests -= 1
            
            # Record request
            self._record_request(request_id, "success", time.time() - start_time)
            
            return result
            
        except asyncio.TimeoutError:
            with self.lock:
                self.timeout_requests += 1
                self.active_requests -= 1
            
            self._record_request(request_id, "timeout", time.time() - start_time)
            raise Exception("Request timeout")
            
        except Exception as e:
            with self.lock:
                self.failed_requests += 1
                self.active_requests -= 1
            
            self._record_request(request_id, "failed", time.time() - start_time)
            raise e
    
    async def _check_concurrency_limits(self) -> bool:
        """Check if concurrency limits allow execution."""
        with self.lock:
            if self.active_requests >= self.concurrency_config.max_concurrent_requests:
                return False
            return True
    
    def _record_request(self, request_id: str, status: str, duration: float):
        """Record request details for monitoring."""
        self.request_history.append({
            "id": request_id,
            "status": status,
            "duration": duration,
            "timestamp": time.time(),
            "active_requests": self.active_requests
        })
    
    def get_resource_status(self) -> ResourceStatus:
        """Get current resource status."""
        with self.lock:
            utilization = self.active_requests / self.concurrency_config.max_concurrent_requests
            
            if utilization >= 0.9:
                return ResourceStatus.OVERLOADED
            elif utilization >= 0.7:
                return ResourceStatus.LIMITED
            elif self.circuit_breaker.state == "OPEN":
                return ResourceStatus.FAILED
            else:
                return ResourceStatus.AVAILABLE
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive resource metrics."""
        with self.lock:
            uptime = time.time() - self.start_time
            success_rate = self.successful_requests / max(self.total_requests, 1)
            
            return {
                "uptime_seconds": uptime,
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "timeout_requests": self.timeout_requests,
                "success_rate": success_rate,
                "active_requests": self.active_requests,
                "max_concurrent_requests": self.concurrency_config.max_concurrent_requests,
                "utilization": self.active_requests / self.concurrency_config.max_concurrent_requests,
                "circuit_breaker_state": self.circuit_breaker.state,
                "rate_limiter_tokens": self.rate_limiter.tokens,
                "resource_status": self.get_resource_status().value
            }
    
    def get_recent_requests(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent request history."""
        with self.lock:
            return list(self.request_history)[-limit:]
    
    def reset_metrics(self):
        """Reset all metrics (useful for testing)."""
        with self.lock:
            self.total_requests = 0
            self.successful_requests = 0
            self.failed_requests = 0
            self.timeout_requests = 0
            self.active_requests = 0
            self.request_history.clear()
            self.start_time = time.time()


class RetryManager:
    """Manages retry logic with exponential backoff."""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        retry_on_exceptions: tuple = (Exception,),
        **kwargs
    ) -> Any:
        """
        Execute a function with retry logic.
        
        Args:
            func: Function to execute
            *args: Function arguments
            retry_on_exceptions: Exceptions to retry on
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If all retries are exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except retry_on_exceptions as e:
                last_exception = e
                
                if attempt == self.max_retries:
                    logger.error(f"All {self.max_retries} retries exhausted: {e}")
                    raise e
                
                delay = self._calculate_delay(attempt)
                logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay:.2f}s: {e}")
                await asyncio.sleep(delay)
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            # Add random jitter to prevent thundering herd
            delay *= (0.5 + random.random() * 0.5)
        
        return delay


# Global resource manager instance
_resource_manager: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    """Get the global resource manager instance."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager


def configure_resource_manager(
    rate_limit_config: Optional[RateLimitConfig] = None,
    timeout_config: Optional[TimeoutConfig] = None,
    concurrency_config: Optional[ConcurrencyConfig] = None
) -> ResourceManager:
    """Configure the global resource manager."""
    global _resource_manager
    _resource_manager = ResourceManager(rate_limit_config, timeout_config, concurrency_config)
    return _resource_manager


async def execute_with_resource_limits(
    func: Callable,
    *args,
    priority: int = 0,
    **kwargs
) -> Any:
    """
    Execute a function with resource limits.
    
    Args:
        func: Function to execute
        *args: Function arguments
        priority: Request priority
        **kwargs: Function keyword arguments
        
    Returns:
        Function result
    """
    manager = get_resource_manager()
    return await manager.execute_with_limits(func, *args, priority=priority, **kwargs)


def get_resource_metrics() -> Dict[str, Any]:
    """Get current resource metrics."""
    manager = get_resource_manager()
    return manager.get_metrics()


def get_resource_status() -> ResourceStatus:
    """Get current resource status."""
    manager = get_resource_manager()
    return manager.get_resource_status() 