"""
Ray connection configuration for SeedCore.
Supports both local and remote Ray clusters with flexible configuration.
"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class RayConfig:
    """Configuration for Ray cluster connection."""
    
    # Connection settings
    address: Optional[str] = None
    port: int = 10001
    host: Optional[str] = None
    
    # Authentication (if needed)
    password: Optional[str] = None
    
    # Connection options
    namespace: Optional[str] = None
    ignore_reinit_error: bool = True
    
    # Timeout settings
    connection_timeout: int = 30
    
    # Development vs production
    is_remote: bool = False
    
    def __post_init__(self):
        """Set defaults and validate configuration."""
        # Set remote flag based on address
        if self.address and ('ray://' in self.address or self.host):
            self.is_remote = True
        
        # Get namespace from environment, default to "seedcore-dev" for consistency
        self.namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
    
    @classmethod
    def from_env(cls) -> 'RayConfig':
        """Create configuration from environment variables."""
        return cls(
            address=os.getenv('RAY_ADDRESS'),
            port=int(os.getenv('RAY_PORT', '10001')),
            host=os.getenv('RAY_HOST'),
            password=os.getenv('RAY_PASSWORD'),
            namespace=os.getenv('RAY_NAMESPACE'),
            ignore_reinit_error=os.getenv('RAY_IGNORE_REINIT_ERROR', 'true').lower() == 'true',
            connection_timeout=int(os.getenv('RAY_CONNECTION_TIMEOUT', '30')),
        )
    
    @classmethod
    def local(cls) -> 'RayConfig':
        """Create configuration for local Ray cluster."""
        return cls(
            address=None,  # Use default local Ray
            is_remote=False
        )
    
    @classmethod
    def remote(cls, host: str, port: int = 10001, password: Optional[str] = None) -> 'RayConfig':
        """Create configuration for remote Ray cluster."""
        return cls(
            address=f"ray://{host}:{port}",
            host=host,
            port=port,
            password=password,
            is_remote=True
        )
    
    def get_connection_args(self) -> Dict[str, Any]:
        """Get arguments for ray.init()."""
        args = {
            'ignore_reinit_error': self.ignore_reinit_error,
            'namespace': self.namespace,
        }
        
        if self.address:
            args['address'] = self.address
        elif self.host:
            args['address'] = f"ray://{self.host}:{self.port}"
        
        if self.password:
            args['_password'] = self.password
        
        return args
    
    def is_configured(self) -> bool:
        """Check if Ray is configured (either local or remote)."""
        return self.address is not None or self.host is not None
    
    def __str__(self) -> str:
        """String representation for logging."""
        if self.is_remote:
            return f"RayConfig(remote={self.host}:{self.port}, namespace={self.namespace})"
        else:
            return f"RayConfig(local, namespace={self.namespace})"


# Global configuration instance
ray_config = RayConfig.from_env()


def get_ray_config() -> RayConfig:
    """Get the global Ray configuration."""
    return ray_config


def set_ray_config(config: RayConfig) -> None:
    """Set the global Ray configuration."""
    global ray_config
    ray_config = config


def configure_ray_remote(host: str, port: int = 10001, password: Optional[str] = None) -> None:
    """Configure Ray for remote connection."""
    config = RayConfig.remote(host, port, password)
    set_ray_config(config)


def configure_ray_local() -> None:
    """Configure Ray for local connection."""
    config = RayConfig.local()
    set_ray_config(config) 