"""
SeedCore Hardware Abstraction Layer (HAL)
==========================================

The HAL module provides a unified interface for interacting with various robot
platforms and hardware devices. It abstracts away SDK-specific details and
provides a consistent API for SeedCore task execution.

Module Structure:
-----------------
- interfaces: Abstract base classes defining the robot driver contract
- drivers: SDK-specific implementations (Reachy, Drone, etc.)
- adapters: Converters between SeedCore JSON and SDK-native types
- media: Camera/audio stream handling via GStreamer/WebRTC

Architecture:
-------------
The HAL follows a layered architecture:

1. **Interfaces Layer**: Defines the BaseRobotDriver contract that all
   robot implementations must follow. This ensures consistent behavior
   across different robot types.

2. **Drivers Layer**: Contains concrete implementations for specific robot
   SDKs (e.g., ReachyMini, Drone SDKs). Each driver implements the
   BaseRobotDriver interface.

3. **Adapters Layer**: Converts between SeedCore's JSON-based task payloads
   (TaskPayload v2.5) and SDK-native types (e.g., NumPy arrays for poses).
   This allows SeedCore to work with any robot without modifying core logic.

4. **Media Layer**: Handles camera and audio streams using GStreamer/WebRTC
   for real-time multimodal interactions.

Usage Example:
--------------
```python
from seedcore.hal import get_robot_driver
from seedcore.hal.adapters import PoseAdapter
from seedcore.models.task_payload import TaskPayload

# Get a robot driver (auto-detects or uses config)
driver = get_robot_driver("reachy")

# Convert SeedCore task to robot commands
task = TaskPayload(...)
pose = PoseAdapter.task_to_pose(task.params.get("motion", {}))

# Execute on robot
driver.move_to_pose(pose, duration=1.0)
```

Design Principles:
-----------------
- **Abstraction**: Core SeedCore logic never depends on specific robot SDKs
- **Extensibility**: Easy to add new robot types without modifying core code
- **Type Safety**: Clear contracts between layers using abstract base classes
- **Multimodal**: Built-in support for camera/audio streams via TaskPayload v2.5
"""

from .interfaces import (
    BaseRobotDriver,
    BaseIoTDeviceDriver,
    RobotState,
    RobotCapabilities,
    ProprioceptionState,
)
from .adapters.pose_adapter import PoseAdapter
from .adapters.motion_adapter import MotionAdapter
from .media.stream_manager import StreamManager

__all__ = [
    "BaseRobotDriver",
    "BaseIoTDeviceDriver",
    "RobotState",
    "RobotCapabilities",
    "ProprioceptionState",
    "PoseAdapter",
    "MotionAdapter",
    "StreamManager",
    "get_robot_driver",
]

def get_robot_driver(robot_type: str, **kwargs) -> BaseRobotDriver:
    """
    Factory function to get a robot driver instance.
    
    Args:
        robot_type: Type of robot ("reachy", "drone", etc.)
        **kwargs: Additional configuration passed to the driver
        
    Returns:
        BaseRobotDriver instance
        
    Raises:
        ValueError: If robot_type is not supported
    """
    from .drivers import get_driver
    
    return get_driver(robot_type, **kwargs)
