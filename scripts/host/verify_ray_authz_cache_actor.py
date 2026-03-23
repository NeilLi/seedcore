#!/usr/bin/env python3
"""Experimental verification for a Ray-backed authz graph cache actor."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import ray  # pyright: ignore[reportMissingImports]

from seedcore.ops.pkg.authz_graph import AuthzGraphCompiler, AuthzGraphProjector
from seedcore.ops.pkg.authz_graph.ray_cache import AuthzGraphCacheActor


def _fetch_json(url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _ray_address() -> str:
    return os.getenv("RAY_ADDRESS", "ray://127.0.0.1:23001")


def _ray_namespace() -> str:
    return (os.getenv("SEEDCORE_NS") or os.getenv("RAY_NAMESPACE") or "seedcore-dev").strip() or "seedcore-dev"


def _build_fixture_snapshot():
    canonical_resource_uri = "seedcore://zones/vault-a/assets/asset-1"
    snapshot = AuthzGraphProjector().project_snapshot(
        snapshot_ref="authz-ray-fixture@host",
        snapshot_id=999,
        snapshot_version="authz-ray-fixture:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 999,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
            {
                "id": "fact-zone",
                "snapshot_id": 999,
                "namespace": "authz",
                "subject": canonical_resource_uri,
                "predicate": "locatedInZone",
                "object_data": {"zone": "vault-a"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 999,
                "namespace": "authz",
                "subject": "role:ROBOT_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MUTATE",
                    "resource": canonical_resource_uri,
                    "zones": ["vault-a"],
                },
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
        ],
    )
    return canonical_resource_uri, snapshot, AuthzGraphCompiler().compile(snapshot)


def _compare_active_snapshot(actor) -> Dict[str, Any]:
    pkg_status = _fetch_json("http://127.0.0.1:8002/api/v1/pkg/status")
    status = ray.get(
        actor.load_snapshot.remote(
            snapshot_id=int(pkg_status["snapshot_id"]),
            snapshot_version=str(pkg_status["active_version"]),
            snapshot_ref=f"authz_graph@{pkg_status['active_version']}",
        )
    )
    actor_decision = ray.get(
        actor.can_access.remote(
            {
                "principal_ref": "principal:agent-1",
                "operation": "MUTATE",
                "resource_ref": "seedcore://zones/vault-a/assets/nonexistent",
                "zone_ref": "zone:vault-a",
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    return {
        "pkg_status": {
            "snapshot_id": pkg_status["snapshot_id"],
            "active_version": pkg_status["active_version"],
            "authz_graph_ready": pkg_status["authz_graph_ready"],
        },
        "actor_status": status,
        "actor_decision": actor_decision,
    }


def _compare_fixture_snapshot(actor) -> Dict[str, Any]:
    canonical_resource_uri, snapshot, compiled = _build_fixture_snapshot()
    status = ray.get(
        actor.load_fixture.remote(
            snapshot_ref=snapshot.snapshot_ref,
            snapshot_id=snapshot.snapshot_id,
            snapshot_version=snapshot.snapshot_version,
            facts=[
                {
                    "id": "fact-role",
                    "snapshot_id": 999,
                    "namespace": "authz",
                    "subject": "agent-1",
                    "predicate": "hasRole",
                    "object_data": {"role": "ROBOT_OPERATOR"},
                    "valid_from": "2099-03-20T11:50:00+00:00",
                    "valid_to": "2099-03-20T12:20:00+00:00",
                },
                {
                    "id": "fact-zone",
                    "snapshot_id": 999,
                    "namespace": "authz",
                    "subject": canonical_resource_uri,
                    "predicate": "locatedInZone",
                    "object_data": {"zone": "vault-a"},
                },
                {
                    "id": "fact-allow",
                    "snapshot_id": 999,
                    "namespace": "authz",
                    "subject": "role:ROBOT_OPERATOR",
                    "predicate": "allowedOperation",
                    "object_data": {
                        "operation": "MUTATE",
                        "resource": canonical_resource_uri,
                        "zones": ["vault-a"],
                    },
                    "valid_from": "2099-03-20T11:50:00+00:00",
                    "valid_to": "2099-03-20T12:20:00+00:00",
                },
            ],
        )
    )
    payload = {
        "principal_ref": "principal:agent-1",
        "operation": "MUTATE",
        "resource_ref": canonical_resource_uri,
        "zone_ref": "zone:vault-a",
        "at": "2099-03-20T12:00:00+00:00",
    }
    local_match = compiled.can_access(
        principal_ref=payload["principal_ref"],
        operation=payload["operation"],
        resource_ref=payload["resource_ref"],
        zone_ref=payload["zone_ref"],
        at=datetime.fromisoformat(str(payload["at"]).replace("Z", "+00:00")),
    )
    actor_match = ray.get(actor.can_access.remote(payload))
    local_serialized = {
        "allowed": local_match.allowed,
        "matched_subjects": list(local_match.matched_subjects),
        "matched_permissions_count": len(local_match.matched_permissions),
        "deny_permissions_count": len(local_match.deny_permissions),
        "break_glass_permissions_count": len(local_match.break_glass_permissions),
        "break_glass_required": local_match.break_glass_required,
        "break_glass_used": local_match.break_glass_used,
        "reason": local_match.reason,
    }
    _assert(actor_match == local_serialized, "Ray actor decision drifted from local compiled index")

    latencies_ms = []
    for _ in range(10):
        start = time.perf_counter()
        ray.get(actor.can_access.remote(payload))
        latencies_ms.append(round((time.perf_counter() - start) * 1000, 3))

    return {
        "actor_status": status,
        "local_decision": local_serialized,
        "actor_decision": actor_match,
        "latency_ms": {
            "runs": len(latencies_ms),
            "min": min(latencies_ms),
            "max": max(latencies_ms),
            "avg": round(sum(latencies_ms) / len(latencies_ms), 3),
        },
    }


def main() -> int:
    ray.init(address=_ray_address(), namespace=_ray_namespace(), ignore_reinit_error=True, log_to_driver=False)
    actor = AuthzGraphCacheActor.remote()
    try:
        active = _compare_active_snapshot(actor)
        fixture = _compare_fixture_snapshot(actor)

        _assert(active["pkg_status"]["authz_graph_ready"] is True, "Active PKG authz graph is not ready")
        _assert(active["actor_status"]["loaded"] is True, "Actor failed to load active snapshot")
        _assert(
            active["actor_decision"]["reason"] in {"no_matching_permission", "explicit_deny", "break_glass_required"},
            "Unexpected active-snapshot decision shape",
        )
        active_edges = int(active["actor_status"].get("graph_edges_count") or 0)
        active_nodes = int(active["actor_status"].get("graph_nodes_count") or 0)
        _assert(fixture["actor_status"]["graph_edges_count"] > 0, "Fixture graph did not produce any edges")
        _assert(fixture["actor_decision"]["allowed"] is True, "Fixture actor path should allow the sample traversal")

        verified_today = [
            "Ray actor can own a compiled authz index in memory",
            "Actor decision parity matches the local compiled graph for a non-empty fixture",
            "Active snapshot can be loaded into the actor from the current local runtime",
        ]
        not_yet_verified = [
            "No production PDP request path is routed through the actor yet",
        ]
        if active_edges > 0 and active_nodes > 0:
            verified_today.append(
                f"Active snapshot projects a non-empty authz graph in Ray memory ({active_nodes} nodes / {active_edges} edges)"
            )
        else:
            not_yet_verified.append(
                "Current active snapshot has zero authz graph edges, so the live graph-cache demo is structurally limited"
            )

        report = {
            "ray_address": _ray_address(),
            "namespace": _ray_namespace(),
            "active_snapshot_check": active,
            "fixture_cache_check": fixture,
            "conclusion": {
                "workable_locally": True,
                "verified_today": verified_today,
                "not_yet_verified": not_yet_verified,
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        ray.kill(actor, no_restart=True)


if __name__ == "__main__":
    raise SystemExit(main())
