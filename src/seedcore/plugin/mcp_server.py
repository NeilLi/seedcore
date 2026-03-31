from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request  # pyright: ignore[reportMissingImports]
from fastapi.responses import JSONResponse  # pyright: ignore[reportMissingImports]

try:
    from mcp.server.fastmcp import Context, FastMCP  # pyright: ignore[reportMissingImports]
    from mcp.server.session import ServerSession  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError:  # pragma: no cover - exercised implicitly in local envs without mcp
    Context = Any  # type: ignore[assignment]
    FastMCP = None  # type: ignore[assignment]
    ServerSession = Any  # type: ignore[assignment]

from . import host_tools
from .capture_tools import capture_digital_twin_from_link
from .runtime_client import SeedcorePluginError, SeedcoreRuntimeClient


PLUGIN_TOOL_NAMES = [
    "seedcore.health",
    "seedcore.readyz",
    "seedcore.pkg.status",
    "seedcore.pkg.authz_graph_status",
    "seedcore.hotpath.status",
    "seedcore.hotpath.verify_shadow",
    "seedcore.hotpath.benchmark",
    "seedcore.evidence.verify",
    "seedcore.identity.owner.upsert",
    "seedcore.identity.owner.get",
    "seedcore.creator_profile.upsert",
    "seedcore.creator_profile.get",
    "seedcore.delegation.grant",
    "seedcore.delegation.get",
    "seedcore.delegation.revoke",
    "seedcore.trust_preferences.upsert",
    "seedcore.trust_preferences.get",
    "seedcore.owner_context.get",
    "seedcore.agent_action.preflight",
    "seedcore.digital_twin.capture_link",
    "seedcore.forensic_replay.fetch",
]


class ServiceState:
    def __init__(self, runtime: SeedcoreRuntimeClient):
        self.runtime = runtime


AppContext = Context[ServerSession, ServiceState] if FastMCP is not None else Any


