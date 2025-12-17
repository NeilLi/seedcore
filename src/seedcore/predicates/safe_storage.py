"""
Safe storage implementation with Redis fallback to in-memory storage.
"""

import json
import time
import logging
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class StorageBackend(ABC):
    """Abstract storage backend interface."""
    
    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a key-value pair with optional TTL."""
        pass
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get a value by key."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a key."""
        pass
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        pass

class InMemoryStorage(StorageBackend):
    """In-memory storage backend with TTL support."""
    
    def __init__(self):
        self._storage: Dict[str, Dict[str, Any]] = {}
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a key-value pair with optional TTL."""
        try:
            expire_time = time.time() + ttl if ttl else None
            self._storage[key] = {
                "value": value,
                "expire_time": expire_time
            }
            self._maybe_cleanup()
            return True
        except Exception as e:
            logger.warning(f"Failed to set key {key}: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get a value by key."""
        try:
            if key not in self._storage:
                return None
            
            entry = self._storage[key]
            
            # Check TTL
            if entry["expire_time"] and time.time() > entry["expire_time"]:
                del self._storage[key]
                return None
            
            return entry["value"]
        except Exception as e:
            logger.warning(f"Failed to get key {key}: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Delete a key."""
        try:
            if key in self._storage:
                del self._storage[key]
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to delete key {key}: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        return self.get(key) is not None
    
    def _maybe_cleanup(self):
        """Clean up expired entries periodically."""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup()
            self._last_cleanup = now
    
    def _cleanup(self):
        """Remove expired entries."""
        now = time.time()
        expired_keys = []
        
        for key, entry in self._storage.items():
            if entry["expire_time"] and now > entry["expire_time"]:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._storage[key]
        
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired entries")

class RedisStorage(StorageBackend):
    """Redis storage backend."""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a key-value pair with optional TTL."""
        try:
            # Serialize value to JSON
            serialized = json.dumps(value)
            
            if ttl:
                return self.redis.setex(key, ttl, serialized)
            else:
                return self.redis.set(key, serialized)
        except Exception as e:
            logger.warning(f"Failed to set key {key} in Redis: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get a value by key."""
        try:
            serialized = self.redis.get(key)
            if serialized is None:
                return None
            
            return json.loads(serialized)
        except Exception as e:
            logger.warning(f"Failed to get key {key} from Redis: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Delete a key."""
        try:
            return bool(self.redis.delete(key))
        except Exception as e:
            logger.warning(f"Failed to delete key {key} from Redis: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        try:
            return bool(self.redis.exists(key))
        except Exception as e:
            logger.warning(f"Failed to check existence of key {key} in Redis: {e}")
            return False

class SafeStorage:
    """Safe storage with Redis fallback to in-memory."""
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self._backend: Optional[StorageBackend] = None
        self._initialize_backend()
    
    def _initialize_backend(self):
        """Initialize the storage backend."""
        if self.redis_client:
            try:
                # Test Redis connection with timeout
                # Use a short timeout to fail fast if Redis is unavailable
                self.redis_client.ping()
                self._backend = RedisStorage(self.redis_client)
                logger.info("✅ Using Redis storage backend")
            except Exception as e:
                # Check error type to provide better diagnostics
                error_msg = str(e)
                error_type = type(e).__name__
                
                # DNS resolution errors suggest Redis service doesn't exist
                if "name resolution" in error_msg.lower() or "temporary failure" in error_msg.lower():
                    logger.info(
                        f"Redis unavailable (DNS resolution failed: {error_msg[:100]}). "
                        "Using in-memory storage (Redis is optional)."
                    )
                elif "Connection refused" in error_msg or "ConnectionError" in error_type:
                    logger.info(
                        f"Redis unavailable (connection refused). "
                        "Using in-memory storage (Redis is optional)."
                    )
                else:
                    logger.warning(
                        f"Redis connection failed ({error_type}): {error_msg[:100]}, "
                        "falling back to in-memory storage"
                    )
                self._backend = InMemoryStorage()
        else:
            logger.info("No Redis client provided, using in-memory storage")
            self._backend = InMemoryStorage()
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a key-value pair."""
        if not self._backend:
            logger.error("No storage backend available")
            return False
        
        return self._backend.set(key, value, ttl)
    
    def get(self, key: str) -> Optional[Any]:
        """Get a value by key."""
        if not self._backend:
            logger.error("No storage backend available")
            return None
        
        return self._backend.get(key)
    
    def delete(self, key: str) -> bool:
        """Delete a key."""
        if not self._backend:
            logger.error("No storage backend available")
            return False
        
        return self._backend.delete(key)
    
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        if not self._backend:
            logger.error("No storage backend available")
            return False
        
        return self._backend.exists(key)
    
    def get_backend_type(self) -> str:
        """Get the type of storage backend being used."""
        if isinstance(self._backend, RedisStorage):
            return "redis"
        elif isinstance(self._backend, InMemoryStorage):
            return "in_memory"
        else:
            return "none"
