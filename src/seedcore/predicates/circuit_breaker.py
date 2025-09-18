"""
Circuit breaker implementation for downstream service calls.
"""

import time
import asyncio
from typing import Callable, Any, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    """Simple circuit breaker for downstream service calls."""
    
    def __init__(self, 
                 failure_threshold: int = 5,
                 recovery_timeout: float = 30.0,
                 expected_exception: type = Exception):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        
        # Metrics
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.circuit_opens = 0
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function with circuit breaker protection."""
        self.total_calls += 1
        
        # Check if circuit should be opened
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info(f"Circuit breaker transitioning to HALF_OPEN")
            else:
                self.failed_calls += 1
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
            
        except self.expected_exception as e:
            self._on_failure()
            # Log specific timeout errors for better debugging
            if hasattr(e, '__class__') and 'Timeout' in e.__class__.__name__:
                logger.warning(f"Timeout error in circuit breaker: {e.__class__.__name__}: {e}")
            raise e
        except Exception as e:
            # Log unexpected exceptions but don't count them as circuit breaker failures
            logger.error(f"Unexpected exception in circuit breaker: {e.__class__.__name__}: {e}")
            raise e
    
    def _on_success(self):
        """Handle successful call."""
        self.successful_calls += 1
        self.failure_count = 0
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info(f"Circuit breaker transitioning to CLOSED")
    
    def _on_failure(self):
        """Handle failed call."""
        self.failed_calls += 1
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                self.state = CircuitState.OPEN
                self.circuit_opens += 1
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def get_state(self) -> dict:
        """Get current circuit breaker state."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "circuit_opens": self.circuit_opens,
            "success_rate": self.successful_calls / self.total_calls if self.total_calls > 0 else 0.0
        }

class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(self, 
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 10.0,
                 exponential_base: float = 2.0,
                 jitter: bool = True):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

async def retry_with_backoff(func: Callable, 
                           config: RetryConfig = None,
                           *args, **kwargs) -> Any:
    """Execute a function with exponential backoff retry."""
    if config is None:
        config = RetryConfig()
    
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if attempt == config.max_attempts - 1:
                # Last attempt, re-raise
                raise e
            
            # Calculate delay with exponential backoff
            delay = min(
                config.base_delay * (config.exponential_base ** attempt),
                config.max_delay
            )
            
            # Add jitter
            if config.jitter:
                import random
                delay *= (0.5 + random.random() * 0.5)
            
            logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {delay:.2f}s")
            await asyncio.sleep(delay)
    
    # Should never reach here
    raise last_exception

# ServiceClient has been moved to seedcore.serve.base_client
# This is kept for backward compatibility during migration
class ServiceClient:
    """
    DEPRECATED: Use seedcore.serve.base_client.BaseServiceClient instead.
    
    This class is kept for backward compatibility but will be removed in a future version.
    Please migrate to the new service clients in seedcore.serve package.
    """
    
    def __init__(self, 
                 service_name: str,
                 base_url: str,
                 timeout: float = 10.0,
                 circuit_breaker: CircuitBreaker = None,
                 retry_config: RetryConfig = None):
        import warnings
        warnings.warn(
            "ServiceClient is deprecated. Use seedcore.serve.base_client.BaseServiceClient instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        # Import the new base client
        from seedcore.serve.base_client import BaseServiceClient
        
        # Create the new client instance
        self._client = BaseServiceClient(
            service_name=service_name,
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
        
        # Expose the old interface
        self.service_name = service_name
        self.base_url = base_url
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker
        self.retry_config = retry_config
    
    async def post(self, endpoint: str, json: dict = None, **kwargs) -> dict:
        """Make a POST request with circuit breaker and retry."""
        return await self._client.post(endpoint, json=json, **kwargs)
    
    async def get(self, endpoint: str, **kwargs) -> dict:
        """Make a GET request with circuit breaker and retry."""
        return await self._client.get(endpoint, **kwargs)
    
    def get_metrics(self) -> dict:
        """Get circuit breaker metrics."""
        return self._client.get_metrics()
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.close()
