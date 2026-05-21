from __future__ import annotations

import json

from seedcore.sdk.schema_exporter import (
    extract_gated_actions_from_file,
    export_schemas,
)


def test_extract_gated_actions_from_file(tmp_path):
    # 1. Create a temporary Python file with some mock gated actions
    temp_file = tmp_path / "mock_service.py"
    temp_file.write_text("""
from seedcore.sdk import gated_action

@gated_action(
    policy="strict_custody",
    evidence_required=["origin_scan"],
    fail_mode="deny",
    mode="enforce",
)
def transfer_assets(intent: dict):
    return "done"

@gated_action()
def default_gated_action(intent: dict):
    pass

def normal_function():
    pass
""", encoding="utf-8")

    # 2. Extract gated actions from the temporary file
    actions = extract_gated_actions_from_file(str(temp_file), str(tmp_path))

    # 3. Assert correct extraction
    assert len(actions) == 2
    assert "mock_service.py:transfer_assets" in actions
    assert "mock_service.py:default_gated_action" in actions
    assert "normal_function" not in actions

    # Verify custom arguments
    assert actions["mock_service.py:transfer_assets"] == {
        "function_name": "transfer_assets",
        "file_path": "mock_service.py",
        "policy": "strict_custody",
        "evidence_required": ["origin_scan"],
        "fail_mode": "deny",
        "mode": "enforce",
    }

    # Verify defaults are merged correctly
    assert actions["mock_service.py:default_gated_action"] == {
        "function_name": "default_gated_action",
        "file_path": "mock_service.py",
        "policy": "strict_custody",
        "evidence_required": ["origin_scan", "delivery_scan", "signed_edge_telemetry"],
        "fail_mode": "quarantine",
        "mode": "shadow",
    }


def test_export_schemas_writes_valid_json_manifest(tmp_path):
    # 1. Setup temporary directories for src and docs
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    docs_dir = tmp_path / "docs" / "schemas"

    # Create nested python files
    sub_dir = src_dir / "services"
    sub_dir.mkdir()

    file_a = src_dir / "app.py"
    file_a.write_text("""
from seedcore.sdk import gated_action
@gated_action(policy="strict_custody")
def run_app():
    pass
""", encoding="utf-8")

    file_b = sub_dir / "handler.py"
    file_b.write_text("""
from seedcore.sdk import gated_action
@gated_action(fail_mode="escalate", mode="enforce")
def handle_incoming():
    pass
""", encoding="utf-8")

    output_json = docs_dir / "gated_actions_manifest.json"

    # 2. Run the exporter
    manifest = export_schemas(str(src_dir), str(output_json))

    # 3. Verify manifest contents
    assert manifest["generator"] == "seedcore.sdk.schema_exporter"
    assert "generated_at" in manifest
    assert len(manifest["gated_actions"]) == 2

    assert "app.py:run_app" in manifest["gated_actions"]
    assert manifest["gated_actions"]["app.py:run_app"] == {
        "function_name": "run_app",
        "file_path": "app.py",
        "policy": "strict_custody",
        "evidence_required": ["origin_scan", "delivery_scan", "signed_edge_telemetry"],
        "fail_mode": "quarantine",
        "mode": "shadow",
    }

    assert "services/handler.py:handle_incoming" in manifest["gated_actions"]
    assert manifest["gated_actions"]["services/handler.py:handle_incoming"] == {
        "function_name": "handle_incoming",
        "file_path": "services/handler.py",
        "policy": "strict_custody",
        "evidence_required": ["origin_scan", "delivery_scan", "signed_edge_telemetry"],
        "fail_mode": "escalate",
        "mode": "enforce",
    }

    # 4. Verify file was written correctly
    assert output_json.exists()
    with open(output_json, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == manifest


def test_export_schemas_keeps_duplicate_function_names_distinct(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    nested_dir = src_dir / "service"
    nested_dir.mkdir()

    (src_dir / "a.py").write_text("""
from seedcore.sdk import gated_action
@gated_action(fail_mode="deny")
def transfer():
    pass
""", encoding="utf-8")
    (nested_dir / "b.py").write_text("""
from seedcore.sdk import gated_action
@gated_action(fail_mode="escalate")
async def transfer():
    pass
""", encoding="utf-8")

    output_json = tmp_path / "manifest.json"
    manifest = export_schemas(str(src_dir), str(output_json))

    assert set(manifest["gated_actions"]) == {"a.py:transfer", "service/b.py:transfer"}
    assert manifest["gated_actions"]["a.py:transfer"]["fail_mode"] == "deny"
    assert manifest["gated_actions"]["service/b.py:transfer"]["fail_mode"] == "escalate"
