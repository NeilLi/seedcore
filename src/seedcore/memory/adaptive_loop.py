"""Deprecated import path; use ``seedcore.memory.legacy``."""

from warnings import warn

warn(
    "Importing seedcore.memory.adaptive_loop is deprecated; use seedcore.memory.legacy",
    DeprecationWarning,
    stacklevel=2,
)

from .legacy.adaptive_loop import *  # noqa: F403
