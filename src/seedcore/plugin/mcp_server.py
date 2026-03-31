from __future__ import annotations

import asyncio
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