def _normalize_health(raw: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    return {
        "ok": str(raw.get("status", "")).lower() in {"ok", "healthy", "ready"},
        "status": raw.get("status"),
        "service": raw.get("service"),
        "version": raw.get("version"),
        "source_url": source_url,
    }


def _normalize_readyz(raw: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    deps = raw.get("deps") if isinstance(raw.get("deps"), dict) else {}
    return {
        "ok": str(raw.get("status", "")).lower() == "ready",
        "status": raw.get("status"),
        "deps": deps,
        "source_url": source_url,
    }


def _authz_graph_highlights(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": bool(raw.get("available")),
        "authz_graph_ready": bool(raw.get("authz_graph_ready")),
        "active_snapshot_id": raw.get("active_snapshot_id"),
        "active_snapshot_version": raw.get("active_snapshot_version"),
        "snapshot_hash": raw.get("snapshot_hash"),
        "compiled_at": raw.get("compiled_at"),
        "restricted_transfer_ready": raw.get("restricted_transfer_ready"),
        "hot_path_workflow": raw.get("hot_path_workflow"),
        "graph_nodes_count": raw.get("graph_nodes_count"),
        "graph_edges_count": raw.get("graph_edges_count"),
        "error": raw.get("error"),
    }


async def handle_health(runtime: SeedcoreRuntimeClient) -> dict[str, Any]:
    raw = await runtime.health()
    return _normalize_health(raw, source_url=runtime.root_url("/health"))


async def handle_readyz(runtime: SeedcoreRuntimeClient) -> dict[str, Any]:
    raw = await runtime.readyz()
    return _normalize_readyz(raw, source_url=runtime.root_url("/readyz"))


async def handle_pkg_status(runtime: SeedcoreRuntimeClient) -> dict[str, Any]:
    raw = await runtime.pkg_status()
    authz_graph = raw.get("authz_graph") if isinstance(raw.get("authz_graph"), dict) else {}
    return {
        "ok": bool(raw.get("available")),
        "available": bool(raw.get("available")),
        "manager_exists": bool(raw.get("manager_exists")),
        "evaluator_ready": bool(raw.get("evaluator_ready")),
        "authz_graph_ready": bool(raw.get("authz_graph_ready")),
        "mode": raw.get("mode"),
        "active_version": raw.get("active_version") or raw.get("version"),
        "snapshot_id": raw.get("snapshot_id"),
        "engine_type": raw.get("engine_type"),
        "status": raw.get("status"),
        "authz_graph": {
            "active_snapshot_id": authz_graph.get("active_snapshot_id"),
            "active_snapshot_version": authz_graph.get("active_snapshot_version"),
            "snapshot_hash": authz_graph.get("snapshot_hash"),
            "compiled_at": authz_graph.get("compiled_at"),
            "restricted_transfer_ready": authz_graph.get("restricted_transfer_ready"),
            "trust_gap_taxonomy": authz_graph.get("trust_gap_taxonomy"),
            "error": authz_graph.get("error"),
        },
        "source_url": runtime.api_url("/pkg/status"),
    }


async def handle_pkg_authz_graph_status(runtime: SeedcoreRuntimeClient) -> dict[str, Any]:
    raw = await runtime.pkg_authz_graph_status()
    normalized = _authz_graph_highlights(raw)
    normalized["source_url"] = runtime.api_url("/pkg/authz-graph/status")
    normalized["ok"] = bool(normalized["available"])
    return normalized


async def handle_hotpath_status(runtime: SeedcoreRuntimeClient) -> dict[str, Any]:
    raw = await runtime.hotpath_status()
    return {
        "ok": bool(raw.get("authz_graph_ready", True)),
        "mode": raw.get("mode"),
        "enforce_ready": raw.get("enforce_ready"),
        "authz_graph_ready": raw.get("authz_graph_ready"),
        "graph_freshness_ok": raw.get("graph_freshness_ok"),
        "active_snapshot_version": raw.get("active_snapshot_version"),
        "graph_age_seconds": raw.get("graph_age_seconds"),
        "total": raw.get("total"),
        "parity_ok": raw.get("parity_ok"),
        "mismatched": raw.get("mismatched"),
        "latency_ms": raw.get("latency_ms"),
        "recent_results": raw.get("recent_results"),
        "source_url": runtime.api_url("/pdp/hot-path/status"),
    }


async def handle_hotpath_verify_shadow(
    runtime: SeedcoreRuntimeClient,
    *,
    base_url: str | None = None,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    resolved_base_url = base_url or runtime.api_v1_base_url
    summary = await asyncio.to_thread(
        host_tools.run_shadow_verification,
        base_url=resolved_base_url,
        artifact_dir=artifact_dir,
    )
    return {
        "ok": bool(summary.get("pass")),
        "base_url": summary.get("base_url"),
        "mode": summary.get("mode"),
        "active_snapshot": summary.get("active_snapshot"),
        "run_parity_ok": summary.get("run_parity_ok"),
        "run_total": summary.get("run_total"),
        "run_mismatched": summary.get("run_mismatched"),
        "latency_ms": summary.get("latency_ms"),
        "cases": summary.get("cases"),
        "artifact_path": summary.get("artifact_path"),
        "disposition_mismatches": summary.get("disposition_mismatches"),
        "recent_mismatches": summary.get("recent_mismatches"),
    }


async def handle_hotpath_benchmark(
    runtime: SeedcoreRuntimeClient,
    *,
    base_url: str | None = None,
    requests: int = 40,
    warmup: int = 4,
    concurrency: int = 4,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    resolved_base_url = base_url or runtime.api_v1_base_url
    summary = await asyncio.to_thread(
        host_tools.run_hotpath_benchmark,
        base_url=resolved_base_url,
        requests=requests,
        warmup=warmup,
        concurrency=concurrency,
        artifact_dir=artifact_dir,
    )
    return {
        "ok": int(summary.get("error_count") or 0) == 0,
        "base_url": summary.get("base_url"),
        "mode": summary.get("mode"),
        "active_snapshot": summary.get("active_snapshot"),
        "requests": summary.get("total_requests"),
        "warmup": summary.get("warmup_requests"),
        "concurrency": summary.get("concurrency"),
        "latency_ms": summary.get("latency_ms"),
        "success_count": summary.get("success_count"),
        "error_count": summary.get("error_count"),
        "mismatch_count": summary.get("mismatch_count"),
        "quarantine_count": summary.get("quarantine_count"),
        "artifact_path": summary.get("artifact_path"),
    }


def _verify_payload(
    *,
    reference_id: str | None = None,
    public_id: str | None = None,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
) -> dict[str, Any]:
    provided = [
        bool(reference_id and reference_id.strip()),
        bool(public_id and public_id.strip()),
        bool(audit_id and audit_id.strip()),
        bool(subject_id and subject_id.strip()),
    ]
    if sum(provided) != 1:
        raise ValueError("Provide exactly one of reference_id, public_id, audit_id, or subject_id")
    payload: dict[str, Any] = {}
    if reference_id:
        payload["reference_id"] = reference_id
    if public_id:
        payload["public_id"] = public_id
    if audit_id:
        payload["audit_id"] = audit_id
    if subject_id:
        payload["subject_id"] = subject_id
    if subject_type:
        payload["subject_type"] = subject_type
    return payload


async def handle_evidence_verify(
    runtime: SeedcoreRuntimeClient,
    *,
    reference_id: str | None = None,
    public_id: str | None = None,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
) -> dict[str, Any]:
    payload = _verify_payload(
        reference_id=reference_id,
        public_id=public_id,
        audit_id=audit_id,
        subject_id=subject_id,
        subject_type=subject_type,
    )
    result = await runtime.evidence_verify(payload)
    result["source_url"] = runtime.api_url("/verify")
    return result


async def handle_owner_identity_upsert(
    runtime: SeedcoreRuntimeClient,
    *,
    did: str,
    controller: str | None = None,
    display_name: str | None = None,
    signing_scheme: str = "ed25519",
    public_key: str | None = None,
    key_ref: str | None = None,
    service_endpoints: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = "ACTIVE",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "did": did,
        "signing_scheme": signing_scheme,
        "status": status,
        "service_endpoints": service_endpoints or {},
        "metadata": metadata or {},
    }
    if controller is not None:
        payload["controller"] = controller
    if display_name is not None:
        payload["display_name"] = display_name
    if public_key is not None:
        payload["public_key"] = public_key
    if key_ref is not None:
        payload["key_ref"] = key_ref
    result = await runtime.register_did(payload)
    result["source_url"] = runtime.api_url("/identities/dids")
    return result


async def handle_owner_identity_get(
    runtime: SeedcoreRuntimeClient,
    *,
    did: str,
) -> dict[str, Any]:
    result = await runtime.get_did(did)
    result["source_url"] = runtime.api_url(f"/identities/dids/{did}")
    return result


async def handle_creator_profile_upsert(
    runtime: SeedcoreRuntimeClient,
    *,
    owner_id: str,
    version: str = "v1",
    status: str = "ACTIVE",
    display_name: str | None = None,
    brand_handles: dict[str, str] | None = None,
    commerce_prefs: dict[str, Any] | None = None,
    publish_prefs: dict[str, Any] | None = None,
    risk_profile: dict[str, Any] | None = None,
    updated_by: str = "identity_router",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "owner_id": owner_id,
        "version": version,
        "status": status,
        "brand_handles": brand_handles or {},
        "commerce_prefs": commerce_prefs or {},
        "publish_prefs": publish_prefs or {},
        "risk_profile": risk_profile or {},
        "updated_by": updated_by,
        "metadata": metadata or {},
    }
    if display_name is not None:
        payload["display_name"] = display_name
    result = await runtime.upsert_creator_profile(payload)
    result["source_url"] = runtime.api_url("/creator-profiles")
    return result


async def handle_creator_profile_get(
    runtime: SeedcoreRuntimeClient,
    *,
    owner_id: str,
) -> dict[str, Any]:
    result = await runtime.get_creator_profile(owner_id)
    result["source_url"] = runtime.api_url(f"/creator-profiles/{owner_id}")
    return result


async def handle_delegation_grant(
    runtime: SeedcoreRuntimeClient,
    *,
    owner_id: str,
    assistant_id: str,
    authority_level: str = "observer",
    scope: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
    requires_step_up: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "owner_id": owner_id,
        "assistant_id": assistant_id,
        "authority_level": authority_level,
        "scope": list(scope or []),
        "constraints": dict(constraints or {}),
        "requires_step_up": bool(requires_step_up),
    }
    result = await runtime.grant_delegation(payload)
    result["source_url"] = runtime.api_url("/delegations")
    return result


async def handle_delegation_get(
    runtime: SeedcoreRuntimeClient,
    *,
    delegation_id: str,
) -> dict[str, Any]:
    result = await runtime.get_delegation(delegation_id)
    result["source_url"] = runtime.api_url(f"/delegations/{delegation_id}")
    return result


async def handle_delegation_revoke(
    runtime: SeedcoreRuntimeClient,
    *,
    delegation_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    result = await runtime.revoke_delegation(delegation_id, payload=payload)
    result["source_url"] = runtime.api_url(f"/delegations/{delegation_id}/revoke")
    return result


async def handle_trust_preferences_upsert(
    runtime: SeedcoreRuntimeClient,
    *,
    owner_id: str,
    trust_version: str = "v1",
    status: str = "ACTIVE",
    max_risk_score: float | None = None,
    merchant_allowlist: list[str] | None = None,
    required_provenance_level: str | None = None,
    required_evidence_modalities: list[str] | None = None,
    high_value_step_up_threshold_usd: float | None = None,
    updated_by: str = "identity_router",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "owner_id": owner_id,
        "trust_version": trust_version,
        "status": status,
        "merchant_allowlist": list(merchant_allowlist or []),
        "required_evidence_modalities": list(required_evidence_modalities or []),
        "updated_by": updated_by,
        "metadata": metadata or {},
    }
    if max_risk_score is not None:
        payload["max_risk_score"] = float(max_risk_score)
    if required_provenance_level is not None:
        payload["required_provenance_level"] = required_provenance_level
    if high_value_step_up_threshold_usd is not None:
        payload["high_value_step_up_threshold_usd"] = float(high_value_step_up_threshold_usd)
    result = await runtime.upsert_trust_preferences(payload)
    result["source_url"] = runtime.api_url("/trust-preferences")
    return result


async def handle_trust_preferences_get(
    runtime: SeedcoreRuntimeClient,
    *,
    owner_id: str,
) -> dict[str, Any]:
    result = await runtime.get_trust_preferences(owner_id)
    result["source_url"] = runtime.api_url(f"/trust-preferences/{owner_id}")
    return result


async def handle_owner_context_get(
    runtime: SeedcoreRuntimeClient,
    *,
    owner_id: str,
    include_identity: bool = True,
    include_creator_profile: bool = True,
    include_trust_preferences: bool = True,
) -> dict[str, Any]:
    owner_identity: dict[str, Any] | None = None
    creator_profile: dict[str, Any] | None = None
    trust_preferences: dict[str, Any] | None = None
    warnings: list[str] = []

    if include_identity:
        try:
            owner_identity = await runtime.get_did(owner_id)
        except SeedcorePluginError:
            warnings.append("owner_identity_unavailable")
    if include_creator_profile:
        try:
            creator_profile = await runtime.get_creator_profile(owner_id)
        except SeedcorePluginError:
            warnings.append("creator_profile_unavailable")
    if include_trust_preferences:
        try:
            trust_preferences = await runtime.get_trust_preferences(owner_id)
        except SeedcorePluginError:
            warnings.append("trust_preferences_unavailable")

    signer_did = (
        str(owner_identity.get("did")).strip()
        if isinstance(owner_identity, dict) and owner_identity.get("did")
        else owner_id
    )
    verification_method = (
        owner_identity.get("verification_method")
        if isinstance(owner_identity, dict) and isinstance(owner_identity.get("verification_method"), dict)
        else {}
    )
    signer_key_ref = (
        str(verification_method.get("key_ref")).strip()
        if isinstance(verification_method, dict) and verification_method.get("key_ref")
        else None
    )

    creator_profile_ref = (
        {
            "owner_id": owner_id,
            "version": creator_profile.get("version"),
            "updated_at": creator_profile.get("updated_at"),
            "updated_by": creator_profile.get("updated_by"),
            "source_namespace": "identity",
            "source_predicate": "creator_profile",
            "signer_did": signer_did,
            "signer_key_ref": signer_key_ref,
        }
        if isinstance(creator_profile, dict)
        else None
    )
    trust_preferences_ref = (
        {
            "owner_id": owner_id,
            "trust_version": trust_preferences.get("trust_version"),
            "updated_at": trust_preferences.get("updated_at"),
            "updated_by": trust_preferences.get("updated_by"),
            "source_namespace": "identity",
            "source_predicate": "trust_preferences",
            "signer_did": signer_did,
            "signer_key_ref": signer_key_ref,
        }
        if isinstance(trust_preferences, dict)
        else None
    )
    owner_context_ref = {
        "owner_id": owner_id,
        "creator_profile_ref": creator_profile_ref,
        "trust_preferences_ref": trust_preferences_ref,
    }
    owner_context_hash = "sha256:" + hashlib.sha256(
        json.dumps(owner_context_ref, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "owner_id": owner_id,
        "owner_identity": owner_identity,
        "creator_profile": creator_profile,
        "trust_preferences": trust_preferences,
        "owner_context_ref": owner_context_ref,
        "owner_context_hash": owner_context_hash,
        "warnings": warnings,
        "source_urls": {
            "identity_url": runtime.api_url(f"/identities/dids/{owner_id}") if include_identity else None,
            "creator_profile_url": runtime.api_url(f"/creator-profiles/{owner_id}") if include_creator_profile else None,
            "trust_preferences_url": runtime.api_url(f"/trust-preferences/{owner_id}") if include_trust_preferences else None,
        },
    }


async def handle_agent_action_preflight(
    runtime: SeedcoreRuntimeClient,
    *,
    request: dict[str, Any],
    debug: bool = True,
    no_execute: bool = True,
) -> dict[str, Any]:
    result = await runtime.evaluate_agent_action(
        request,
        debug=debug,
        no_execute=no_execute,
    )
    return {
        "ok": bool(result.get("decision", {}).get("allowed")),
        "preflight": {
            "debug": bool(debug),
            "no_execute": bool(no_execute),
        },
        "decision": result.get("decision"),
        "required_approvals": result.get("required_approvals"),
        "trust_gaps": result.get("trust_gaps"),
        "obligations": result.get("obligations"),
        "minted_artifacts": result.get("minted_artifacts"),
        "execution_token": result.get("execution_token"),
        "governed_receipt": result.get("governed_receipt"),
        "raw": result,
        "source_url": runtime.api_url("/agent-actions/evaluate"),
    }


async def handle_digital_twin_capture_link(
    *,
    source_url: str,
    twin_kind: str = "product",
    subject_name: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        capture_digital_twin_from_link,
        source_url=source_url,
        twin_kind=twin_kind,
        subject_name=subject_name,
    )


def _replay_lookup_params(
    *,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
    task_id: str | None = None,
    intent_id: str | None = None,
    projection: str = "buyer",
) -> dict[str, Any]:
    provided = [
        bool(audit_id and audit_id.strip()),
        bool(subject_id and subject_id.strip()),
        bool(task_id and task_id.strip()),
        bool(intent_id and intent_id.strip()),
    ]
    if sum(provided) != 1:
        raise ValueError("Provide exactly one of audit_id, subject_id, task_id, or intent_id")
    payload: dict[str, Any] = {"projection": projection}
    if audit_id:
        payload["audit_id"] = audit_id
    if subject_id:
        payload["subject_id"] = subject_id
    if subject_type:
        payload["subject_type"] = subject_type
    if task_id:
        payload["task_id"] = task_id
    if intent_id:
        payload["intent_id"] = intent_id
    return payload


async def handle_forensic_replay_fetch(
    runtime: SeedcoreRuntimeClient,
    *,
    public_id: str | None = None,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
    task_id: str | None = None,
    intent_id: str | None = None,
    projection: str = "buyer",
) -> dict[str, Any]:
    provided = [
        bool(public_id and public_id.strip()),
        bool(audit_id and audit_id.strip()),
        bool(subject_id and subject_id.strip()),
        bool(task_id and task_id.strip()),
        bool(intent_id and intent_id.strip()),
    ]
    if sum(provided) != 1:
        raise ValueError("Provide exactly one of public_id, audit_id, subject_id, task_id, or intent_id")
    if public_id and public_id.strip():
        trust_page = await runtime.trust_page(public_id.strip())
        trust_jsonld = await runtime.trust_jsonld(public_id.strip())
        trust_certificate = await runtime.trust_certificate(public_id.strip())
        verification_status = (
            trust_page.get("verification_status")
            if isinstance(trust_page.get("verification_status"), dict)
            else {}
        )
        return {
            "ok": bool(verification_status.get("verified")),
            "mode": "public_trust_page",
            "public_id": public_id.strip(),
            "subject_title": trust_page.get("subject_title"),
            "subject_summary": trust_page.get("subject_summary"),
            "workflow_type": trust_page.get("workflow_type"),
            "status": trust_page.get("status"),
            "verification_status": verification_status,
            "approvals": trust_page.get("approvals"),
            "authorization": trust_page.get("authorization"),
            "custody_summary": trust_page.get("custody_summary"),
            "timeline_summary": trust_page.get("timeline_summary"),
            "verifiable_claims": trust_page.get("verifiable_claims"),
            "public_media_refs": trust_page.get("public_media_refs"),
            "public_jsonld_ref": trust_page.get("public_jsonld_ref"),
            "public_certificate_ref": trust_page.get("public_certificate_ref"),
            "jsonld": trust_jsonld,
            "certificate": trust_certificate,
            "source_url": runtime.api_url(f"/trust/{public_id.strip()}"),
        }

    params = _replay_lookup_params(
        audit_id=audit_id,
        subject_id=subject_id,
        subject_type=subject_type,
        task_id=task_id,
        intent_id=intent_id,
        projection=projection,
    )
    replay = await runtime.replay(params)
    timeline = await runtime.replay_timeline({key: value for key, value in params.items() if key != "projection"})
    artifacts = await runtime.replay_artifacts(params)
    jsonld = await runtime.replay_jsonld(params)
    record = replay.get("record") if isinstance(replay.get("record"), dict) else {}
    verification_status = (
        record.get("verification_status")
        if isinstance(record.get("verification_status"), dict)
        else timeline.get("verification_status")
        if isinstance(timeline.get("verification_status"), dict)
        else {}
    )
    return {
        "ok": bool(verification_status.get("verified")),
        "mode": "replay_record",
        "lookup_key": replay.get("lookup_key"),
        "lookup_value": replay.get("lookup_value"),
        "projection": replay.get("projection"),
        "replay_id": record.get("replay_id"),
        "subject_type": record.get("subject_type"),
        "subject_id": record.get("subject_id"),
        "task_id": record.get("task_id"),
        "intent_id": record.get("intent_id"),
        "audit_record_id": record.get("audit_record_id"),
        "verification_status": verification_status,
        "view": replay.get("view"),
        "timeline": timeline.get("timeline"),
        "artifacts": artifacts,
        "jsonld": jsonld,
        "source_url": runtime.api_url("/replay"),
    }


if FastMCP is not None:
    @asynccontextmanager
    async def app_lifespan(server: FastMCP):
        runtime = SeedcoreRuntimeClient()
        try:
            yield ServiceState(runtime=runtime)
        finally:
            await runtime.close()


    mcp = FastMCP("Seedcore Plugin MCP", lifespan=app_lifespan)


    def _runtime(ctx: AppContext) -> SeedcoreRuntimeClient:
        return ctx.request_context.lifespan_context.runtime


    @mcp.tool(name="seedcore.health")
    async def seedcore_health(ctx: AppContext) -> dict[str, Any]:
        return await handle_health(_runtime(ctx))


    @mcp.tool(name="seedcore.readyz")
    async def seedcore_readyz(ctx: AppContext) -> dict[str, Any]:
        return await handle_readyz(_runtime(ctx))


    @mcp.tool(name="seedcore.pkg.status")
    async def seedcore_pkg_status(ctx: AppContext) -> dict[str, Any]:
        return await handle_pkg_status(_runtime(ctx))


    @mcp.tool(name="seedcore.pkg.authz_graph_status")
    async def seedcore_pkg_authz_graph_status(ctx: AppContext) -> dict[str, Any]:
        return await handle_pkg_authz_graph_status(_runtime(ctx))


    @mcp.tool(name="seedcore.hotpath.status")
    async def seedcore_hotpath_status(ctx: AppContext) -> dict[str, Any]:
        return await handle_hotpath_status(_runtime(ctx))


    @mcp.tool(name="seedcore.hotpath.verify_shadow")
    async def seedcore_hotpath_verify_shadow(
        ctx: AppContext,
        base_url: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return await handle_hotpath_verify_shadow(
            _runtime(ctx),
            base_url=base_url,
            artifact_dir=artifact_dir,
        )


    @mcp.tool(name="seedcore.hotpath.benchmark")
    async def seedcore_hotpath_benchmark(
        ctx: AppContext,
        base_url: str | None = None,
        requests: int = 40,
        warmup: int = 4,
        concurrency: int = 4,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return await handle_hotpath_benchmark(
            _runtime(ctx),
            base_url=base_url,
            requests=requests,
            warmup=warmup,
            concurrency=concurrency,
            artifact_dir=artifact_dir,
        )


    @mcp.tool(name="seedcore.evidence.verify")
    async def seedcore_evidence_verify(
        ctx: AppContext,
        reference_id: str | None = None,
        public_id: str | None = None,
        audit_id: str | None = None,
        subject_id: str | None = None,
        subject_type: str | None = None,
    ) -> dict[str, Any]:
        return await handle_evidence_verify(
            _runtime(ctx),
            reference_id=reference_id,
            public_id=public_id,
            audit_id=audit_id,
            subject_id=subject_id,
            subject_type=subject_type,
        )


    @mcp.tool(name="seedcore.identity.owner.upsert")
    async def seedcore_identity_owner_upsert(
        ctx: AppContext,
        did: str,
        controller: str | None = None,
        display_name: str | None = None,
        signing_scheme: str = "ed25519",
        public_key: str | None = None,
        key_ref: str | None = None,
        service_endpoints: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "ACTIVE",
    ) -> dict[str, Any]:
        return await handle_owner_identity_upsert(
            _runtime(ctx),
            did=did,
            controller=controller,
            display_name=display_name,
            signing_scheme=signing_scheme,
            public_key=public_key,
            key_ref=key_ref,
            service_endpoints=service_endpoints,
            metadata=metadata,
            status=status,
        )


    @mcp.tool(name="seedcore.identity.owner.get")
    async def seedcore_identity_owner_get(
        ctx: AppContext,
        did: str,
    ) -> dict[str, Any]:
        return await handle_owner_identity_get(_runtime(ctx), did=did)


    @mcp.tool(name="seedcore.creator_profile.upsert")
    async def seedcore_creator_profile_upsert(
        ctx: AppContext,
        owner_id: str,
        version: str = "v1",
        status: str = "ACTIVE",
        display_name: str | None = None,
        brand_handles: dict[str, str] | None = None,
        commerce_prefs: dict[str, Any] | None = None,
        publish_prefs: dict[str, Any] | None = None,
        risk_profile: dict[str, Any] | None = None,
        updated_by: str = "identity_router",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await handle_creator_profile_upsert(
            _runtime(ctx),
            owner_id=owner_id,
            version=version,
            status=status,
            display_name=display_name,
            brand_handles=brand_handles,
            commerce_prefs=commerce_prefs,
            publish_prefs=publish_prefs,
            risk_profile=risk_profile,
            updated_by=updated_by,
            metadata=metadata,
        )


    @mcp.tool(name="seedcore.creator_profile.get")
    async def seedcore_creator_profile_get(
        ctx: AppContext,
        owner_id: str,
    ) -> dict[str, Any]:
        return await handle_creator_profile_get(_runtime(ctx), owner_id=owner_id)


    @mcp.tool(name="seedcore.delegation.grant")
    async def seedcore_delegation_grant(
        ctx: AppContext,
        owner_id: str,
        assistant_id: str,
        authority_level: str = "observer",
        scope: list[str] | None = None,
        constraints: dict[str, Any] | None = None,
        requires_step_up: bool = True,
    ) -> dict[str, Any]:
        return await handle_delegation_grant(
            _runtime(ctx),
            owner_id=owner_id,
            assistant_id=assistant_id,
            authority_level=authority_level,
            scope=scope,
            constraints=constraints,
            requires_step_up=requires_step_up,
        )


    @mcp.tool(name="seedcore.delegation.get")
    async def seedcore_delegation_get(
        ctx: AppContext,
        delegation_id: str,
    ) -> dict[str, Any]:
        return await handle_delegation_get(_runtime(ctx), delegation_id=delegation_id)


    @mcp.tool(name="seedcore.delegation.revoke")
    async def seedcore_delegation_revoke(
        ctx: AppContext,
        delegation_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return await handle_delegation_revoke(
            _runtime(ctx),
            delegation_id=delegation_id,
            reason=reason,
        )


    @mcp.tool(name="seedcore.trust_preferences.upsert")
    async def seedcore_trust_preferences_upsert(
        ctx: AppContext,
        owner_id: str,
        trust_version: str = "v1",
        status: str = "ACTIVE",
        max_risk_score: float | None = None,
        merchant_allowlist: list[str] | None = None,
        required_provenance_level: str | None = None,
        required_evidence_modalities: list[str] | None = None,
        high_value_step_up_threshold_usd: float | None = None,
        updated_by: str = "identity_router",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await handle_trust_preferences_upsert(
            _runtime(ctx),
            owner_id=owner_id,
            trust_version=trust_version,
            status=status,
            max_risk_score=max_risk_score,
            merchant_allowlist=merchant_allowlist,
            required_provenance_level=required_provenance_level,
            required_evidence_modalities=required_evidence_modalities,
            high_value_step_up_threshold_usd=high_value_step_up_threshold_usd,
            updated_by=updated_by,
            metadata=metadata,
        )


    @mcp.tool(name="seedcore.trust_preferences.get")
    async def seedcore_trust_preferences_get(
        ctx: AppContext,
        owner_id: str,
    ) -> dict[str, Any]:
        return await handle_trust_preferences_get(_runtime(ctx), owner_id=owner_id)


    @mcp.tool(name="seedcore.owner_context.get")
    async def seedcore_owner_context_get(
        ctx: AppContext,
        owner_id: str,
        include_identity: bool = True,
        include_creator_profile: bool = True,
        include_trust_preferences: bool = True,
    ) -> dict[str, Any]:
        return await handle_owner_context_get(
            _runtime(ctx),
            owner_id=owner_id,
            include_identity=include_identity,
            include_creator_profile=include_creator_profile,
            include_trust_preferences=include_trust_preferences,
        )


    @mcp.tool(name="seedcore.agent_action.preflight")
    async def seedcore_agent_action_preflight(
        ctx: AppContext,
        request: dict[str, Any],
        debug: bool = True,
        no_execute: bool = True,
    ) -> dict[str, Any]:
        return await handle_agent_action_preflight(
            _runtime(ctx),
            request=request,
            debug=debug,
            no_execute=no_execute,
        )


    @mcp.tool(name="seedcore.digital_twin.capture_link")
    async def seedcore_digital_twin_capture_link(
        ctx: AppContext,
        source_url: str,
        twin_kind: str = "product",
        subject_name: str | None = None,
    ) -> dict[str, Any]:
        del ctx
        return await handle_digital_twin_capture_link(
            source_url=source_url,
            twin_kind=twin_kind,
            subject_name=subject_name,
        )


    @mcp.tool(name="seedcore.forensic_replay.fetch")
    async def seedcore_forensic_replay_fetch(
        ctx: AppContext,
        public_id: str | None = None,
        audit_id: str | None = None,
        subject_id: str | None = None,
        subject_type: str | None = None,
        task_id: str | None = None,
        intent_id: str | None = None,
        projection: str = "buyer",
    ) -> dict[str, Any]:
        return await handle_forensic_replay_fetch(
            _runtime(ctx),
            public_id=public_id,
            audit_id=audit_id,
            subject_id=subject_id,
            subject_type=subject_type,
            task_id=task_id,
            intent_id=intent_id,
            projection=projection,
        )
else:  # pragma: no cover - only used in envs missing the optional dependency
    mcp = None


app = FastAPI(title="Seedcore Plugin MCP", version="1.0.0")

_origin_validation_enabled = (
    os.getenv("MCP_VALIDATE_ORIGIN", "1").strip().lower()
    not in {"0", "false", "no", "off"}
)
_configured_allowed_origins = {
    origin.strip()
    for origin in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}


def _is_loopback_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _is_origin_allowed(origin: str) -> bool:
    if not origin:
        return True
    if origin in _configured_allowed_origins:
        return True
    return _is_loopback_origin(origin)


@app.middleware("http")
async def validate_origin_middleware(request: Request, call_next):
    if not _origin_validation_enabled or request.url.path in {"/health", "/info"}:
        return await call_next(request)
    origin = request.headers.get("origin", "")
    if origin and not _is_origin_allowed(origin):
        return JSONResponse(
            status_code=403,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "Forbidden Origin"},
            },
        )
    return await call_next(request)


@app.exception_handler(SeedcorePluginError)
async def seedcore_plugin_error_handler(_: Request, exc: SeedcorePluginError):
    return JSONResponse(status_code=503, content={"error": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "seedcore-plugin-mcp"}


@app.get("/info")
async def info() -> dict[str, Any]:
    return {
        "service": "seedcore-plugin-mcp",
        "version": "1.0.0",
        "tools": PLUGIN_TOOL_NAMES,
        "description": "Read-only Seedcore operator tools for Codex and Gemini hosts",
    }


if mcp is not None:
    app.mount("/", mcp.streamable_http_app())
