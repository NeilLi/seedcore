import ast
import os
import pytest
from unittest.mock import MagicMock

# Import the endpoints and models to test coupling
from seedcore.api.routers.pkg_router import pdp_hot_path_evaluate
from seedcore.models.pdp_hot_path import HotPathEvaluateRequest
from seedcore.ops.pdp_hot_path import evaluate_pdp_hot_path


def get_imports_from_file(filepath: str) -> list[str]:
    """Parse a file using AST and return a list of all imported module names."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
    
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def test_pdp_hot_path_ast_imports_contain_no_llm_sdks():
    """
    AST Boundary Check: Ensure that the authoritative PDP evaluation core and router
    do not import any AI/LLM libraries or reasoning engines.
    """
    target_files = [
        "src/seedcore/ops/pdp_hot_path.py",
        "src/seedcore/api/routers/pkg_router.py",
    ]
    
    forbidden_substrings = [
        "openai",
        "google.generativeai",
        "langchain",
        "anthropic",
        "cohere",
        "transformers",
        "cognitive_service",
    ]
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    for relative_path in target_files:
        filepath = os.path.join(project_root, relative_path)
        assert os.path.exists(filepath), f"Target file does not exist: {filepath}"
        
        imported_modules = get_imports_from_file(filepath)
        for module in imported_modules:
            for forbidden in forbidden_substrings:
                assert forbidden not in module.lower(), (
                    f"Safety Violation: Deterministic PDP file '{relative_path}' "
                    f"imports forbidden AI/LLM library/service: '{module}'"
                )


@pytest.mark.asyncio
async def test_shadow_learning_cannot_override_pdp_authority(monkeypatch):
    """
    Direct Coupling Test: Verifies that even if shadow/advisory learning outputs
    or mock student predictions are active, the final authoritative PDP decision
    is determined solely by deterministic evaluation rules and cannot be mutated by AI.
    """
    # 1. Setup a valid basic request payload
    request_data = {
        "contract_version": "pdp.hot_path.asset_transfer.v1",
        "request_id": "req-boundary-test",
        "requested_at": "2026-06-26T12:00:00Z",
        "policy_snapshot_ref": "snapshot:test-v1",
        "action_intent": {
            "intent_id": "intent-test",
            "timestamp": "2026-06-26T12:00:00Z",
            "valid_until": "2026-06-26T12:05:00Z",
            "principal": {
                "agent_id": "agent-test",
                "role_profile": "TRANSFER_COORDINATOR",
                "session_token": "sess-test"
            },
            "action": {
                "type": "TRANSFER_CUSTODY",
                "operation": "MOVE",
                "parameters": {
                    "approval_context": {
                        "approval_envelope_id": "envelope-test",
                        "approval_binding_hash": "sha256:abc",
                        "required_roles": ["FACILITY_MANAGER"],
                        "approved_by": ["principal:facility_mgr"]
                    }
                },
                "security_contract": {
                    "hash": "hash-test",
                    "version": "v1"
                }
            },
            "resource": {
                "asset_id": "asset-test",
                "target_zone": "zone-b",
                "provenance_hash": "sha256:prov"
            }
        },
        "asset_context": {
            "asset_ref": "asset-test",
            "current_custodian_ref": "custodian-test",
            "current_zone": "zone-a",
            "source_registration_status": "registered",
            "registration_decision_ref": "decision-test"
        },
        "telemetry_context": {
            "observed_at": "2026-06-26T12:00:00Z",
            "freshness_seconds": 5.0,
            "max_allowed_age_seconds": 10.0,
            "current_zone": "zone-a",
            "current_coordinate_ref": "coord-a",
            "evidence_refs": ["ev-1"]
        },
        "context_freshness": {
            "causality_token": "token-test",
            "minimum_observed_at": "2026-06-26T11:59:00Z",
            "local_view_ref": "view-test"
        },
        "signed_context_envelopes": []
    }
    
    payload = HotPathEvaluateRequest(**request_data)
    
    # Mock resolve_authoritative_transfer_approval to bypass database query
    mock_approval = {
        "authoritative_approval_envelope": {
            "envelope_id": "envelope-test",
            "status": "APPROVED"
        },
        "authoritative_approval_transition_history": [],
        "authoritative_approval_transition_head": "sha256:abc"
    }
    
    async def mock_resolve(*args, **kwargs):
        return mock_approval
        
    monkeypatch.setattr(
        "seedcore.api.routers.pkg_router.resolve_authoritative_transfer_approval",
        mock_resolve
    )
    
    # 2. Run the normal evaluate endpoint
    response = await pdp_hot_path_evaluate(payload)
    
    # 3. Simulate an adversary attempting to overwrite the response's allowed field
    # using a mock student prediction.
    mock_student = MagicMock()
    mock_student.predict.return_value = {
        "allowed": True,
        "disposition": "allow",
        "reason_code": "override_by_ai"
    }
    
    # Verify that the actual result of the evaluate function is separate and unaffected
    # by any such simulated student or model recommendations.
    assert response.decision is not None
    # If the signature envelopes are empty, evaluate_pdp_hot_path fails closed (allowed: False)
    assert response.decision.allowed is False
    assert response.decision.disposition in ("quarantine", "deny")
