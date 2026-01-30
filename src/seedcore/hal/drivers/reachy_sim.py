"""
Reachy Simulation Driver
========================
Driver implementation for the RobotSim gRPC simulation server.

This driver wraps the gRPC simulation server and implements the BaseRobotDriver
interface, allowing the simulation to be used as a drop-in replacement for
physical hardware in the HAL layer.
"""

import os
import logging
import time
from typing import Dict, Any, Optional, List
import numpy as np

try:
    import grpc
    import sys
    import pathlib
    
    # Try to import protobuf generated code
    current_file = pathlib.Path(__file__)
    project_root = current_file.parent.parent.parent.parent.parent
    apps_mini_path = project_root / "apps" / "mini"
    
    if apps_mini_path.exists():
        sys.path.insert(0, str(apps_mini_path))
    
    import robot_sim_pb2  # type: ignore
    import robot_sim_pb2_grpc  # type: ignore
    GRPC_AVAILABLE = True
except ImportError as e:
    GRPC_AVAILABLE = False
    robot_sim_pb2 = None
    robot_sim_pb2_grpc = None
    grpc = None

from ..interfaces import (
    BaseRobotDriver,
    RobotState,
    RobotCapabilities,
    ProprioceptionState,
)

logger = logging.getLogger(__name__)


