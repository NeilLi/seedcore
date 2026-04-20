from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

import seedcore.integrations.rust_kernel as rust_kernel


def test_verify_replay_bundle_uses_proof_py_bridge_when_available(monkeypatch):
    rust_kernel._reset_proof_py_bridge_cache_for_tests()
    monkeypatch.setenv("SEEDCORE_PROOF_PY_BRIDGE_ENABLED", "true")
    fake_bridge = SimpleNamespace(
        verify_chain=lambda payload: {
            "verified": True,
            "error_code": None,
            "artifact_reports": [],
            "chain_checks": ["ok"],
        }
    )
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE", fake_bridge, raising=True)
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE_CHECKED", True, raising=True)

    with patch.object(rust_kernel, "_run_verify_cli", side_effect=AssertionError("cli should not run")):
        report = rust_kernel.verify_replay_bundle_with_rust({"artifacts": []})

    assert report["verified"] is True
    assert report["chain_checks"] == ["ok"]


def test_verify_replay_bundle_falls_back_to_cli_when_bridge_payload_invalid(monkeypatch):
    rust_kernel._reset_proof_py_bridge_cache_for_tests()
    monkeypatch.setenv("SEEDCORE_PROOF_PY_BRIDGE_ENABLED", "true")
    fake_bridge = SimpleNamespace(
        verify_chain=lambda payload: "not-json",
    )
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE", fake_bridge, raising=True)
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE_CHECKED", True, raising=True)
    run_cli = MagicMock(
        return_value={
            "verified": True,
            "error_code": None,
            "artifact_reports": [],
            "chain_checks": ["cli"],
        }
    )
    monkeypatch.setattr(rust_kernel, "_run_verify_cli", run_cli, raising=True)

    report = rust_kernel.verify_replay_bundle_with_rust({"artifacts": []})

    assert report["verified"] is True
    assert report["chain_checks"] == ["cli"]
    run_cli.assert_called_once()


def test_verify_replay_bundle_supports_json_string_bridge_signatures(monkeypatch):
    rust_kernel._reset_proof_py_bridge_cache_for_tests()
    monkeypatch.setenv("SEEDCORE_PROOF_PY_BRIDGE_ENABLED", "true")

    def verify_chain(payload: str) -> str:
        loaded = json.loads(payload)
        assert loaded == {"artifacts": []}
        return json.dumps(
            {
                "verified": True,
                "error_code": None,
                "artifact_reports": [],
                "chain_checks": ["bridge-json"],
            }
        )

    fake_bridge = SimpleNamespace(verify_chain=verify_chain)
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE", fake_bridge, raising=True)
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE_CHECKED", True, raising=True)

    with patch.object(rust_kernel, "_run_verify_cli", side_effect=AssertionError("cli should not run")):
        report = rust_kernel.verify_replay_bundle_with_rust({"artifacts": []})

    assert report["verified"] is True
    assert report["chain_checks"] == ["bridge-json"]


def test_mint_execution_token_uses_bridge_when_available(monkeypatch):
    rust_kernel._reset_proof_py_bridge_cache_for_tests()
    monkeypatch.setenv("SEEDCORE_PROOF_PY_BRIDGE_ENABLED", "true")
    fake_bridge = SimpleNamespace(
        mint_execution_token=lambda payload: {
            "token_id": "token-1",
            "signature": {"signing_scheme": "debug_hash_v1"},
        }
    )
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE", fake_bridge, raising=True)
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE_CHECKED", True, raising=True)

    with patch.object(rust_kernel, "_run_verify_cli", side_effect=AssertionError("cli should not run")):
        token = rust_kernel.mint_execution_token_with_rust({"token_id": "token-1"})

    assert token["token_id"] == "token-1"


def test_mint_execution_token_falls_back_to_cli_when_bridge_payload_invalid(monkeypatch):
    rust_kernel._reset_proof_py_bridge_cache_for_tests()
    monkeypatch.setenv("SEEDCORE_PROOF_PY_BRIDGE_ENABLED", "true")
    fake_bridge = SimpleNamespace(mint_execution_token=lambda payload: {"unexpected": "shape"})
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE", fake_bridge, raising=True)
    monkeypatch.setattr(rust_kernel, "_PROOF_PY_MODULE_CHECKED", True, raising=True)
    run_cli = MagicMock(
        return_value={
            "token_id": "token-from-cli",
            "signature": {"signing_scheme": "debug_hash_v1"},
        }
    )
    monkeypatch.setattr(rust_kernel, "_run_verify_cli", run_cli, raising=True)

    token = rust_kernel.mint_execution_token_with_rust({"token_id": "token-1"})

    assert token["token_id"] == "token-from-cli"
    run_cli.assert_called_once()
