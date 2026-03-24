#!/usr/bin/env python3
"""Verify the staged authz-graph RFC implementation against local SeedCore runtime."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("RAY_ADDRESS", "ray://127.0.0.1:23001")
os.environ.setdefault("RAY_NAMESPACE", "seedcore-local")
os.environ.setdefault("SEEDCORE_NS", os.environ["RAY_NAMESPACE"])

from seedcore.coordinator.core.governance import (
    _compiled_authz_shard_key,
    evaluate_intent,
)
from seedcore.models.action_intent import ActionIntent
from seedcore.ops.pkg.authz_graph import (
    AuthzGraphCompiler,
    AuthzGraphManager,
    AuthzGraphProjectionService,
    AuthzGraphProjector,
)
from seedcore.ops.pkg.authz_graph.ray_cache import (
    _authz_graph_cache_actor_name,
    evaluate_authz_with_ray_cache,
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _api_url(path: str) -> str:
    base = os.getenv("SEEDCORE_API_URL", "http://127.0.0.1:8002").rstrip("/")
    return f"{base}{path}"


def _base_payload() -> dict[str, Any]:
    return {
        "task_id": "task-phase-check",
        "type": "action",
        "params": {
            "interaction": {"assigned_agent_id": "agent-1"},
            "resource": {"asset_id": "asset-1"},
            "intent": "transport",
            "governance": {
                "action_intent": {
                    "intent_id": "intent-phase-check",
                    "timestamp": "2099-03-20T12:00:00+00:00",
                    "valid_until": "2099-03-20T12:10:00+00:00",
                    "principal": {
                        "agent_id": "agent-1",
                        "role_profile": "ROBOT_OPERATOR",
                        "session_token": "sess-1",
                    },
                    "action": {
                        "type": "MOVE",
                        "parameters": {},
                        "security_contract": {"hash": "h-1", "version": "snapshot:1"},
                    },
                    "resource": {
                        "asset_id": "asset-1",
                        "resource_uri": "seedcore://zones/vault-a/assets/asset-1",
                        "target_zone": "vault-a",
                        "provenance_hash": "prov-1",
                    },
                }
            },
        },
    }


class _FakePKGClient:
    def __init__(
        self,
        *,
        snapshot_id: int,
        version: str,
        facts: list[dict[str, Any]],
        graph_manifests: list[dict[str, Any]] | None = None,
    ) -> None:
        self.snapshot = SimpleNamespace(
            id=snapshot_id,
            version=version,
            graph_manifests=list(graph_manifests or []),
        )
        self.facts = list(facts)

    async def get_active_governed_facts(self, **kwargs: Any) -> list[dict[str, Any]]:
        snapshot_id = kwargs.get("snapshot_id")
        if snapshot_id is not None and snapshot_id != self.snapshot.id:
            return []
        return list(self.facts)

    async def get_snapshot_by_version(self, version: str) -> Any:
        if version == self.snapshot.version:
            return self.snapshot
        return None

    async def get_snapshot_by_id(self, snapshot_id: int) -> Any:
        if snapshot_id == self.snapshot.id:
            return self.snapshot
        return None


def _serialize_snapshot(snapshot: Any) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(node.kind.value), node.ref) for node in snapshot.nodes))


def _serialize_edges(snapshot: Any) -> tuple[tuple[str, str, str], ...]:
    return tuple(sorted((edge.src, edge.dst, str(edge.kind.value)) for edge in snapshot.edges))


async def _phase0_checks() -> list[CheckResult]:
    now = datetime.now(timezone.utc)
    facts = [
        {
            "id": "fact-role",
            "snapshot_id": 9,
            "namespace": "authz",
            "subject": "agent-alpha",
            "predicate": "hasRole",
            "object_data": {"role": "warehouse_operator"},
            "valid_from": (now - timedelta(minutes=5)).isoformat(),
            "valid_to": (now + timedelta(minutes=5)).isoformat(),
        },
        {
            "id": "fact-allow",
            "snapshot_id": 9,
            "namespace": "authz",
            "subject": "role:warehouse_operator",
            "predicate": "allowedOperation",
            "object_data": {
                "operation": "PICK",
                "resource": "asset-42",
                "zones": ["cold-room"],
                "networks": ["plant-a"],
            },
            "valid_from": (now - timedelta(minutes=5)).isoformat(),
            "valid_to": (now + timedelta(minutes=5)).isoformat(),
        },
        {
            "id": "fact-zone",
            "snapshot_id": 9,
            "namespace": "authz",
            "subject": "asset-42",
            "predicate": "locatedInZone",
            "object_data": {"zone": "cold-room"},
        },
    ]
    service = AuthzGraphProjectionService(
        pkg_client=_FakePKGClient(snapshot_id=9, version="rules@9.0.0", facts=facts),
        registrations_loader=lambda **kwargs: asyncio.sleep(0, result=[]),
        tracking_events_loader=lambda **kwargs: asyncio.sleep(0, result=[]),
    )
    compiled_one, result_one = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase0",
        snapshot_version="rules@9.0.0",
    )
    compiled_two, result_two = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase0",
        snapshot_version="rules@9.0.0",
    )
    match = compiled_one.can_access(
        principal_ref="principal:agent-alpha",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        network_ref="network:plant-a",
    )

    return [
        CheckResult(
            "phase0.projection_rebuild_determinism",
            _serialize_snapshot(result_one.snapshot) == _serialize_snapshot(result_two.snapshot)
            and _serialize_edges(result_one.snapshot) == _serialize_edges(result_two.snapshot),
            {
                "snapshot_one_nodes": len(result_one.snapshot.nodes),
                "snapshot_two_nodes": len(result_two.snapshot.nodes),
                "snapshot_one_edges": len(result_one.snapshot.edges),
                "snapshot_two_edges": len(result_two.snapshot.edges),
            },
        ),
        CheckResult(
            "phase0.compiled_index_correctness",
            match.allowed is True and compiled_one.snapshot_version == compiled_two.snapshot_version,
            {
                "allowed": match.allowed,
                "snapshot_version": compiled_one.snapshot_version,
                "matched_subjects": list(match.matched_subjects),
            },
        ),
    ]


def _phase1_check() -> CheckResult:
    payload = _base_payload()
    payload["params"]["governance"]["requires_approved_source_registration"] = True
    payload["params"]["governance"]["action_intent"]["action"]["type"] = "RELEASE"
    payload["params"]["governance"]["action_intent"]["action"]["parameters"] = {
        "workflow_stage": "release_review"
    }
    payload["params"]["governance"]["action_intent"]["resource"].update(
        {
            "resource_uri": "resource:asset-1",
            "lot_id": "lot-1",
            "source_registration_id": "reg-1",
            "registration_decision_id": "decision-1",
            "product_id": "sku-1",
        }
    )
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@phase1",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "RELEASE_OPERATOR"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:RELEASE_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "RELEASE",
                    "resource": "asset-1",
                    "required_current_custodian": True,
                    "required_transferable_state": True,
                    "require_approved_source_registration": True,
                    "workflow_stages": ["release_review"],
                },
            },
            {
                "id": "fact-held",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "heldBy",
                "object_data": {"custodian": "agent-1", "transferable": True, "lot_id": "lot-1"},
            },
        ],
        registrations=[
            {"id": "reg-1", "snapshot_id": 1, "lot_id": "lot-1", "producer_id": "producer-1", "status": "approved"}
        ],
        registration_decisions=[
            {
                "id": "decision-1",
                "registration_id": "reg-1",
                "decision": "approved",
                "policy_snapshot_id": 1,
                "decided_at": "2099-03-20T11:59:00+00:00",
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)
    os.environ["SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS"] = "true"
    decision = evaluate_intent(
        payload,
        compiled_authz_index=compiled,
        approved_source_registrations={"reg-1": "decision-1"},
    )
    return CheckResult(
        "phase1.release_provenance_wedge",
        decision.allowed is True
        and decision.disposition == "allow"
        and any(item["code"] == "source_registration" and item["outcome"] == "passed" for item in decision.authz_graph["checked_constraints"])
        and "registration:reg-1" in decision.governed_receipt["evidence_refs"]
        and "registration_decision:decision-1" in decision.governed_receipt["evidence_refs"],
        {
            "allowed": decision.allowed,
            "disposition": decision.disposition,
            "authority_paths": decision.authz_graph["authority_paths"],
            "checked_constraints": decision.authz_graph["checked_constraints"],
            "evidence_refs": decision.governed_receipt["evidence_refs"],
        },
    )


def _phase2_check() -> CheckResult:
    payload = _base_payload()
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@phase2",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-delegated-by",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "delegatedBy",
                "object_data": {"org": "acme-logistics"},
            },
            {
                "id": "fact-facility",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "org:acme-logistics",
                "predicate": "approvedForFacility",
                "object_data": {"facility_id": "vault-hub"},
            },
            {
                "id": "fact-zone-control",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "facility:vault-hub",
                "predicate": "controlsZone",
                "object_data": {"zone": "vault-a"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "zone:vault-a",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MUTATE",
                    "resource": "seedcore://zones/vault-a/assets/asset-1",
                    "zones": ["vault-a"],
                },
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)
    decision = evaluate_intent(payload, compiled_authz_index=compiled)
    expected_path = (
        "principal:agent-1",
        "org:acme-logistics",
        "facility:vault-hub",
        "zone:vault-a",
    )
    return CheckResult(
        "phase2.multihop_authority_paths",
        decision.allowed is True and any(tuple(path) == expected_path for path in decision.authz_graph["authority_paths"]),
        {
            "allowed": decision.allowed,
            "authority_paths": decision.authz_graph["authority_paths"],
        },
    )


def _phase3_check() -> CheckResult:
    payload = _base_payload()
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@phase3",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:ROBOT_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MOVE",
                    "resource": "seedcore://zones/vault-a/assets/asset-1",
                    "zones": ["vault-a"],
                    "required_current_custodian": True,
                    "required_transferable_state": True,
                    "max_telemetry_age_seconds": 60,
                },
            },
            {
                "id": "fact-held",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "heldBy",
                "object_data": {"custodian": "agent-1", "transferable": True},
                "valid_from": "2099-03-20T11:55:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
            {
                "id": "fact-attest",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "attestedBy",
                "object_data": {
                    "attestation_id": "attest-1",
                    "attestor": "lab-1",
                    "valid_from": "2099-03-19T12:00:00+00:00",
                    "valid_to": "2099-03-21T12:00:00+00:00",
                },
            },
            {
                "id": "fact-seal",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "sealedWith",
                "object_data": {"seal_id": "seal-1"},
            },
            {
                "id": "fact-telemetry",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "observedIn",
                "object_data": {
                    "observation_id": "obs-1",
                    "measurement_type": "temperature",
                    "quality_score": 0.88,
                    "observed_at": "2099-03-20T11:30:00+00:00",
                },
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)
    os.environ["SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS"] = "true"
    decision = evaluate_intent(payload, compiled_authz_index=compiled)
    return CheckResult(
        "phase3.constraints_and_explanation",
        decision.allowed is True
        and decision.disposition == "quarantine"
        and "fact-allow" in decision.authz_graph["matched_policy_refs"]
        and any(item["code"] == "telemetry_freshness" and item["outcome"] == "failed" for item in decision.authz_graph["checked_constraints"])
        and any(item["code"] == "telemetry_freshness" and item["outcome"] == "failed" for item in decision.authz_graph["missing_prerequisites"]),
        {
            "disposition": decision.disposition,
            "matched_policy_refs": decision.authz_graph["matched_policy_refs"],
            "checked_constraints": decision.authz_graph["checked_constraints"],
            "missing_prerequisites": decision.authz_graph["missing_prerequisites"],
            "trust_gaps": decision.authz_graph["trust_gaps"],
        },
    )


async def _phase4_check(live_status: dict[str, Any]) -> CheckResult:
    facts = [
        {
            "id": "fact-role",
            "snapshot_id": 11,
            "namespace": "authz",
            "subject": "agent-alpha",
            "predicate": "hasRole",
            "object_data": {"role": "warehouse_operator"},
        },
        {
            "id": "fact-allow",
            "snapshot_id": 11,
            "namespace": "authz",
            "subject": "role:warehouse_operator",
            "predicate": "allowedOperation",
            "object_data": {"operation": "PICK", "resource": "asset-42"},
        },
    ]
    tracking_events = [
        {
            "id": "evt-1",
            "snapshot_id": 11,
            "event_type": "telemetry.update",
            "producer_id": "producer-1",
            "subject_id": "asset-42",
            "subject_type": "asset",
        }
    ]
    service = AuthzGraphProjectionService(
        pkg_client=_FakePKGClient(snapshot_id=11, version="rules@11.0.0", facts=facts),
        registrations_loader=lambda **kwargs: asyncio.sleep(0, result=[]),
        tracking_events_loader=lambda **kwargs: asyncio.sleep(0, result=tracking_events),
    )
    compiled, result = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase4",
        snapshot_version="rules@11.0.0",
    )
    authz_status = live_status.get("authz_graph") if isinstance(live_status.get("authz_graph"), dict) else {}
    return CheckResult(
        "phase4.decision_vs_enrichment_split",
        compiled.snapshot_version == "rules@11.0.0"
        and all(node.kind.value != "tracking_event" for node in result.snapshot.nodes)
        and any(node.kind.value == "tracking_event" for node in result.enrichment_snapshot.nodes)
        and {"decision_graph_nodes_count", "decision_graph_edges_count", "enrichment_graph_nodes_count", "enrichment_graph_edges_count"}.issubset(authz_status.keys()),
        {
            "decision_nodes": len(result.snapshot.nodes),
            "enrichment_nodes": len(result.enrichment_snapshot.nodes),
            "live_status": authz_status,
        },
    )


def _phase5_check(live_status: dict[str, Any]) -> CheckResult:
    status_graph = live_status.get("authz_graph") if isinstance(live_status.get("authz_graph"), dict) else {}
    snapshot_id = status_graph.get("active_snapshot_id")
    snapshot_version = status_graph.get("active_snapshot_version")
    snapshot_ref = f"authz_graph@{snapshot_version}" if snapshot_version else None

    payload = {
        "principal_ref": "principal:agent-1",
        "operation": "MOVE",
        "resource_ref": "seedcore://zones/vault-a/assets/asset-1",
        "facility_ref": "facility:vault-hub",
        "zone_ref": "zone:vault-a",
        "product_ref": "product:sku-1",
    }
    ray_result = evaluate_authz_with_ray_cache(
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        snapshot_ref=snapshot_ref,
        payload=payload,
        transitions=False,
        timeout_seconds=float(os.getenv("SEEDCORE_PDP_RAY_AUTHZ_CACHE_TIMEOUT_SECONDS", "5.0")),
    )

    actor_name = _authz_graph_cache_actor_name("facility:vault-hub")
    actor_found = False
    try:
        import ray  # pyright: ignore[reportMissingImports]

        if not ray.is_initialized():
            ray.init(
                address=os.getenv("RAY_ADDRESS", "ray://127.0.0.1:23001"),
                namespace=os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-local")),
                ignore_reinit_error=True,
                log_to_driver=False,
            )
        ray.get_actor(actor_name, namespace=os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-local")))
        actor_found = True
    except Exception:
        actor_found = False

    action_intent = ActionIntent.model_validate(
        _base_payload()["params"]["governance"]["action_intent"]
        | {"action": _base_payload()["params"]["governance"]["action_intent"]["action"] | {"parameters": {"facility_id": "vault-hub"}}}
    )
    shard_key = _compiled_authz_shard_key(action_intent)

    return CheckResult(
        "phase5.ray_shard_routing",
        ray_result is not None
        and ray_result.get("source") == "ray_actor"
        and ray_result.get("shard_key") == "facility:vault-hub"
        and shard_key == "facility:vault-hub"
        and actor_found,
        {
            "runtime_snapshot_id": snapshot_id,
            "runtime_snapshot_version": snapshot_version,
            "result_source": None if ray_result is None else ray_result.get("source"),
            "result_shard_key": None if ray_result is None else ray_result.get("shard_key"),
            "actor_name": actor_name,
            "actor_found": actor_found,
            "compiled_shard_key": shard_key,
        },
    )


async def main() -> int:
    results: list[CheckResult] = []

    pkg_status_response = requests.get(_api_url("/api/v1/pkg/status"), timeout=5)
    pkg_status_response.raise_for_status()
    pkg_status = pkg_status_response.json()

    authz_status_response = requests.get(_api_url("/api/v1/pkg/authz-graph/status"), timeout=5)
    authz_status_response.raise_for_status()
    authz_status = authz_status_response.json()

    refresh_response = requests.post(_api_url("/api/v1/pkg/authz-graph/refresh"), timeout=10)
    refresh_response.raise_for_status()
    refresh_payload = refresh_response.json()

    results.append(
        CheckResult(
            "phase0.runtime_snapshot_alignment_and_refresh",
            bool(pkg_status.get("available"))
            and bool(pkg_status.get("authz_graph_ready"))
            and pkg_status.get("snapshot_id") == pkg_status.get("authz_graph", {}).get("active_snapshot_id")
            and pkg_status.get("active_version") == pkg_status.get("authz_graph", {}).get("active_snapshot_version")
            and bool(refresh_payload.get("success")),
            {
                "pkg_status": {
                    "snapshot_id": pkg_status.get("snapshot_id"),
                    "active_version": pkg_status.get("active_version"),
                    "authz_graph": pkg_status.get("authz_graph"),
                },
                "refresh": refresh_payload,
                "authz_status": authz_status,
            },
        )
    )

    results.extend(await _phase0_checks())
    results.append(_phase1_check())
    results.append(_phase2_check())
    results.append(_phase3_check())
    results.append(await _phase4_check(pkg_status))
    results.append(_phase5_check(pkg_status))

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    print(
        json.dumps(
            {
                "summary": {
                    "checks": len(results),
                    "passed": len(results) - len(failing),
                    "failed": len(failing),
                    "active_snapshot_id": pkg_status.get("snapshot_id"),
                    "active_snapshot_version": pkg_status.get("active_version"),
                }
            },
            indent=2,
            sort_keys=True,
        )
    )

    if failing:
        print("\nAuthz graph RFC phase verification failed.", file=sys.stderr)
        return 1

    print("\nAuthz graph RFC phase verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
