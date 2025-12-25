# warmup_policy.py
from enum import Enum
import os

class WarmupMode(str, Enum):
    DISABLED = "disabled"      # never warm up automatically
    LAZY = "lazy"              # warm up on first real request
    BACKGROUND = "background"  # warm up after startup (async)
    EAGER = "eager"            # block startup until warm

def get_warmup_mode() -> WarmupMode:
    """
    Get warmup mode from environment variable.
    """
    return WarmupMode(
        os.getenv("ML_WARMUP_MODE", "lazy").lower()
    )
