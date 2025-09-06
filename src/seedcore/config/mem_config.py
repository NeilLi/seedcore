"""
Memory subsystem configuration.

This module centralizes all memory and caching related configuration variables,
providing a single source of truth for the memory subsystem settings.

Environment Variables:
    SHARED_CACHE_SHARDS: Number of L2 cache shards (default: 256)
    SHARED_CACHE_VNODES: Virtual nodes per shard for consistent hashing (default: 64)
    SHARED_CACHE_TTL_S: L2 cache TTL in seconds (default: 3600)
    SHARED_CACHE_L1_TTL_S: L1 (node) cache TTL in seconds (default: 30)
    SHARED_CACHE_MAX_BYTES_PER_SHARD: Max bytes per shard (default: 2GB)
    SHARED_CACHE_MODE: Cache mode - 'ref' or 'inline' (default: 'ref')
    SHARED_CACHE_EPOCH: Epoch version for cache remapping (default: 1)
    MEMORY_NAMESPACE: Ray namespace for memory actors (default: 'mem-dev')
    MW_ACTOR_NAME: Name for MwStore actor (default: 'mw')
    SHARED_CACHE_NAME: Base name for cache actors (default: 'shared_cache')
    AUTO_CREATE: Auto-create missing actors (default: '0')
    LOOKUP_RETRIES: Number of retries for actor lookup (default: 12)
    LOOKUP_BACKOFF_S: Initial backoff time in seconds (default: 0.5)
    LOOKUP_BACKOFF_MULT: Backoff multiplier (default: 1.5)
    LOG_LEVEL: Logging level (default: 'INFO')
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MemoryConfig:
    """Centralized configuration for the memory subsystem."""
    
    # Ray configuration
    ray_address: str = os.getenv("RAY_ADDRESS", "auto")
    namespace: str = os.getenv("MEMORY_NAMESPACE", "mem-dev")
    
    # Actor names
    mw_actor_name: str = os.getenv("MW_ACTOR_NAME", "mw")
    shared_cache_name: str = os.getenv("SHARED_CACHE_NAME", "shared_cache")
    
    # Cache sharding configuration
    num_shards: int = int(os.getenv("SHARED_CACHE_SHARDS", "4"))
    vnodes_per_shard: int = int(os.getenv("SHARED_CACHE_VNODES", "4"))
    
    # TTL configuration
    l2_ttl_s: int = int(os.getenv("SHARED_CACHE_TTL_S", "3600"))
    l1_ttl_s: int = int(os.getenv("SHARED_CACHE_L1_TTL_S", "30"))
    
    # Memory management
    max_bytes_per_shard: int = int(os.getenv("SHARED_CACHE_MAX_BYTES_PER_SHARD", "2000000000"))  # 2GB
    cache_mode: Literal["ref", "inline"] = os.getenv("SHARED_CACHE_MODE", "ref")
    
    # Versioning and deployment
    cache_epoch: int = int(os.getenv("SHARED_CACHE_EPOCH", "1"))
    
    # Bootstrap configuration
    bootstrap_batch_size: int = int(os.getenv("BOOTSTRAP_BATCH_SIZE", "10"))
    
    # Behavior flags
    auto_create: bool = os.getenv("AUTO_CREATE", "0") in {"1", "true", "True"}
    
    # Lookup behavior
    lookup_retries: int = int(os.getenv("LOOKUP_RETRIES", "12"))
    lookup_backoff_s: float = float(os.getenv("LOOKUP_BACKOFF_S", "0.5"))
    lookup_backoff_mult: float = float(os.getenv("LOOKUP_BACKOFF_MULT", "1.5"))
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Computed properties
    @property
    def total_vnodes(self) -> int:
        """Total number of virtual nodes across all shards."""
        return self.num_shards * self.vnodes_per_shard
    
    @property
    def shard_names(self) -> list[str]:
        """List of all shard actor names."""
        return [f"{self.shared_cache_name}_shard_{i}" for i in range(self.num_shards)]
    
    @property
    def max_items_per_shard(self) -> int:
        """Estimated max items per shard based on bytes limit."""
        # Rough estimate: assume average item size of 1KB
        return self.max_bytes_per_shard // 1024
    
    def get_shard_name(self, shard_id: int) -> str:
        """Get the actor name for a specific shard."""
        if not 0 <= shard_id < self.num_shards:
            raise ValueError(f"Shard ID {shard_id} out of range [0, {self.num_shards})")
        return f"{self.shared_cache_name}_shard_{shard_id}"
    
    def get_node_cache_name(self, node_id: str) -> str:
        """Get the actor name for a node cache."""
        return f"node_cache_{node_id}"
    
    def validate(self) -> None:
        """Validate configuration values."""
        if self.num_shards <= 0:
            raise ValueError("SHARED_CACHE_SHARDS must be positive")
        if self.vnodes_per_shard <= 0:
            raise ValueError("SHARED_CACHE_VNODES must be positive")
        if self.l2_ttl_s <= 0:
            raise ValueError("SHARED_CACHE_TTL_S must be positive")
        if self.l1_ttl_s <= 0:
            raise ValueError("SHARED_CACHE_L1_TTL_S must be positive")
        if self.max_bytes_per_shard <= 0:
            raise ValueError("SHARED_CACHE_MAX_BYTES_PER_SHARD must be positive")
        if self.cache_mode not in ("ref", "inline"):
            raise ValueError("SHARED_CACHE_MODE must be 'ref' or 'inline'")
        if self.cache_epoch < 1:
            raise ValueError("SHARED_CACHE_EPOCH must be >= 1")
        if self.lookup_retries < 0:
            raise ValueError("LOOKUP_RETRIES must be non-negative")
        if self.lookup_backoff_s < 0:
            raise ValueError("LOOKUP_BACKOFF_S must be non-negative")
        if self.lookup_backoff_mult < 1.0:
            raise ValueError("LOOKUP_BACKOFF_MULT must be >= 1.0")


# Global configuration instance
CONFIG = MemoryConfig()

# Validate configuration on import
CONFIG.validate()


def get_memory_config() -> MemoryConfig:
    """Get the global memory configuration instance."""
    return CONFIG


def reload_config() -> MemoryConfig:
    """Reload configuration from environment variables."""
    global CONFIG
    CONFIG = MemoryConfig()
    CONFIG.validate()
    return CONFIG


# Convenience functions for common config access
def get_namespace() -> str:
    """Get the memory namespace."""
    return CONFIG.namespace


def get_num_shards() -> int:
    """Get the number of cache shards."""
    return CONFIG.num_shards


def get_vnodes_per_shard() -> int:
    """Get the number of virtual nodes per shard."""
    return CONFIG.vnodes_per_shard


def get_l2_ttl() -> int:
    """Get the L2 cache TTL in seconds."""
    return CONFIG.l2_ttl_s


def get_l1_ttl() -> int:
    """Get the L1 cache TTL in seconds."""
    return CONFIG.l1_ttl_s


def get_cache_mode() -> str:
    """Get the cache mode."""
    return CONFIG.cache_mode


def get_cache_epoch() -> int:
    """Get the cache epoch version."""
    return CONFIG.cache_epoch


def is_auto_create_enabled() -> bool:
    """Check if auto-create is enabled."""
    return CONFIG.auto_create


def get_max_bytes_per_shard() -> int:
    """Get the maximum bytes per shard."""
    return CONFIG.max_bytes_per_shard


def get_max_items_per_shard() -> int:
    """Get the estimated maximum items per shard."""
    return CONFIG.max_items_per_shard


def get_shard_names() -> list[str]:
    """Get all shard actor names."""
    return CONFIG.shard_names


def get_shard_name(shard_id: int) -> str:
    """Get the actor name for a specific shard."""
    return CONFIG.get_shard_name(shard_id)


def get_node_cache_name(node_id: str) -> str:
    """Get the actor name for a node cache."""
    return CONFIG.get_node_cache_name(node_id)


def get_total_vnodes() -> int:
    """Get the total number of virtual nodes."""
    return CONFIG.total_vnodes


# Configuration summary for debugging
def get_config_summary() -> dict:
    """Get a summary of the current configuration."""
    return {
        "namespace": CONFIG.namespace,
        "num_shards": CONFIG.num_shards,
        "vnodes_per_shard": CONFIG.vnodes_per_shard,
        "total_vnodes": CONFIG.total_vnodes,
        "l2_ttl_s": CONFIG.l2_ttl_s,
        "l1_ttl_s": CONFIG.l1_ttl_s,
        "max_bytes_per_shard": CONFIG.max_bytes_per_shard,
        "max_items_per_shard": CONFIG.max_items_per_shard,
        "cache_mode": CONFIG.cache_mode,
        "cache_epoch": CONFIG.cache_epoch,
        "auto_create": CONFIG.auto_create,
        "lookup_retries": CONFIG.lookup_retries,
        "lookup_backoff_s": CONFIG.lookup_backoff_s,
        "lookup_backoff_mult": CONFIG.lookup_backoff_mult,
        "log_level": CONFIG.log_level,
    }


if __name__ == "__main__":
    # Print configuration summary when run directly
    import json
    print("Memory Configuration Summary:")
    print(json.dumps(get_config_summary(), indent=2))
