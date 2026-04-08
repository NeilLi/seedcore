"""Deprecated import path; use ``seedcore.memory.legacy.cost_vq``."""

from warnings import warn

warn(
    "Importing seedcore.memory.cost_vq is deprecated; use seedcore.memory.legacy",
    DeprecationWarning,
    stacklevel=2,
)

from .legacy.cost_vq import *  # noqa: F403
