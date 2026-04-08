"""Deprecated import path; use ``seedcore.memory.legacy.system``."""

from warnings import warn

warn(
    "Importing seedcore.memory.system is deprecated; use seedcore.memory.legacy",
    DeprecationWarning,
    stacklevel=2,
)

from .legacy.system import *  # noqa: F403
