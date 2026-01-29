"""
Hardware Abstraction Layer - Base Interfaces
=============================================

Defines the abstract BaseRobotDriver contract that all robot implementations
must follow. This ensures consistent behavior across different robot types
while allowing SDK-specific optimizations.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from enum import Enum
import time
import numpy as np
from dataclasses import dataclass, field


class RobotState(Enum):
    """Robot operational states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    MOVING = "moving"
    ERROR = "error"
    EMERGENCY_STOP = "emergency_stop"


@dataclass
class ProprioceptionState:
    """
    Real-time physical state for VLA feedback loops.
    
    This dataclass captures the current state of the robot's physical
    components, providing proprioceptive feedback for Vision-Language-Action
    models. The data is fed into TaskPayload v2.5 multimodal envelope
    for cognitive processing.
    
    Attributes:
        joint_positions: Dictionary mapping joint names to angles (radians)
        ee_pose: End-effector pose (x, y, z, roll, pitch, yaw)
        imu_data: IMU sensor data (accelerometer, gyroscope, magnetometer)
        is_moving: Whether the robot is currently executing motion
        timestamp: Unix timestamp when this state was captured
        battery_level: Optional battery level (0.0 to 1.0)
        temperature: Optional temperature readings (dict of sensor -> temp)
    """
    joint_positions: Dict[str, float] = field(default_factory=dict)
    ee_pose: Dict[str, float] = field(default_factory=dict)
    imu_data: Dict[str, Any] = field(default_factory=dict)
    is_moving: bool = False
    timestamp: float = field(default_factory=time.time)
    battery_level: Optional[float] = None
    temperature: Dict[str, float] = field(default_factory=dict)


@dataclass
class RobotCapabilities:
    """
    Describes the capabilities of a robot platform.
    
    Attributes:
        has_arms: Whether the robot has articulated arms
        has_head: Whether the robot has a movable head
        has_base: Whether the robot has a mobile base
        num_arms: Number of arms (0 if no arms)
        num_joints_per_arm: Number of joints per arm
        has_camera: Whether the robot has camera(s)
        has_microphone: Whether the robot has microphone(s)
        max_linear_velocity: Maximum linear velocity (m/s)
        max_angular_velocity: Maximum angular velocity (rad/s)
        supported_pose_types: List of supported pose types (e.g., ["head", "arm", "base"])
    """
    has_arms: bool = False
    has_head: bool = False
    has_base: bool = False
    num_arms: int = 0
    num_joints_per_arm: int = 0
    has_camera: bool = False
    has_microphone: bool = False
    max_linear_velocity: float = 0.0
    max_angular_velocity: float = 0.0
    supported_pose_types: List[str] = None
    
    def __post_init__(self):
        if self.supported_pose_types is None:
            self.supported_pose_types = []


