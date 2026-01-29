"""
Robot Driver Implementations
============================

Contains SDK-specific implementations of BaseRobotDriver for various robot platforms.

Available Drivers:
- ReachyMiniDriver: For Reachy Mini robot
- DroneDriver: Placeholder for drone platforms (to be implemented)
"""

from typing import Dict, Any, Optional
import logging

from ..interfaces import BaseRobotDriver

logger = logging.getLogger(__name__)

# Registry of available drivers
_DRIVER_REGISTRY: Dict[str, type] = {}


def register_driver(name: str, driver_class: type) -> None:
    """
    Register a robot driver class.
    
    Args:
        name: Driver name (e.g., "reachy", "drone")
        driver_class: BaseRobotDriver subclass
    """
    if not issubclass(driver_class, BaseRobotDriver):
        raise TypeError(f"Driver class must inherit from BaseRobotDriver")
    _DRIVER_REGISTRY[name.lower()] = driver_class
    logger.debug(f"Registered robot driver: {name}")


def get_driver(robot_type: str, **kwargs) -> BaseRobotDriver:
    """
    Get a robot driver instance.
    
    Args:
        robot_type: Type of robot ("reachy", "drone", etc.)
        **kwargs: Configuration passed to driver constructor
        
    Returns:
        BaseRobotDriver instance
        
    Raises:
        ValueError: If robot_type is not supported
    """
    robot_type = robot_type.lower()
    
    if robot_type not in _DRIVER_REGISTRY:
        available = ", ".join(_DRIVER_REGISTRY.keys())
        raise ValueError(
            f"Unknown robot type: {robot_type}. "
            f"Available types: {available}"
        )
    
    driver_class = _DRIVER_REGISTRY[robot_type]
    return driver_class(**kwargs)


# Import drivers to register them
try:
    from .reachy_mini import ReachyMiniDriver
    register_driver("reachy", ReachyMiniDriver)
except ImportError as e:
    logger.warning(f"Reachy driver not available: {e}")

try:
    from .drone import DroneDriver
    register_driver("drone", DroneDriver)
except ImportError as e:
    logger.debug(f"Drone driver not available: {e}")

# IoT device drivers (not registered in robot registry, accessed directly)
try:
    from .tuya_driver import TuyaDriver
except ImportError as e:
    logger.debug(f"Tuya driver not available: {e}")
    TuyaDriver = None

__all__ = [
    "register_driver",
    "get_driver",
    "ReachyMiniDriver",
    "DroneDriver",
    "TuyaDriver",
]
