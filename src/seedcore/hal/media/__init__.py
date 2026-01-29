"""
HAL Media Module
================

Handles camera and audio streams for multimodal robot interactions.

This module provides:
- GStreamer pipeline management for video streams
- WebRTC support for real-time audio/video
- Integration with TaskPayload v2.5 multimodal envelope
- Stream lifecycle management (start/stop/restart)

Architecture:
-------------
The media module bridges robot hardware streams (camera, microphone) with
SeedCore's multimodal task processing. Streams are managed independently
from robot motion control, allowing concurrent perception and action.

Usage:
------
```python
from seedcore.hal.media import StreamManager

# Create stream manager for a robot
manager = StreamManager(robot_driver=driver)

# Start camera stream
stream_url = manager.start_camera_stream(stream_id="camera_0")

# Stream URL can be used in TaskPayload multimodal envelope
task.params["multimodal"] = {
    "modality": "vision",
    "media_uri": stream_url,
    "camera_id": "camera_0"
}
```
"""

from .stream_manager import StreamManager, StreamType, StreamConfig

__all__ = [
    "StreamManager",
    "StreamType",
    "StreamConfig",
]