class ReachySimDriver(BaseRobotDriver):
    """
    Driver for RobotSim gRPC simulation server.
    
    Implements the BaseRobotDriver interface, making the simulation server
    compatible with the HAL layer. This allows simulation to be used as a
    drop-in replacement for physical hardware.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the simulation driver.
        
        Args:
            config: Configuration dictionary. Keys:
                - "energy": Energy level (0-100) affecting motion speed
                - "warmth": Warmth level (0-100) affecting motion style
                - "grpc_address": Optional gRPC server address (default: "localhost:50055")
        """
        super().__init__(config)
        if not GRPC_AVAILABLE:
            raise RuntimeError("gRPC dependencies not available. Install grpcio and protobuf.")
        
        # Read from config, then environment variable, then default (matches demo_simulator.py)
        self._grpc_address = (
            self.config.get("grpc_address") 
            or os.getenv("REACHY_SIM_ADDRESS") 
            or "localhost:50055"
        )
        self._channel: Optional[grpc.Channel] = None
        self._stub: Optional[robot_sim_pb2_grpc.RobotSimStub] = None
        self._current_state: Dict[str, Any] = {
            "head": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "roll": 0.0},
            "antennas": [0.0, 0.0],
            "body_yaw": 0.0,
        }

    def _initialize_capabilities(self) -> RobotCapabilities:
        """Define simulation capabilities (matches Reachy Mini)."""
        return RobotCapabilities(
            has_arms=False,
            has_head=True,
            has_base=False,
            has_camera=False,  # Simulation doesn't have camera
            has_microphone=False,  # Simulation doesn't have microphone
            supported_pose_types=["head", "antennas", "body_yaw"],
        )

    def _ensure_stub(self) -> robot_sim_pb2_grpc.RobotSimStub:
        """Ensure gRPC stub is initialized."""
        if self._stub is None:
            if self._channel is None:
                self._channel = grpc.insecure_channel(self._grpc_address)
            self._stub = robot_sim_pb2_grpc.RobotSimStub(self._channel)
        return self._stub

    def connect(self) -> bool:
        """Connect to the simulation server with retry logic."""
        import time
        
        max_retries = 10
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"connect: Attempt {attempt + 1}/{max_retries} to connect to {self._grpc_address}")
                self._ensure_stub()
                # Test connection by getting state
                state = self._stub.GetState(robot_sim_pb2.Empty())
                self._current_state = {
                    "head": dict(state.head),
                    "antennas": list(state.antennas),
                    "body_yaw": state.body_yaw,
                }
                self._state = RobotState.CONNECTED
                logger.info(f"✅ Connected to simulation server at {self._grpc_address} (attempt {attempt + 1})")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"connect: Connection attempt {attempt + 1} failed: {e}, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"❌ Failed to connect to simulation server after {max_retries} attempts: {e}", exc_info=True)
                    self._state = RobotState.ERROR
                    return False
        
        return False

    def disconnect(self) -> None:
        """Disconnect from the simulation server."""
        if self._channel:
            try:
                self._channel.close()
            except Exception as e:
                logger.warning(f"Error closing gRPC channel: {e}")
            finally:
                self._channel = None
                self._stub = None
        self._state = RobotState.DISCONNECTED
        logger.info("Disconnected from simulation server")

    def emergency_stop(self) -> None:
        """Immediate stop (sets all values to zero)."""
        try:
            stub = self._ensure_stub()
            cmd = robot_sim_pb2.MotionCommand(
                head={"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "roll": 0.0},
                antennas=[0.0, 0.0],
                body_yaw=0.0,
                duration=0.0,
            )
            stub.Goto(cmd)
            self._state = RobotState.EMERGENCY_STOP
            logger.warning("SAFETY: Emergency stop triggered.")
        except Exception as e:
            logger.error(f"Emergency stop failed: {e}")
            self._state = RobotState.ERROR

    def get_current_pose(self, pose_type: str = "head") -> Dict[str, Any]:
        """Get current pose from simulation."""
        # Allow CONNECTED and MOVING states
        if self._state not in (RobotState.CONNECTED, RobotState.MOVING):
            raise RuntimeError(f"Not connected to simulation (state: {self._state.value})")
        
        if pose_type == "head":
            return self._current_state.get("head", {})
        elif pose_type == "antennas":
            antennas = self._current_state.get("antennas", [0.0, 0.0])
            return {"left": antennas[0], "right": antennas[1]}
        elif pose_type == "body":
            return {"yaw": self._current_state.get("body_yaw", 0.0)}
        else:
            raise ValueError(f"Unsupported pose_type: {pose_type}")

    def _get_duration(self, base_s: float = 1.0) -> float:
        """Maps 'Energy' slider to duration. Energy 100 = 0.3s (Hyper)."""
        energy = self.config.get("energy", 50)
        multiplier = 2.0 - (energy / 100.0) * 1.7
        return base_s * multiplier

    def _get_method(self) -> str:
        """Maps 'Warmth' slider to interpolation method."""
        warmth = self.config.get("warmth", 50)
        if warmth >= 75:
            return "minjerk"
        if warmth >= 40:
            return "ease"
        return "linear"

    def move_instant(
        self,
        target: Dict[str, Any],
        pose_type: str = "head",
        **kwargs
    ) -> None:
        """High-frequency motion control (uses minimal duration)."""
        if self._state not in (RobotState.CONNECTED, RobotState.MOVING):
            raise RuntimeError(f"Not connected to simulation (state: {self._state.value})")
        
        try:
            stub = self._ensure_stub()
            cmd = robot_sim_pb2.MotionCommand(duration=0.1)  # Minimal duration for instant
            
            # Extract components from target dict
            if "head" in target:
                cmd.head.update(target["head"])
            if "antennas" in target:
                cmd.antennas.extend(target["antennas"])
            if "body_yaw" in target:
                cmd.body_yaw = target["body_yaw"]
            
            logger.debug(f"move_instant: sending command to simulation server: {target}")
            ack = stub.Goto(cmd)
            if ack.ok:
                self._state = RobotState.MOVING
                # Update local state immediately
                if "head" in target:
                    self._current_state["head"].update(target["head"])
                if "antennas" in target:
                    self._current_state["antennas"] = list(target["antennas"])
                if "body_yaw" in target:
                    self._current_state["body_yaw"] = target["body_yaw"]
                # For instant moves, transition back to CONNECTED immediately
                self._state = RobotState.CONNECTED
                logger.debug(f"move_instant: completed, state={self._current_state}")
            else:
                logger.warning("move_instant: simulation server returned ok=False")
                self._state = RobotState.ERROR
        except Exception as e:
            logger.error(f"Error in instant move: {e}", exc_info=True)
            self._state = RobotState.ERROR
            raise

    def move_smooth(
        self,
        target: Dict[str, Any],
        duration: Optional[float] = None,
        pose_type: str = "head",
        method: str = "minjerk",
        **kwargs
    ) -> bool:
        """Smooth interpolated motion."""
        # Allow MOVING state - can queue new commands
        if self._state not in (RobotState.CONNECTED, RobotState.MOVING):
            logger.warning(f"move_smooth: invalid state {self._state.value}")
            return False
        
        target_duration = duration if duration else self._get_duration()
        
        try:
            stub = self._ensure_stub()
            cmd = robot_sim_pb2.MotionCommand(duration=target_duration)
            
            # Extract components from target dict
            if "head" in target:
                cmd.head.update(target["head"])
            if "antennas" in target:
                cmd.antennas.extend(target["antennas"])
            if "body_yaw" in target:
                cmd.body_yaw = target["body_yaw"]
            
            logger.info(f"move_smooth: sending command (duration={target_duration:.2f}s): {target}")
            ack = stub.Goto(cmd)  # This blocks for duration, then returns
            if ack.ok:
                # Update local state
                if "head" in target:
                    self._current_state["head"].update(target["head"])
                if "antennas" in target:
                    self._current_state["antennas"] = list(target["antennas"])
                if "body_yaw" in target:
                    self._current_state["body_yaw"] = target["body_yaw"]
                # Motion completed (gRPC call returned), transition back to CONNECTED
                self._state = RobotState.CONNECTED
                logger.info(f"move_smooth: completed, new state={self._current_state}")
                return True
            else:
                logger.warning("move_smooth: simulation server returned ok=False")
                return False
        except Exception as e:
            logger.error(f"Motion error: {e}", exc_info=True)
            self._state = RobotState.ERROR
            return False

    def move_to_pose(
        self,
        pose: Dict[str, Any],
        pose_type: str = "head",
        duration: Optional[float] = None,
        **kwargs
    ) -> bool:
        """Move to target pose (delegates to move_smooth)."""
        return self.move_smooth(pose, duration=duration, pose_type=pose_type, **kwargs)

    def move_joints(
        self,
        joints: List[float],
        arm_id: Optional[str] = None,
        duration: Optional[float] = None,
        **kwargs
    ) -> bool:
        """Move joints - not applicable for Reachy Mini simulation."""
        raise NotImplementedError("Reachy Mini simulation has no articulated arms")

    def is_moving(self) -> bool:
        """Check if robot is moving."""
        return self._state == RobotState.MOVING

    def wait_for_motion_complete(self, timeout: Optional[float] = None) -> bool:
        """Wait for motion to complete."""
        if not self.is_moving():
            return True
        
        # Simple timeout-based wait
        if timeout:
            time.sleep(min(timeout, 0.1))
        else:
            time.sleep(0.1)
        
        # Assume motion completes quickly
        self._state = RobotState.CONNECTED
        return True

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get latest frame - simulation doesn't have camera."""
        return None

    def play_audio(
        self,
        samples: np.ndarray,
        samplerate: int = 44100,
        **kwargs
    ) -> None:
        """Play audio - simulation doesn't have speakers."""
        logger.debug(f"Audio playback requested (simulation doesn't support audio)")

    def get_proprioception(self) -> ProprioceptionState:
        """Get current robot state from simulation."""
        # Allow CONNECTED and MOVING states
        if self._state not in (RobotState.CONNECTED, RobotState.MOVING):
            raise RuntimeError(f"Not connected to simulation (state: {self._state.value})")
        
        try:
            stub = self._ensure_stub()
            state = stub.GetState(robot_sim_pb2.Empty())
            
            # Update local state cache
            self._current_state = {
                "head": dict(state.head),
                "antennas": list(state.antennas),
                "body_yaw": state.body_yaw,
            }
            
            # Convert to ProprioceptionState
            head_pose = dict(state.head)
            is_moving = self.is_moving()
            logger.debug(f"get_proprioception: Retrieved state, is_moving={is_moving}")
            return ProprioceptionState(
                joint_positions={},  # Simulation doesn't expose joint positions
                ee_pose=head_pose,
                imu_data={},  # Simulation doesn't expose IMU
                is_moving=is_moving,
                timestamp=time.time(),
            )
        except Exception as e:
            logger.error(f"Error getting proprioception: {e}", exc_info=True)
            raise RuntimeError(f"Failed to get state: {e}")

    def get_state(self) -> Dict[str, Any]:
        """
        Get current robot state (convenience method for HAL service).
        
        Returns:
            Dictionary with head, antennas, and body_yaw
        """
        # Allow CONNECTED and MOVING states
        if self._state not in (RobotState.CONNECTED, RobotState.MOVING):
            raise RuntimeError(f"Not connected to simulation (state: {self._state.value})")
        
        try:
            stub = self._ensure_stub()
            state = stub.GetState(robot_sim_pb2.Empty())
            
            # Update local state cache
            self._current_state = {
                "head": dict(state.head),
                "antennas": list(state.antennas),
                "body_yaw": state.body_yaw,
            }
            
            logger.debug(f"get_state: Retrieved state from simulation: {self._current_state}")
            return self._current_state
        except Exception as e:
            logger.error(f"Error getting state: {e}", exc_info=True)
            raise RuntimeError(f"Failed to get state: {e}")
