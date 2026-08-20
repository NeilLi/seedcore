#!/usr/bin/env python3
"""Seed and verify the bounded bootstrap city district in PostgreSQL.

Prerequisites:
- migration 137 applied;
- SEEDCORE_CITY_RUNTIME_PROFILE=bootstrap_sim;
- PostgreSQL connection variables configured for the target local/test DB.

This command replaces only ``fixture:district-01`` rows inside the dedicated
``seedcore_city_foundation`` schema and verifies strict fixture parity.
"""

from __future__ import annotations

import argparse
import json
import os

from seedcore.services.city_foundation_service import (
    CITY_FOUNDATION_STORAGE_ENV,
    CITY_FOUNDATION_STORAGE_POSTGRES,
    CITY_RUNTIME_PROFILE_ENV,
    load_packaged_reference_district,
    load_reference_district,
    persist_reference_district,
    public_discovery_features,
)
from seedcore.services.city_foundation_repository import (
    canonical_reference_district_payload,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        action="store_true",
        help="replace fixture:district-01 transactionally before verification",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if os.getenv(CITY_RUNTIME_PROFILE_ENV) != "bootstrap_sim":
        raise RuntimeError("SEEDCORE_CITY_RUNTIME_PROFILE must be bootstrap_sim")
    if os.getenv(CITY_FOUNDATION_STORAGE_ENV) != CITY_FOUNDATION_STORAGE_POSTGRES:
        raise RuntimeError("SEEDCORE_CITY_FOUNDATION_STORAGE must be postgres")

    packaged = load_packaged_reference_district()
    if args.seed:
        persist_reference_district()
    loaded = load_reference_district()
    if canonical_reference_district_payload(
        packaged
    ) != canonical_reference_district_payload(loaded):
        raise RuntimeError("PostgreSQL reload did not match the expected district")

    public_refs = sorted(
        feature.feature_ref for feature in public_discovery_features(loaded)
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "seeded": args.seed,
                "district_ref": loaded.district_ref,
                "runtime_profile": loaded.runtime_profile,
                "feature_count": len(loaded.feature_records),
                "relationship_count": len(loaded.relationships),
                "public_projection_count": len(public_refs),
                "public_projection_refs": public_refs,
                "authority_effect": "none",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
