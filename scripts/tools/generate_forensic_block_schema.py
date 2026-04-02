from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from seedcore.ops.evidence.forensic_block_contract import (  # noqa: E402
    FORENSIC_BLOCK_CONTEXT,
    FORENSIC_BLOCK_JSON_SCHEMA,
)

CONTRACT_DIR = ROOT / "docs" / "references" / "contracts"
SCHEMA_PATH = CONTRACT_DIR / "seedcore.forensic_block.v1.schema.json"
EXAMPLE_PATH = CONTRACT_DIR / "seedcore.forensic_block.v1.example.json"


EXAMPLE_PAYLOAD = {
    "@context": FORENSIC_BLOCK_CONTEXT,
    "@type": "ForensicBlock",
    "forensic_block_id": "fb-2026-0001",
    "block_header": {
        "forensic_block_id": "fb-2026-0001",
        "audit_id": "6f9dfaf0-95c3-41fb-befd-e0825db0ca38",
        "timestamp": "2026-04-02T12:00:00Z",
        "version": "seedcore.forensic_block.v1",
    },
    "decision_linkage": {
        "request_id": "req-transfer-2026-0001",
        "disposition": "ALLOW",
        "decision_hash": "sha256:decision-2026-0001",
        "policy_receipt_id": "policy-receipt-2026-0001",
        "policy_snapshot_ref": "snapshot:rct-2026-04-02",
    },
    "asset_identity": {
        "asset_id": "asset:lot-8841",
        "lot_id": "lot-8841",
        "product_ref": "sku:cocoa-bar-72",
        "quote_ref": "quote-2026-0001",
    },
    "authority_context": {
        "@type": "DelegatedAuthority",
        "principal_id": "did:seedcore:assistant:buyer-bot-77",
        "owner_id": "did:seedcore:owner:acme-001",
        "hardware_fingerprint": "sha256:hardware-fingerprint-0001",
        "kms_key_ref": "kms://seedcore/verify/hsm-key-001",
        "delegation_chain_hash": "sha256:delegation-chain-0001",
        "execution_token_id": "token-transfer-2026-0001",
        "organization_ref": "org:acme",
    },
    "fingerprint_components": {
        "economic_hash": "sha256:economic-0001",
        "physical_presence_hash": "sha256:physical-0001",
        "reasoning_hash": "sha256:reasoning-0001",
        "actuator_hash": "sha256:actuator-0001",
    },
    "economic_evidence": {
        "@type": "CommerceTransaction",
        "platform": "seedcore_rct",
        "transaction_hash": "sha256:economic-0001",
        "asset_identity": "asset:lot-8841",
    },
    "spatial_evidence": {
        "@type": "PhysicalPresence",
        "coordinate_binding": {
            "coordinate_ref": "coord:warehouse-a:slot-12",
            "system": "seedcore",
        },
        "presence_proof_hash": "sha256:physical-0001",
        "current_zone": "vault-a",
    },
    "cognitive_evidence": {
        "@type": "PolicyReasoning",
        "decision": "ALLOW",
        "reasoning_trace_hash": "sha256:reasoning-0001",
    },
    "physical_evidence": {
        "@type": "ActuatorProof",
        "actuator_telemetry": {
            "motor_torque_hash": "sha256:actuator-0001",
        },
    },
}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> None:
    _write(SCHEMA_PATH, FORENSIC_BLOCK_JSON_SCHEMA)
    _write(EXAMPLE_PATH, EXAMPLE_PAYLOAD)
    print(f"Wrote {SCHEMA_PATH}")
    print(f"Wrote {EXAMPLE_PATH}")


if __name__ == "__main__":
    main()
