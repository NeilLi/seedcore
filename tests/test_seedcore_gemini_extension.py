from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from seedcore.plugin import gemini_stdio


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_gemini_launcher_script_exists():
    launcher = REPO_ROOT / "scripts" / "gemini" / "run_seedcore_mcp.py"
    assert launcher.exists()


def test_load_seedcore_mcp_returns_tool_names(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    class StubMCP:
        def run(self):
            calls.append("run")

    monkeypatch.setattr(
        gemini_stdio.importlib,
        "import_module",
        lambda name: SimpleNamespace(mcp=StubMCP(), PLUGIN_TOOL_NAMES=("seedcore.health", "seedcore.readyz")),
    )

    mcp, tool_names = gemini_stdio.load_seedcore_mcp()

    assert hasattr(mcp, "run")
    assert tool_names == ("seedcore.health", "seedcore.readyz")


def test_load_seedcore_mcp_fails_clearly_when_dependency_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        gemini_stdio.importlib,
        "import_module",
        lambda name: SimpleNamespace(mcp=None, PLUGIN_TOOL_NAMES=("seedcore.health",)),
    )

    with pytest.raises(RuntimeError, match="'mcp' Python dependency is missing"):
        gemini_stdio.load_seedcore_mcp()


def test_load_seedcore_mcp_fails_clearly_when_seedcore_missing(monkeypatch: pytest.MonkeyPatch):
    def _boom(name: str):
        exc = ModuleNotFoundError("No module named 'seedcore'")
        exc.name = "seedcore"
        raise exc

    monkeypatch.setattr(gemini_stdio.importlib, "import_module", _boom)

    with pytest.raises(RuntimeError, match="Could not import 'seedcore'"):
        gemini_stdio.load_seedcore_mcp()


def test_gemini_stdio_main_runs_server(monkeypatch: pytest.MonkeyPatch):
    state = {"ran": False}

    class StubMCP:
        def run(self):
            state["ran"] = True

    monkeypatch.setattr(
        gemini_stdio,
        "load_seedcore_mcp",
        lambda: (StubMCP(), ("seedcore.health",)),
    )

    exit_code = gemini_stdio.main()

    assert exit_code == 0
    assert state["ran"] is True


def test_gemini_stdio_main_returns_failure_on_runtime_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(
        gemini_stdio,
        "load_seedcore_mcp",
        lambda: (_ for _ in ()).throw(RuntimeError("seedcore import failed")),
    )

    exit_code = gemini_stdio.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "seedcore import failed" in captured.err
