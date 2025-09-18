#!/usr/bin/env python3
"""
SeedCore Serve Clients

This package provides comprehensive HTTP clients for all SeedCore services
with circuit breaker, retry logic, and standardized error handling.
"""

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig
from .ml_client import MLServiceClient
from .coordinator_client import CoordinatorServiceClient
from .state_client import StateServiceClient
from .energy_client import EnergyServiceClient
from .cognitive_client import CognitiveServiceClient
from .organism_client import OrganismServiceClient

__all__ = [
    "BaseServiceClient",
    "CircuitBreaker", 
    "RetryConfig",
    "MLServiceClient",
    "CoordinatorServiceClient",
    "StateServiceClient",
    "EnergyServiceClient",
    "CognitiveServiceClient",
    "OrganismServiceClient",
    "get_service_client",
    "get_all_service_clients"
]

# Service client registry
SERVICE_CLIENTS = {
    "ml_service": MLServiceClient,
    "coordinator": CoordinatorServiceClient,
    "state": StateServiceClient,
    "energy": EnergyServiceClient,
    "cognitive": CognitiveServiceClient,
    "organism": OrganismServiceClient,
}

def get_service_client(service_name: str, **kwargs):
    """
    Get a service client by name.
    
    Args:
        service_name: Name of the service (ml_service, coordinator, state, energy, cognitive, organism)
        **kwargs: Additional arguments to pass to the client constructor
        
    Returns:
        Service client instance
        
    Raises:
        ValueError: If service name is not recognized
    """
    if service_name not in SERVICE_CLIENTS:
        raise ValueError(f"Unknown service: {service_name}. Available services: {list(SERVICE_CLIENTS.keys())}")
    
    client_class = SERVICE_CLIENTS[service_name]
    return client_class(**kwargs)

def get_all_service_clients(**kwargs):
    """
    Get all service clients.
    
    Args:
        **kwargs: Additional arguments to pass to all client constructors
        
    Returns:
        Dictionary of service name to client instance
    """
    return {
        name: client_class(**kwargs)
        for name, client_class in SERVICE_CLIENTS.items()
    }
