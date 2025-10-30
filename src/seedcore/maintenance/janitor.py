#!/usr/bin/env python3
"""
SeedCore Janitor actor.

Purpose:
- Find and reap dead Ray actors in a given namespace.
- Expose lightweight health/status info.
- Run detached so OrganismManager can call it periodically.

Usage pattern:
    Janitor.options(
        name="seedcore_janitor",
        namespace="<your-namespace>",
        lifetime="detached",
        get_if_exists=True,
        num_cpus=0,
    ).remote("<your-namespace>")
"""

import logging
import ray
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@ray.remote(
    name="seedcore_janitor",
    lifetime="detached",
    num_cpus=0,
)
class Janitor:
    """Cluster-side maintenance actor."""

    def __init__(self, cluster_namespace: Optional[str] = None):
        """
        cluster_namespace:
            If provided, we will only act on actors in this namespace.
            If None, we'll inspect all namespaces (not recommended in shared clusters).
        """
        self.cluster_namespace = cluster_namespace
        logger.info(
            "🚀 SeedCore Janitor initialized (ns=%s)",
            self.cluster_namespace or "<ANY>",
        )

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _safe_list_actors(self) -> List[Dict[str, Any]]:
        """Return Ray actor state dicts. Isolated for safer error handling."""
        try:
            from ray.util.state import list_actors
            return list_actors()  # Ray returns a list[dict]
        except Exception as e:
            logger.error("Janitor: failed to list actors: %s", e)
            return []

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def list_dead_named(
        self,
        prefix: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List dead named actors filtered by:
            - prefix (actor name startswith)
            - namespace (actor namespace equals)
        Returns a list of {name, namespace, actor_id, state}.
        """
        ns_filter = namespace or self.cluster_namespace
        out: List[Dict[str, Any]] = []

        try:
            actors = self._safe_list_actors()
            for a in actors:
                name = a.get("name")
                state = a.get("state")
                ns = a.get("namespace") or a.get("actor_namespace")

                # Must be named, must be DEAD
                if not (name and state == "DEAD"):
                    continue

                # Optional filter: namespace
                if ns_filter and ns != ns_filter:
                    continue

                # Optional filter: prefix
                if prefix and not name.startswith(prefix):
                    continue

                out.append(
                    {
                        "name": name,
                        "namespace": ns,
                        "actor_id": a.get("actorId")
                        or a.get("actor_id"),  # Ray version differences
                        "state": state,
                    }
                )

            logger.info(
                "Janitor list_dead_named: found %d dead actors (prefix=%r ns=%r)",
                len(out),
                prefix,
                ns_filter,
            )
            return out

        except Exception as e:
            logger.error("Janitor list_dead_named failed: %s", e)
            return []

    def reap(
        self,
        prefix: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Attempt to clean up dead actors.
        Strategy:
            1. Find dead named actors (respecting prefix/ns).
            2. Try to kill them by name/namespace (handle-based kill).
            3. If that fails, we log and continue. We do NOT crash.

        Returns:
            {
                "reaped": [...names...],
                "count": <int>,
                "errors": <int>
            }
        """
        ns_target = namespace or self.cluster_namespace
        reaped: List[str] = []
        errors = 0

        try:
            dead_list = self.list_dead_named(prefix=prefix, namespace=ns_target)

            for item in dead_list:
                aname = item.get("name")
                ans = item.get("namespace")

                # Only try to kill in our namespace (safety guard)
                if ns_target and ans != ns_target:
                    continue

                if not aname:
                    continue

                # Try kill by handle in that namespace
                try:
                    if ns_target:
                        handle = ray.get_actor(aname, namespace=ns_target)
                    else:
                        # fallback: best effort without namespace filter
                        handle = ray.get_actor(aname)

                    # no_restart=True makes sure Ray doesn't auto-respawn it
                    ray.kill(handle, no_restart=True)
                    reaped.append(aname)
                    logger.info(
                        "Janitor reap: killed actor by handle: %s (ns=%s)",
                        aname,
                        ns_target,
                    )
                except Exception as kill_err:
                    errors += 1
                    logger.debug(
                        "Janitor reap: failed to kill actor %r in ns=%r: %s",
                        aname,
                        ns_target,
                        kill_err,
                    )
                    continue

            result = {
                "reaped": reaped,
                "count": len(reaped),
                "errors": errors,
                "namespace": ns_target,
            }
            logger.info(
                "Janitor reap complete: %d reaped, %d errors (ns=%s)",
                result["count"],
                result["errors"],
                ns_target,
            )
            return result

        except Exception as outer_e:
            # Top-level guard: never let janitor crash caller
            logger.error("Janitor reap fatal error: %s", outer_e)
            return {
                "reaped": reaped,
                "count": len(reaped),
                "errors": errors + 1,
                "namespace": ns_target,
                "fatal": str(outer_e),
            }

    def ping(self) -> str:
        """Simple ping for health checks."""
        return "ok"

    def status(self) -> Dict[str, Any]:
        """
        Return summary of cluster actor state. This is read-only, no mutation.
        {
            "status": "healthy" | "error",
            "namespace": "...",
            "total_actors": N,
            "dead_actors": N,
            "alive_actors": N
        }
        """
        try:
            actors = self._safe_list_actors()
            total = len(actors)
            dead = 0
            for a in actors:
                if a.get("state") == "DEAD":
                    # Only count as "ours" if namespace matches (if we care)
                    ns = a.get("namespace") or a.get("actor_namespace")
                    if self.cluster_namespace and ns != self.cluster_namespace:
                        continue
                    dead += 1

            return {
                "status": "healthy",
                "namespace": self.cluster_namespace,
                "total_actors": total,
                "dead_actors": dead,
                "alive_actors": total - dead,
            }

        except Exception as e:
            return {
                "status": "error",
                "namespace": self.cluster_namespace,
                "error": str(e),
            }
