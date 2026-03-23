#!/usr/bin/env python3
"""Run a local authz engine parity check against a snapshot-scoped fixture matrix."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import seedcore.coordinator.core.governance as governance_mod
from seedcore.ops.pkg.authz_graph import AuthzGraphCompiler, AuthzGraphProjector
from seedcore.ops.pkg.authz_parity_service import AuthzParityFixture, AuthzParityService


def _load_fixtures() -> list[AuthzParityFixture]:
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "authz_parity" / "basic_matrix.json"
    raw = json.loads(fixture_path.read_text())
    return [
        AuthzParityFixture(
            name=item["name"],
            payload=item["payload"],
            metadata=item.get("metadata") or {},
        )
        for item in raw
    ]


def _build_compiled_index():
    canonical_resource_uri = "seedcore://zones/vault-a/assets/asset-1"
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="authz-parity@host",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
            {
                "id": "fact-zone",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": canonical_resource_uri,
                "predicate": "locatedInZone",
                "object_data": {"zone": "vault-a"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:ROBOT_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MUTATE",
                    "resource": canonical_resource_uri,
                    "zones": ["vault-a"],
                },
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
        ],
    )
    return AuthzGraphCompiler().compile(graph)


def main() -> int:
    fixtures = _load_fixtures()
    compiled = _build_compiled_index()

    stale_now = datetime(2099, 3, 20, 12, 0, 1, tzinfo=timezone.utc)
    os.environ["SEEDCORE_PDP_MAX_INTENT_AGE_MS"] = "500"
    governance_mod._utcnow = lambda: stale_now  # type: ignore[assignment]

    report = AuthzParityService().compare_fixtures(
        compiled_authz_index=compiled,
        fixtures=fixtures,
    )

    print(
        json.dumps(
            {
                "snapshot_ref": report.snapshot_ref,
                "snapshot_version": report.snapshot_version,
                "total": report.total,
                "parity_ok": report.parity_ok,
                "mismatched": report.mismatched,
            },
            indent=2,
        )
    )
    for result in report.results:
        marker = "PASS" if result.parity_ok else "FAIL"
        print(
            f"[{marker}] {result.fixture_name}: "
            f"{json.dumps({'mismatches': result.mismatches, 'baseline': result.baseline.__dict__, 'candidate': result.candidate.__dict__}, sort_keys=True)}"
        )

    return 0 if report.mismatched == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
