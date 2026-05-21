from __future__ import annotations

import ast
import datetime
import json
import os
from typing import Any, Dict

DEFAULTS = {
    "policy": "strict_custody",
    "evidence_required": ["origin_scan", "delivery_scan", "signed_edge_telemetry"],
    "fail_mode": "quarantine",
    "mode": "shadow",
}


def _parse_ast_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.List):
        return [_parse_ast_value(el) for el in node.elts]
    elif isinstance(node, ast.Tuple):
        return tuple(_parse_ast_value(el) for el in node.elts)
    elif isinstance(node, ast.Dict):
        return {
            _parse_ast_value(k): _parse_ast_value(v)
            for k, v in zip(node.keys, node.values)
            if k is not None
        }
    elif isinstance(node, ast.Name):
        return node.id
    return None


def extract_gated_actions_from_file(file_path: str, base_dir: str) -> Dict[str, Any]:
    """Parses a Python file using AST and returns a dictionary of gated actions."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
    except Exception:
        return {}

    actions = {}
    rel_path = os.path.relpath(file_path, base_dir)

    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            for decorator in node.decorator_list:
                is_gated = False
                decorator_call = None

                if isinstance(decorator, ast.Name) and decorator.id == "gated_action":
                    is_gated = True
                elif isinstance(decorator, ast.Attribute) and decorator.attr == "gated_action":
                    is_gated = True
                elif isinstance(decorator, ast.Call):
                    func_node = decorator.func
                    if isinstance(func_node, ast.Name) and func_node.id == "gated_action":
                        is_gated = True
                        decorator_call = decorator
                    elif isinstance(func_node, ast.Attribute) and func_node.attr == "gated_action":
                        is_gated = True
                        decorator_call = decorator

                if is_gated:
                    params = dict(DEFAULTS)
                    if decorator_call:
                        for kw in decorator_call.keywords:
                            if kw.arg is None:
                                continue
                            val = _parse_ast_value(kw.value)
                            if val is not None:
                                params[kw.arg] = val

                    action_id = f"{rel_path}:{node.name}"
                    actions[action_id] = {
                        "function_name": node.name,
                        "file_path": rel_path,
                        "policy": params.get("policy"),
                        "evidence_required": params.get("evidence_required"),
                        "fail_mode": params.get("fail_mode"),
                        "mode": params.get("mode"),
                    }
    return actions


def export_schemas(src_dir: str, output_path: str) -> Dict[str, Any]:
    """Recursively scans a directory for Python files and compiles a gated actions manifest."""
    gated_actions = {}
    for root, _, files in os.walk(src_dir):
        for file in files:
            if file.endswith(".py"):
                full_path = os.path.join(root, file)
                file_actions = extract_gated_actions_from_file(full_path, src_dir)
                gated_actions.update(file_actions)

    manifest = {
        "generator": "seedcore.sdk.schema_exporter",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "gated_actions": gated_actions,
    }

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


if __name__ == "__main__":
    # Self-run defaults to scanning src/ and writing to docs/schemas/
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
    src_dir = os.path.join(project_root, "src")
    output_path = os.path.join(project_root, "docs/schemas/gated_actions_manifest.json")

    print(f"Scanning `{src_dir}` for gated actions...")
    manifest = export_schemas(src_dir, output_path)
    print(f"Exported {len(manifest['gated_actions'])} gated actions to `{output_path}` successfully!")
