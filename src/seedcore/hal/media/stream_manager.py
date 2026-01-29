"""
Stream Manager
==============

Manages camera and audio streams for robots using GStreamer/WebRTC.

Handles:
- GStreamer pipeline creation and management
- WebRTC peer connections for real-time streaming
- Stream lifecycle (start/stop/restart)
- Integration with TaskPayload v2.5 multimodal envelope
"""

import logging
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class StreamType(Enum):
    """Types of media streams."""
    CAMERA = "camera"
    AUDIO = "audio"
    BOTH = "both"


@dataclass
class StreamConfig:
    """
    Configuration for a media stream.
    
    Attributes:
        stream_id: Unique identifier for this stream
        stream_type: Type of stream (camera, audio, both)
        width: Video width in pixels (for camera streams)
        height: Video height in pixels (for camera streams)
        fps: Frames per second
        codec: Video/audio codec (e.g., "h264", "vp8", "opus")
        bitrate: Bitrate in kbps
        port: UDP/TCP port for streaming
        webrtc_enabled: Whether to use WebRTC (vs raw UDP)
    """
    stream_id: str
    stream_type: StreamType = StreamType.CAMERA
    width: int = 640
    height: int = 480
    fps: int = 30
    codec: str = "h264"
    bitrate: int = 2000
    port: Optional[int] = None
    webrtc_enabled: bool = False


class StreamManager:
    """
    Manages media streams for robot hardware.
    
    Provides GStreamer/WebRTC-based streaming for camera and audio feeds.
    Streams are exposed via URLs that can be referenced in TaskPayload v2.5
    multimodal envelopes.
    
    Design Notes:
    - Streams are independent of robot motion control
    - Multiple streams can be active simultaneously
    - Stream lifecycle is managed explicitly (start/stop)
    - Stream URLs are compatible with TaskPayload v2.5 multimodal.media_uri
    """
    
    def __init__(self, robot_driver: Optional[Any] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize stream manager.
        
        Args:
            robot_driver: Optional robot driver instance (for SDK-specific stream access)
            config: Optional configuration dictionary
        """
        self.robot_driver = robot_driver
        self.config = config or {}
        self._active_streams: Dict[str, StreamConfig] = {}
        self._gstreamer_pipelines: Dict[str, Any] = {}  # Placeholder for GStreamer pipeline objects
    
    def start_camera_stream(
        self,
        stream_id: str = "camera_0",
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        codec: str = "h264",
        port: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Start a camera stream.
        
        Args:
            stream_id: Unique identifier for this stream
            width: Video width in pixels
            height: Video height in pixels
            fps: Frames per second
            codec: Video codec ("h264", "vp8", "vp9")
            port: UDP port (auto-assigned if None)
            **kwargs: Additional stream configuration
            
        Returns:
            Stream URL (e.g., "udp://127.0.0.1:5000" or WebRTC SDP URL)
            
        Raises:
            RuntimeError: If stream cannot be started
        """
        if stream_id in self._active_streams:
            logger.warning(f"Stream {stream_id} already active, stopping first")
            self.stop_stream(stream_id)
        
        config = StreamConfig(
            stream_id=stream_id,
            stream_type=StreamType.CAMERA,
            width=width,
            height=height,
            fps=fps,
            codec=codec,
            port=port or self._get_next_port(),
            **kwargs
        )
        
        # TODO: Implement actual GStreamer pipeline creation
        # For now, return a placeholder URL
        logger.info(f"Starting camera stream {stream_id} (placeholder)")
        
        self._active_streams[stream_id] = config
        stream_url = f"udp://127.0.0.1:{config.port}"
        
        return stream_url
    
    def start_audio_stream(
        self,
        stream_id: str = "audio_0",
        codec: str = "opus",
        bitrate: int = 128,
        port: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Start an audio stream.
        
        Args:
            stream_id: Unique identifier for this stream
            codec: Audio codec ("opus", "pcm")
            bitrate: Bitrate in kbps
            port: UDP port (auto-assigned if None)
            **kwargs: Additional stream configuration
            
        Returns:
            Stream URL
            
        Raises:
            RuntimeError: If stream cannot be started
        """
        if stream_id in self._active_streams:
            logger.warning(f"Stream {stream_id} already active, stopping first")
            self.stop_stream(stream_id)
        
        config = StreamConfig(
            stream_id=stream_id,
            stream_type=StreamType.AUDIO,
            codec=codec,
            bitrate=bitrate,
            port=port or self._get_next_port(),
            **kwargs
        )
        
        logger.info(f"Starting audio stream {stream_id} (placeholder)")
        
        self._active_streams[stream_id] = config
        stream_url = f"udp://127.0.0.1:{config.port}"
        
        return stream_url
    
    def stop_stream(self, stream_id: str) -> bool:
        """
        Stop a stream.
        
        Args:
            stream_id: Stream identifier
            
        Returns:
            True if stream was stopped, False if not found
        """
        if stream_id not in self._active_streams:
            logger.warning(f"Stream {stream_id} not found")
            return False
        
        config = self._active_streams.pop(stream_id)
        
        # TODO: Stop GStreamer pipeline
        logger.info(f"Stopped stream {stream_id}")
        
        return True
    
    def stop_all_streams(self) -> None:
        """Stop all active streams."""
        stream_ids = list(self._active_streams.keys())
        for stream_id in stream_ids:
            self.stop_stream(stream_id)
    
    def get_stream_url(self, stream_id: str) -> Optional[str]:
        """
        Get the URL for an active stream.
        
        Args:
            stream_id: Stream identifier
            
        Returns:
            Stream URL, or None if stream not found
        """
        config = self._active_streams.get(stream_id)
        if not config:
            return None
        
        return f"udp://127.0.0.1:{config.port}"
    
    def list_active_streams(self) -> List[str]:
        """List all active stream IDs."""
        return list(self._active_streams.keys())
    
    def _get_next_port(self) -> int:
        """Get next available UDP port."""
        # Simple port allocation (in production, use proper port management)
        base_port = 5000
        used_ports = {cfg.port for cfg in self._active_streams.values() if cfg.port}
        
        port = base_port
        while port in used_ports:
            port += 1
        
        return port
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop all streams."""
        self.stop_all_streams()
