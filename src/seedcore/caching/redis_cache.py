"""
Redis caching utility for SeedCore energy endpoints.

This module provides Redis-based caching for computationally expensive
energy calculations to improve response times.
"""

import json
import time
import logging
from typing import Any, Dict, Optional, Union
import redis
from functools import wraps

logger = logging.getLogger(__name__)

class RedisCache:
    """Redis caching utility for SeedCore."""
    
    def __init__(self, host: str = None, port: int = None, db: int = None, 
                 password: Optional[str] = None, decode_responses: bool = True):
        """Initialize Redis connection."""
        # Use environment variables if not provided
        import os
        host = host or os.getenv("REDIS_HOST", "redis")
        port = port or int(os.getenv("REDIS_PORT", "6379"))
        db = db or int(os.getenv("REDIS_DB", "0"))
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=decode_responses,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )
        # Detect read-only replica status
        self.read_only = False
        try:
            import os
            if os.getenv("REDIS_READONLY", "").lower() in {"1", "true", "yes"}:
                self.read_only = True
            else:
                info = self.redis_client.info(section='replication')
                role = str(info.get('role', '')).lower()
                # Common roles: 'master'/'primary' vs 'slave'/'replica'
                if role in {"slave", "replica", "readonly", "reader"}:
                    self.read_only = True
        except Exception:
            # Be conservative: leave as False if we cannot detect
            pass
        
    def ping(self) -> bool:
        """Test Redis connectivity."""
        try:
            return self.redis_client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get failed for key {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, expire: int = 300) -> bool:
        """Set value in cache with expiration (default 5 minutes)."""
        try:
            if getattr(self, 'read_only', False):
                logger.debug(f"Redis is read-only; skip set for key {key}")
                return False
            serialized = json.dumps(value, default=str)
            return self.redis_client.setex(key, expire, serialized)
        except Exception as e:
            # Downgrade log level for read-only replica to avoid noisy ERRORs
            msg = str(e).lower()
            if "read only replica" in msg or "readonly" in msg:
                # Mark as read-only for subsequent calls
                self.read_only = True
                logger.warning(f"Redis set skipped (read-only) for key {key}")
                return False
            logger.error(f"Redis set failed for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            logger.error(f"Redis delete failed for key {key}: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            return bool(self.redis_client.exists(key))
        except Exception as e:
            logger.error(f"Redis exists failed for key {key}: {e}")
            return False
    
    def ttl(self, key: str) -> int:
        """Get time to live for key."""
        try:
            return self.redis_client.ttl(key)
        except Exception as e:
            logger.error(f"Redis TTL failed for key {key}: {e}")
            return -1

# Global Redis cache instance
_redis_cache = None

def get_redis_cache() -> RedisCache:
    """Get global Redis cache instance."""
    global _redis_cache
    if _redis_cache is None:
        _redis_cache = RedisCache()
    return _redis_cache

def cache_result(cache_key: str, expire: int = 300, fallback_on_error: bool = True):
    """
    Decorator to cache function results in Redis.
    
    Args:
        cache_key: Redis key to use for caching
        expire: Cache expiration time in seconds (default 5 minutes)
        fallback_on_error: Whether to execute function if Redis fails
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_redis_cache()
            
            # Try to get from cache first
            if cache.ping():
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    logger.debug(f"Cache hit for key: {cache_key}")
                    return cached_result
            
            # Execute function if cache miss or Redis unavailable
            try:
                result = func(*args, **kwargs)
                
                # Cache the result if Redis is available
                if cache.ping():
                    cache.set(cache_key, result, expire)
                    logger.debug(f"Cached result for key: {cache_key}")
                
                return result
            except Exception as e:
                logger.error(f"Function execution failed: {e}")
                if fallback_on_error and cache.ping():
                    # Try to return stale cache if available
                    cached_result = cache.get(cache_key)
                    if cached_result is not None:
                        logger.warning(f"Returning stale cache for key: {cache_key}")
                        return cached_result
                raise
        
        return wrapper
    return decorator

def invalidate_cache(cache_key: str) -> bool:
    """Invalidate a specific cache key."""
    cache = get_redis_cache()
    return cache.delete(cache_key)

def clear_energy_cache() -> bool:
    """Clear all energy-related cache entries."""
    cache = get_redis_cache()
    try:
        # Get all keys matching energy patterns
        keys = cache.redis_client.keys("energy:*")
        if keys:
            cache.redis_client.delete(*keys)
            logger.info(f"Cleared {len(keys)} energy cache entries")
            return True
        return True
    except Exception as e:
        logger.error(f"Failed to clear energy cache: {e}")
        return False

# Cache key generators
def energy_gradient_cache_key() -> str:
    """Generate cache key for energy gradient endpoint."""
    return f"energy:gradient:{int(time.time() // 30)}"  # 30-second windows

def energy_monitor_cache_key() -> str:
    """Generate cache key for energy monitor endpoint."""
    return f"energy:monitor:{int(time.time() // 30)}"  # 30-second windows

def energy_calibrate_cache_key() -> str:
    """Generate cache key for energy calibrate endpoint."""
    return f"energy:calibrate:{int(time.time() // 60)}"  # 1-minute windows 