class BaseRobotDriver(ABC):
    """
    Enhanced VLA-Ready Hardware Abstraction Layer.
    
    Abstract base class for robot drivers with Vision-Language-Action (VLA)
    support. All robot SDK implementations must inherit from this class and
    implement all abstract methods.
    
    The driver handles:
    - Connection lifecycle (connect/disconnect)
    - Motion control (high-frequency instant moves, smooth interpolation)
    - State queries (proprioception, current pose, joint angles)
    - Multimodal I/O (camera frames, audio streaming)
    - Error handling and safety (emergency stop)
    
    Design Notes:
    - Methods accept SeedCore-native types (dicts, lists) for easy integration
    - SDK-specific conversions happen in adapters
    - High-frequency methods (move_instant, get_proprioception) are optimized
      for VLA token streaming at 20Hz+
    - All methods should be thread-safe if the underlying SDK supports it
    - State changes should be atomic where possible
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the robot driver.
        
        Args:
            config: Optional configuration dictionary. SDK-specific keys allowed.
                   Common keys:
                   - "energy": Energy level (0-100) affecting motion speed
                   - "warmth": Warmth level (0-100) affecting motion style
        """
        self.config = config or {}
        self._state = RobotState.DISCONNECTED
        self._capabilities = self._initialize_capabilities()
    
    @property
    def state(self) -> RobotState:
        """Current robot state."""
        return self._state
    
    @property
    def capabilities(self) -> RobotCapabilities:
        """
        Get robot capabilities. Initialized on driver creation.
        
        Returns:
            RobotCapabilities instance
        """
        return self._capabilities
    
    @abstractmethod
    def _initialize_capabilities(self) -> RobotCapabilities:
        """
        Define hardware limits and degrees of freedom on initialization.
        
        This method is called during __init__ to set up the robot's
        capabilities before connection. Override to specify robot-specific
        capabilities.
        
        Returns:
            RobotCapabilities instance describing this robot's capabilities
        """
        pass
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to the robot.
        
        Returns:
            True if connection successful, False otherwise
            
        Raises:
            RuntimeError: If connection fails after retries
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """
        Disconnect from the robot gracefully.
        
        Should:
        - Stop all motion
        - Release resources
        - Set state to DISCONNECTED
        """
        pass
    
    @abstractmethod
    def emergency_stop(self) -> None:
        """
        Immediately stop all robot motion (safety-critical).
        
        Should:
        - Stop all motors immediately
        - Set state to EMERGENCY_STOP
        - Log the emergency stop event
        """
        pass
    
    @abstractmethod
    def get_current_pose(self, pose_type: str = "head") -> Dict[str, Any]:
        """
        Get the current pose of a robot component.
        
        Args:
            pose_type: Type of pose to query ("head", "arm", "base", etc.)
            
        Returns:
            Dictionary with pose data. Format depends on pose_type:
            - "head": {"x": float, "y": float, "z": float, "roll": float, "pitch": float, "yaw": float}
            - "arm": {"joints": [float, ...], "end_effector": {...}}
            - "base": {"x": float, "y": float, "theta": float}
            
        Raises:
            ValueError: If pose_type is not supported
            RuntimeError: If robot is not connected
        """
        pass
    
    @abstractmethod
    def move_instant(
        self,
        target: Dict[str, Any],
        pose_type: str = "head",
        **kwargs
    ) -> None:
        """
        High-frequency motion control for VLA token streaming (20Hz+).
        
        Bypasses interpolation and sets target directly. This is crucial for
        real-time VLA control where latency matters more than smoothness.
        
        Args:
            target: Target pose/joint dictionary
            pose_type: Type of pose ("head", "arm", "base", etc.)
            **kwargs: Additional SDK-specific parameters
            
        Raises:
            ValueError: If target is invalid or pose_type not supported
            RuntimeError: If robot is not connected or in error state
            
        Example:
            >>> driver.move_instant({"x": 0.1, "y": 0.0, "z": 0.2}, pose_type="head")
        """
        pass
    
    @abstractmethod
    def move_smooth(
        self,
        target: Dict[str, Any],
        duration: Optional[float] = None,
        pose_type: str = "head",
        method: str = "minjerk",
        **kwargs
    ) -> bool:
        """
        Smooth interpolated motion with configurable style.
        
        Uses interpolation (e.g., minjerk, ease) for fluid, non-threatening
        motion. Duration can be influenced by the "energy" config parameter.
        Method can be influenced by the "warmth" config parameter.
        
        Args:
            target: Target pose/joint dictionary
            duration: Optional duration in seconds. If None, computed from
                     energy level (higher energy = lower duration)
            pose_type: Type of pose ("head", "arm", "base", etc.)
            method: Interpolation method ("minjerk", "ease", "linear", etc.)
                    Can be influenced by warmth level (warm = minjerk/ease)
            **kwargs: Additional SDK-specific parameters
            
        Returns:
            True if motion command accepted, False otherwise
            
        Raises:
            ValueError: If target is invalid or pose_type not supported
            RuntimeError: If robot is not connected or in error state
            
        Example:
            >>> driver.move_smooth(
            ...     {"x": 0.1, "y": 0.0, "z": 0.2},
            ...     duration=1.0,
            ...     method="minjerk"
            ... )
        """
        pass
    
    @abstractmethod
    def move_to_pose(
        self,
        pose: Dict[str, Any],
        pose_type: str = "head",
        duration: Optional[float] = None,
        **kwargs
    ) -> bool:
        """
        Move robot to a target pose (legacy method, delegates to move_smooth).
        
        This method is kept for backward compatibility. New code should use
        move_smooth() or move_instant() directly.
        
        Args:
            pose: Pose dictionary (format depends on pose_type)
            pose_type: Type of pose ("head", "arm", "base", etc.)
            duration: Optional duration in seconds for the motion
            **kwargs: Additional SDK-specific parameters
            
        Returns:
            True if motion command accepted, False otherwise
            
        Raises:
            ValueError: If pose is invalid or pose_type not supported
            RuntimeError: If robot is not connected or in error state
        """
        # Default implementation delegates to move_smooth
        return self.move_smooth(pose, duration=duration, pose_type=pose_type, **kwargs)
    
    @abstractmethod
    def move_joints(
        self,
        joints: List[float],
        arm_id: Optional[str] = None,
        duration: Optional[float] = None,
        **kwargs
    ) -> bool:
        """
        Move robot joints to target angles.
        
        Args:
            joints: List of joint angles in radians
            arm_id: Optional arm identifier (for multi-arm robots)
            duration: Optional duration in seconds for the motion
            **kwargs: Additional SDK-specific parameters
            
        Returns:
            True if motion command accepted, False otherwise
            
        Raises:
            ValueError: If joints list length doesn't match robot
            RuntimeError: If robot is not connected
        """
        pass
    
    @abstractmethod
    def is_moving(self) -> bool:
        """
        Check if the robot is currently executing a motion.
        
        Returns:
            True if robot is moving, False otherwise
        """
        pass
    
    @abstractmethod
    def wait_for_motion_complete(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for current motion to complete.
        
        Args:
            timeout: Optional timeout in seconds. None = wait indefinitely
            
        Returns:
            True if motion completed, False if timeout
        """
        pass
    
    # --- Multimodal I/O (The Pulse) ---
    
    @abstractmethod
    def get_latest_frame(self) -> Optional[np.ndarray]:
        """
        Get the latest RGB frame from the robot's camera.
        
        Returns:
            NumPy array of shape (H, W, 3) with RGB values (uint8), or None
            if no camera or frame not available
            
        Raises:
            RuntimeError: If robot is not connected
        """
        pass
    
    @abstractmethod
    def play_audio(
        self,
        samples: np.ndarray,
        samplerate: int = 44100,
        **kwargs
    ) -> None:
        """
        Stream audio samples to robot speakers.
        
        Args:
            samples: NumPy array of audio samples (mono or stereo)
                    Shape: (n_samples,) for mono or (n_samples, n_channels) for stereo
                    Data type: float32 or int16
            samplerate: Sample rate in Hz (default: 44100)
            **kwargs: Additional audio parameters (channels, format, etc.)
            
        Raises:
            ValueError: If samples format is invalid
            RuntimeError: If robot is not connected or has no speakers
        """
        pass
    
    # --- Proprioception (State Feedback) ---
    
    @abstractmethod
    def get_proprioception(self) -> ProprioceptionState:
        """
        Gather current joint angles, IMU, and motor status.
        
        This method provides real-time proprioceptive feedback for VLA models.
        The returned state is fed into TaskPayload v2.5 multimodal envelope
        for cognitive processing.
        
        Returns:
            ProprioceptionState with current robot state
            
        Raises:
            RuntimeError: If robot is not connected
        """
        pass
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} state={self.state.value}>"


class BaseIoTDeviceDriver(ABC):
    """
    Abstract base class for IoT device drivers.
    
    Provides a unified interface for interacting with IoT devices (smart lights,
    switches, sensors, etc.) across different vendors and protocols.
    
    Design Notes:
    - Async-first for non-blocking device communication
    - Stateless design (no persistent connections required)
    - Error handling via exceptions
    - Supports both read (status) and write (commands) operations
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the IoT device driver.
        
        Args:
            config: Optional configuration dictionary. Vendor-specific keys allowed.
        """
        self.config = config or {}
    
    @abstractmethod
    async def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """
        Get the current status of an IoT device.
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            Dictionary containing device status data. Format is vendor-specific
            but should include at least:
            - "device_id": str
            - "status": dict with device-specific status fields
            
        Raises:
            ValueError: If device_id is invalid
            RuntimeError: If device communication fails
        """
        pass
    
    @abstractmethod
    async def send_commands(
        self,
        device_id: str,
        commands: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Send commands to an IoT device.
        
        Args:
            device_id: Unique device identifier
            commands: List of command dictionaries. Each command should have:
                - "code": str - Command code/identifier
                - "value": Any - Command value
                
        Returns:
            Dictionary containing command response. Should include:
            - "device_id": str
            - "commands": List of sent commands
            - Response data from device
            
        Raises:
            ValueError: If device_id or commands are invalid
            RuntimeError: If device communication fails
        """
        pass
    
    async def close(self) -> None:
        """
        Clean up resources (close connections, etc.).
        
        Default implementation does nothing. Override if driver maintains
        persistent connections or resources that need cleanup.
        """
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
