from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from seedcore.plugin.mcp_server import (
    PLUGIN_TOOL_NAMES,
    app,
    handle_digital_twin_capture_link,
    handle_evidence_verify,
    handle_health,
    handle_hotpath_benchmark,
    handle_hotpath_verify_shadow,
    handle_pkg_authz_graph_status,
    handle_pkg_status,
    handle_readyz,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class _RuntimeStub:
    def __init__(self) -> None:
        self.base_url = "http://127.0.0.1:8002"
        self.api_v1_base_url = f"{self.base_url}/api/v1"
        self.health = AsyncMock()
        self.readyz = AsyncMock()
        self.pkg_status = AsyncMock()
        self.pkg_authz_graph_status = AsyncMock()
        self.hotpath_status = AsyncMock()
        self.evidence_verify = AsyncMock()

    def root_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def api_url(self, path: str) -> str:
        return f"{self.api_v1_base_url}{path}"


def test_plugin_info_lists_seedcore_tools():
    client = TestClient(app)
    response = client.get("/info")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "seedcore-plugin-mcp"
    assert body["tools"] == PLUGIN_TOOL_NAMES


def test_packaging_files_point_to_seedcore_skill_bootstrap():
    extension = json.loads((REPO_ROOT / "gemini-extension.json").read_text())
    gemini_md = (REPO_ROOT / "GEMINI.md").read_text()
    codex_install = (REPO_ROOT / ".codex" / "INSTALL.md").read_text()

    assert extension["name"] == "seedcore"
    assert extension["contextFileName"] == "GEMINI.md"
    assert extension["mcpServers"]["seedcore"]["command"] == "python"
    assert extension["mcpServers"]["seedcore"]["args"] == [
        "${extensionPath}/scripts/gemini/run_seedcore_mcp.py"
    ]
    assert "skills/using-seedcore/SKILL.md" in gemini_md
    assert "gemini-troubleshooting.md" in gemini_md
    assert "~/.agents/skills/seedcore" in codex_install


@pytest.mark.asyncio
async def test_handle_health_and_readyz_normalize_payloads():
    runtime = _RuntimeStub()
    runtime.health.return_value = {
        "status": "healthy",
        "service": "seedcore-api",
        "version": "1.0.0",
    }
    runtime.readyz.return_value = {
        "status": "ready",
        "deps": {"db": "ok"},
    }

    health = await handle_health(runtime)
    readyz = await handle_readyz(runtime)

    assert health["ok"] is True
    assert health["service"] == "seedcore-api"
    assert health["source_url"].endswith("/health")
    assert readyz["ok"] is True
    assert readyz["deps"] == {"db": "ok"}
    assert readyz["source_url"].endswith("/readyz")


@pytest.mark.asyncio
async def test_handle_pkg_status_merges_authz_graph_summary():
    runtime = _RuntimeStub()
    runtime.pkg_status.return_value = {
        "available": True,
        "manager_exists": True,
        "evaluator_ready": True,
        "authz_graph_ready": True,
        "mode": "control",
        "active_version": "rules@7.0.0",
        "snapshot_id": 7,
        "engine_type": "native",
        "status": {"healthy": True},
        "authz_graph": {
            "active_snapshot_id": 7,
            "active_snapshot_version": "rules@7.0.0",
            "snapshot_hash": "hash-7",
            "compiled_at": "2026-03-27T10:00:00+00:00",
            "restricted_transfer_ready": True,
            "trust_gap_taxonomy": ["stale_telemetry"],
            "error": None,
        },
    }

    result = await handle_pkg_status(runtime)

    assert result["ok"] is True
    assert result["active_version"] == "rules@7.0.0"
    assert result["authz_graph"]["compiled_at"] == "2026-03-27T10:00:00+00:00"
    assert result["authz_graph"]["restricted_transfer_ready"] is True


@pytest.mark.asyncio
async def test_handle_pkg_authz_graph_status_normalizes_highlights():
    runtime = _RuntimeStub()
    runtime.pkg_authz_graph_status.return_value = {
        "available": True,
        "authz_graph_ready": True,
        "active_snapshot_id": 11,
        "active_snapshot_version": "rules@11.0.0",
        "snapshot_hash": "hash-11",
        "compiled_at": "2026-03-31T08:00:00+00:00",
        "restricted_transfer_ready": True,
        "hot_path_workflow": "restricted_custody_transfer",
        "graph_nodes_count": 18,
        "graph_edges_count": 24,
        "error": None,
    }

    result = await handle_pkg_authz_graph_status(runtime)

    assert result["ok"] is True
    assert result["active_snapshot_version"] == "rules@11.0.0"
    assert result["graph_edges_count"] == 24


@pytest.mark.asyncio
async def test_handle_evidence_verify_enforces_one_of_rule():
    runtime = _RuntimeStub()

    with pytest.raises(ValueError, match="Provide exactly one"):
        await handle_evidence_verify(
            runtime,
            reference_id="ref-1",
            public_id="pub-1",
        )


@pytest.mark.asyncio
async def test_handle_evidence_verify_forwards_valid_payload():
    runtime = _RuntimeStub()
    runtime.evidence_verify.return_value = {"verified": True, "reference_type": "audit"}

    result = await handle_evidence_verify(runtime, audit_id="audit-123")

    runtime.evidence_verify.assert_awaited_once_with({"audit_id": "audit-123"})
    assert result["verified"] is True
    assert result["source_url"].endswith("/api/v1/verify")


@pytest.mark.asyncio
async def test_handle_hotpath_verify_shadow_uses_host_tool(monkeypatch: pytest.MonkeyPatch):
    runtime = _RuntimeStub()

    monkeypatch.setattr(
        "seedcore.plugin.mcp_server.host_tools.run_shadow_verification",
        lambda **kwargs: {
            "pass": True,
            "base_url": kwargs["base_url"],
            "mode": "shadow",
            "active_snapshot": "snapshot:test",
            "run_parity_ok": 4,
            "run_total": 4,
            "run_mismatched": 0,
            "latency_ms": {"p95": 42},
            "cases": [{"case": "allow_case", "disposition": "allow"}],
            "artifact_path": "/tmp/shadow.json",
            "disposition_mismatches": [],
            "recent_mismatches": [],
        },
    )

    result = await handle_hotpath_verify_shadow(runtime)

    assert result["ok"] is True
    assert result["mode"] == "shadow"
    assert result["artifact_path"] == "/tmp/shadow.json"


@pytest.mark.asyncio
async def test_handle_hotpath_benchmark_uses_host_tool(monkeypatch: pytest.MonkeyPatch):
    runtime = _RuntimeStub()

    monkeypatch.setattr(
        "seedcore.plugin.mcp_server.host_tools.run_hotpath_benchmark",
        lambda **kwargs: {
            "base_url": kwargs["base_url"],
            "mode": "shadow",
            "active_snapshot": "snapshot:test",
            "total_requests": kwargs["requests"],
            "warmup_requests": kwargs["warmup"],
            "concurrency": kwargs["concurrency"],
            "latency_ms": {"p99": 88},
            "success_count": 40,
            "error_count": 0,
            "mismatch_count": 0,
            "quarantine_count": 1,
            "artifact_path": "/tmp/bench.json",
        },
    )

    result = await handle_hotpath_benchmark(runtime, requests=40, warmup=4, concurrency=4)

    assert result["ok"] is True
    assert result["latency_ms"]["p99"] == 88
    assert result["artifact_path"] == "/tmp/bench.json"


@pytest.mark.asyncio
async def test_handle_digital_twin_capture_link_returns_draft_candidate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "seedcore.plugin.mcp_server.capture_digital_twin_from_link",
        lambda **kwargs: {
            "ok": True,
            "source_url": kwargs["source_url"],
            "authority": {"status": "external_claim_only", "verified": False},
            "digital_twin_candidate": {"twin_id": "external:youtube:test"},
            "intent_candidate": {"intent_type": "capture_external_production_basics"},
        },
    )

    result = await handle_digital_twin_capture_link(source_url="https://www.youtube.com/shorts/test")

    assert result["ok"] is True
    assert result["authority"]["verified"] is False
    assert result["digital_twin_candidate"]["twin_id"] == "external:youtube:test"
