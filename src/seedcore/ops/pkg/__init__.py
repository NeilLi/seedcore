#!/usr/bin/env python3
"""
SeedCore PKG (Policy Knowledge Graph) Package

Centralized module for managing PKG snapshots, evaluation, and hot-swapping.

Architecture:
- manager.py: PKGManager class for lifecycle management and hot-swapping
- client.py: PKGClient for database operations (read-only)
- evaluator.py: PKGEvaluator for policy evaluation (WASM and native engines)

The PKGManager provides a global singleton instance that:
- Loads the active policy snapshot from the database on startup
- Listens to Redis for hot-swap updates
- Provides thread-safe access to the active evaluator
- Supports both WASM and native rule engines

Usage:
    from seedcore.ops.pkg import get_global_pkg_manager, initialize_global_pkg_manager
    
    # Initialize at application startup
    pkg_manager = await initialize_global_pkg_manager()
    
    # Use in services
    manager = get_global_pkg_manager()
    evaluator = manager.get_active_evaluator()
    if evaluator:
        result = evaluator.evaluate(task_facts)
"""

from .manager import (
    PKGManager,
    get_global_pkg_manager,
    initialize_global_pkg_manager,
)
from .client import (
    PKGClient,
    PKGSnapshotData,
)
from .dao import (
    PKGSnapshotsDAO,
    PKGDeploymentsDAO,
    PKGValidationDAO,
    PKGPromotionsDAO,
    PKGDevicesDAO,
)
from .evaluator import (
    PKGEvaluator,
)

__all__ = [
    # Manager (main entry point)
    "PKGManager",
    "get_global_pkg_manager",
    "initialize_global_pkg_manager",
    # Client (facade for database operations)
    "PKGClient",
    "PKGSnapshotData",
    # DAOs (modular data access)
    "PKGSnapshotsDAO",
    "PKGDeploymentsDAO",
    "PKGValidationDAO",
    "PKGPromotionsDAO",
    "PKGDevicesDAO",
    # Evaluator (policy evaluation)
    "PKGEvaluator",
]

