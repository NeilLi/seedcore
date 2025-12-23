#!/usr/bin/env python
# seedcore/tools/base.py

from __future__ import annotations

from typing import Any, Dict, Optional
import time
import logging

from seedcore.tools.manager import ToolError

logger = logging.getLogger(__name__)


class ToolBase:
    """
    Base class for SeedCore internal tools.

    This class standardizes:
    - Execution lifecycle
    - Error normalization
    - Timing & logging
    - Optional learning reflection

    Concrete tools should implement:
        - name (class attribute)
        - description (class attribute, optional)
        - async run(...)
        - schema() (can be inherited)
    """

    #: Unique tool name (must be overridden)
    name: str = ""

    #: Optional human-readable description
    description: str = ""

    # ------------------------------------------------------------------
    # Core execution wrapper (called by ToolManager)
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> Any:
        """
        ToolManager entrypoint.

        DO NOT override this unless you know what you're doing.
        Override `run()` instead.
        """
        if not self.name:
            raise ToolError("<unknown>", "tool_name_not_defined")

        start = time.perf_counter()

        try:
            result = await self.run(**kwargs)
            return result

        except ToolError:
            # Already normalized
            raise

        except Exception as exc:
            logger.error(
                "❌ Tool '%s' execution failed: %s",
                self.name,
                exc,
                exc_info=True,
            )
            raise ToolError(self.name, str(exc), exc)

        finally:
            elapsed = time.perf_counter() - start
            logger.debug(
                "🔧 Tool '%s' executed in %.3fs",
                self.name,
                elapsed,
            )

    # ------------------------------------------------------------------
    # To be implemented by concrete tools
    # ------------------------------------------------------------------

    async def run(self, **kwargs: Any) -> Any:
        """
        Tool logic implementation.

        Must be overridden by subclasses.
        """
        raise NotImplementedError("Tool must implement run()")

    # ------------------------------------------------------------------
    # Schema & introspection
    # ------------------------------------------------------------------

    def schema(self) -> Dict[str, Any]:
        """
        Return tool schema used by ToolManager, Router, and LLM planning.

        Default implementation expects:
            - self.name
            - self.description
        """
        if not self.name:
            raise ValueError("Tool schema requires 'name'")

        return {
            "name": self.name,
            "description": self.description or "",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        }

    # ------------------------------------------------------------------
    # Optional: learning / reflection hook
    # ------------------------------------------------------------------

    def reflection(self, result: Any) -> Optional[Dict[str, Any]]:
        """
        Optional learning signal emitted after execution.

        Example return:
            { "skill": "planning", "delta": +0.02 }

        ToolManager may consume this in future iterations.
        """
        return None
