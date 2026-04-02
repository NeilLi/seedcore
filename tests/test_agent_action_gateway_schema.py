from __future__ import annotations

import json
from pathlib import Path


def test_agent_action_gateway_schema_artifact_is_present_and_strict() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "references"
        / "contracts"
        / "seedcore.agent_action_gateway.v1.schema.json"
    )
    assert schema_path.is_file()
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    defs = payload.get("definitions") or {}
    request_schema = defs.get("AgentActionEvaluateRequest") or {}
    props = request_schema.get("properties") or {}
    nested_defs = request_schema.get("$defs") or {}
    principal_ref = (props.get("principal") or {}).get("$ref")
    authority_scope_ref = (props.get("authority_scope") or {}).get("$ref")

    principal_def_name = (
        str(principal_ref).split("/")[-1] if isinstance(principal_ref, str) and principal_ref else None
    )
    authority_scope_def_name = (
        str(authority_scope_ref).split("/")[-1]
        if isinstance(authority_scope_ref, str) and authority_scope_ref
        else None
    )
    principal_props = (
        ((nested_defs.get(principal_def_name) or {}).get("properties") or {})
        if principal_def_name
        else {}
    )
    authority_scope_props = (
        ((nested_defs.get(authority_scope_def_name) or {}).get("properties") or {})
        if authority_scope_def_name
        else {}
    )

    assert props.get("contract_version", {}).get("const") == "seedcore.agent_action_gateway.v1"
    assert principal_def_name == "AgentActionPrincipal"
    assert authority_scope_def_name == "AgentActionAuthorityScope"
    assert "hardware_fingerprint" in principal_props
    assert "owner_id" in principal_props
    assert "delegation_ref" in principal_props
    assert "expected_to_zone" in authority_scope_props
    assert "expected_coordinate_ref" in authority_scope_props
