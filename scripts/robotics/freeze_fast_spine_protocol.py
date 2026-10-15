#!/usr/bin/env python3
"""Generate/check v1 schemas and a golden authenticated frame. No device I/O."""

from pathlib import Path
import argparse
import json

from seedcore.robotics.fast_spine.contracts import SCHEMAS
from seedcore.robotics.fast_spine.protocol import MessageType, encode_frame

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "packages/robotics-profiles/fast-spine-v1"


def outputs():
    result = {
        name + ".schema.json": model.model_json_schema()
        for name, model in SCHEMAS.items()
    }
    result["wire-golden.json"] = {
        "profile": "test_vector_only",
        "key_hex": ("01" * 32),
        "message_type": "HELLO",
        "sequence": 0,
        "payload": {"profile": "simulation_only"},
        "frame_hex": encode_frame(
            MessageType.HELLO, 0, {"profile": "simulation_only"}, b"\x01" * 32
        ).hex(),
        "warning": "Public test key; never enroll or reuse on a device.",
    }
    result["profile.json"] = {
        "schema_version": "seedcore.fast-spine.profile.v1",
        "release_state": "simulation_only",
        "candidate_board": "ESP32-S3",
        "candidate_servo": "STS3215_TTL",
        "joints": [1, 3],
        "wire": {
            "version": 1,
            "header": "<2sBBIH",
            "magic_ascii": "SC",
            "payload": "canonical_ascii_json",
            "max_payload_bytes": 4096,
            "authentication": "HMAC-SHA256(domain || header || payload)",
            "domain_hex": b"seedcore.fast-spine.wire.v1\x00".hex(),
            "checksum": "CRC32/IEEE(header || payload || mac), little endian",
            "framing": "COBS, zero delimiter",
        },
        "simulated_limits": {
            "duration_ms": 1000,
            "command_timeout_ms": 250,
            "heartbeat_timeout_ms": 300,
            "authority_timeout_ms": 250,
            "watchdog_poll_ms": 5,
            "max_events": 2048,
        },
        "hardware_access": None,
        "board_pinout": None,
        "signer_enrollment": None,
        "controller_parts_bom_target_usd": 12,
        "supplier_quote": None,
        "spending_authorized": False,
        "effort_limit": "One simulation profile; repeated deterministic gate failures require review.",
        "open_gates": [
            "physical watchdog and stopping measurements",
            "TTL bus power and timing",
            "device key enrollment and ingress isolation",
            "ESP-IDF image build and recovery",
            "reviewed supplier quote and physical fixture",
        ],
    }
    return {
        name: json.dumps(data, indent=2, sort_keys=True) + "\n"
        for name, data in result.items()
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write reviewed generated contracts"
    )
    args = parser.parse_args()
    for name, content in outputs().items():
        path = DEST / name
        if args.write:
            DEST.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        elif not path.is_file() or path.read_text() != content:
            raise SystemExit(
                f"Stale contract: {path.relative_to(ROOT)}; review and run --write"
            )
    print("Fast Spine v1 schemas, framing vector and simulation limits match")
