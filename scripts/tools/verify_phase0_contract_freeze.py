#!/usr/bin/env python3
"""Validate Phase 0 contract-freeze closure requirements."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "docs/development/phase0_contract_freeze_manifest.json"
KERNEL_TYPES_FILE = REPO_ROOT / "rust/crates/seedcore-kernel-types/src/lib.rs"
TS_CONTRACTS_FILE = REPO_ROOT / "ts/packages/contracts/src/trustContracts.ts"
FIXTURE_ROOT = REPO_ROOT / "rust/fixtures/transfers"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _expect_path_exists(base: Path, rel_path: str, errors: list[str]) -> None:
    target = base / rel_path
    if not target.exists():
        errors.append(f"missing_path:{rel_path}")


def _assert_rust_public_types(manifest: dict[str, Any], rust_source: str, errors: list[str]) -> None:
    required = manifest["required_rust_public_types"]
    for struct_name in required["structs"]:
        pattern = rf"pub struct {re.escape(struct_name)}\b"
        if not re.search(pattern, rust_source):
            errors.append(f"missing_rust_struct:{struct_name}")
    for enum_name in required["enums"]:
        pattern = rf"pub enum {re.escape(enum_name)}\b"
        if not re.search(pattern, rust_source):
            errors.append(f"missing_rust_enum:{enum_name}")


def _assert_explanation_fields(manifest: dict[str, Any], rust_source: str, errors: list[str]) -> None:
    block_match = re.search(
        r"pub struct ExplanationPayload \{(?P<body>.*?)\n\}",
        rust_source,
        flags=re.DOTALL,
    )
    if not block_match:
        errors.append("missing_explanation_payload_block")
        return
    block = block_match.group("body")
    for field in manifest["required_explanation_fields"]:
        if not re.search(rf"\bpub {re.escape(field)}:", block):
            errors.append(f"missing_explanation_field:{field}")


def _assert_disposition_values(manifest: dict[str, Any], rust_source: str, ts_source: str, errors: list[str]) -> None:
    disposition_block = re.search(
        r"pub enum Disposition \{(?P<body>.*?)\n\}",
        rust_source,
        flags=re.DOTALL,
    )
    if not disposition_block:
        errors.append("missing_disposition_enum_block")
        return
    rust_body = disposition_block.group("body")

    required_dispositions = manifest["required_dispositions"]
    rust_name_map = {
        "allow": "Allow",
        "deny": "Deny",
        "quarantine": "Quarantine",
        "escalate": "Escalate",
    }
    for value in required_dispositions:
        rust_variant = rust_name_map[value]
        if not re.search(rf"\b{rust_variant}\b", rust_body):
            errors.append(f"missing_rust_disposition_variant:{value}")

    ts_disposition_match = re.search(
        r"DISPOSITION_VALUES\s*=\s*\[(?P<body>.*?)\]\s*as const",
        ts_source,
        flags=re.DOTALL,
    )
    if not ts_disposition_match:
        errors.append("missing_ts_disposition_values")
    else:
        ts_body = ts_disposition_match.group("body")
        for value in manifest["required_ts_contract_values"]["dispositions"]:
            if f'"{value}"' not in ts_body:
                errors.append(f"missing_ts_disposition_value:{value}")

    ts_approval_match = re.search(
        r"APPROVAL_STATUS_VALUES\s*=\s*\[(?P<body>.*?)\]\s*as const",
        ts_source,
        flags=re.DOTALL,
    )
    if not ts_approval_match:
        errors.append("missing_ts_approval_status_values")
    else:
        ts_body = ts_approval_match.group("body")
        for value in manifest["required_ts_contract_values"]["approval_statuses"]:
            if f'"{value}"' not in ts_body:
                errors.append(f"missing_ts_approval_status_value:{value}")


def _assert_required_docs(manifest: dict[str, Any], errors: list[str]) -> None:
    for rel_path in manifest["required_docs"]:
        _expect_path_exists(REPO_ROOT, rel_path, errors)


def _assert_transfer_scenarios(manifest: dict[str, Any], errors: list[str]) -> None:
    scenarios: dict[str, Any] = manifest["restricted_custody_transfer_scenarios"]
    for scenario_name, scenario_spec in scenarios.items():
        scenario_dir = FIXTURE_ROOT / scenario_name
        if not scenario_dir.exists():
            errors.append(f"missing_fixture_scenario:{scenario_name}")
            continue

        for filename in scenario_spec["required_files"]:
            file_path = scenario_dir / filename
            if not file_path.exists():
                errors.append(f"missing_fixture_file:{scenario_name}/{filename}")

        token_file = scenario_dir / "expected.execution_token.json"
        if not token_file.exists():
            continue

        try:
            token_value = _load_json(token_file)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid_json:{scenario_name}/expected.execution_token.json:{exc.msg}")
            continue

        expectation = scenario_spec["execution_token_expectation"]
        if expectation == "required_null" and token_value is not None:
            errors.append(f"expected_null_execution_token:{scenario_name}")
        if expectation == "required_object" and not isinstance(token_value, dict):
            errors.append(f"expected_object_execution_token:{scenario_name}")


def run(manifest_path: Path) -> int:
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    if not KERNEL_TYPES_FILE.exists():
        print(f"ERROR: missing rust types file: {KERNEL_TYPES_FILE}", file=sys.stderr)
        return 2
    if not TS_CONTRACTS_FILE.exists():
        print(f"ERROR: missing TypeScript contracts file: {TS_CONTRACTS_FILE}", file=sys.stderr)
        return 2

    manifest = _load_json(manifest_path)
    rust_source = _read_text(KERNEL_TYPES_FILE)
    ts_source = _read_text(TS_CONTRACTS_FILE)
    errors: list[str] = []

    _assert_required_docs(manifest, errors)
    _assert_rust_public_types(manifest, rust_source, errors)
    _assert_explanation_fields(manifest, rust_source, errors)
    _assert_disposition_values(manifest, rust_source, ts_source, errors)
    _assert_transfer_scenarios(manifest, errors)

    if errors:
        print("Phase 0 contract freeze check: FAILED")
        for item in errors:
            print(f"- {item}")
        return 1

    print("Phase 0 contract freeze check: PASS")
    print(f"Manifest: {manifest_path.relative_to(REPO_ROOT)}")
    print(
        "Validated: docs, rust kernel types, TS trust contracts, and restricted custody fixture scenarios."
    )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to phase-0 freeze manifest JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest).expanduser().resolve()
    return run(manifest_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
