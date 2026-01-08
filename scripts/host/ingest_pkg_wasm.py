#!/usr/bin/env python3
"""
PKG WASM Ingestion Script

Ingests a WASM file into the PKG database as a new snapshot.
This implements the DB-first model where the database is the source of truth.

Usage:
    python ingest_pkg_wasm.py \
        --wasm /path/to/policy_rules.wasm \
        --version rules@1.4.0 \
        --env prod \
        --activate

Or via environment variables:
    PKG_WASM_FILE=/path/to/policy_rules.wasm
    PKG_VERSION=rules@1.4.0
    PKG_ENV=prod
    PKG_ACTIVATE=true
    python ingest_pkg_wasm.py
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import text

from seedcore.database import get_async_pg_session_factory


async def ingest_wasm_snapshot(
    wasm_file: Path,
    version: str,
    env: str = "prod",
    activate: bool = False,
    entrypoint: str = "data.pkg",
    notes: Optional[str] = None,
) -> int:
    """
    Ingest a WASM file into the PKG database.

    Args:
        wasm_file: Path to WASM binary file
        version: Version string (e.g., 'rules@1.4.0')
        env: Environment ('prod', 'staging', 'dev')
        activate: Whether to mark this snapshot as active
        entrypoint: OPA/Rego entrypoint (default: 'data.pkg')
        notes: Optional notes about this snapshot

    Returns:
        Snapshot ID
    """
    if not wasm_file.exists():
        raise FileNotFoundError(f"WASM file not found: {wasm_file}")

    # Read WASM file and calculate checksum
    print(f"📦 Reading WASM file: {wasm_file}")
    wasm_bytes = wasm_file.read_bytes()
    wasm_size = len(wasm_bytes)

    # Calculate SHA256 checksum (64 hex chars)
    sha256_hash = hashlib.sha256(wasm_bytes).hexdigest()
    print(f"✅ Calculated SHA256: {sha256_hash[:16]}... ({wasm_size} bytes)")

    # Validate env
    if env not in ("prod", "staging", "dev"):
        raise ValueError(f"Invalid env: {env}. Must be 'prod', 'staging', or 'dev'")

    session_factory = get_async_pg_session_factory()

    async with session_factory() as session:
        async with session.begin():  # Transaction
            # Check if version already exists
            check_sql = text("""
                SELECT id FROM pkg_snapshots WHERE version = :version
            """)
            check_res = await session.execute(check_sql, {"version": version})
            existing = await check_res.first()
            if existing:
                raise ValueError(
                    f"Snapshot version '{version}' already exists (id={existing[0]})"
                )

            # Insert snapshot
            insert_snapshot_sql = text("""
                INSERT INTO pkg_snapshots 
                    (version, env, entrypoint, checksum, size_bytes, is_active, notes)
                VALUES 
                    (:version, :env::pkg_env, :entrypoint, :checksum, :size_bytes, :is_active, :notes)
                RETURNING id
            """)
            snapshot_res = await session.execute(
                insert_snapshot_sql,
                {
                    "version": version,
                    "env": env,
                    "entrypoint": entrypoint,
                    "checksum": sha256_hash,
                    "size_bytes": wasm_size,
                    "is_active": activate,
                    "notes": notes,
                },
            )
            snapshot_id = await snapshot_res.scalar()
            print(f"✅ Created snapshot: id={snapshot_id}, version={version}")

            # If activating, deactivate other snapshots in the same env
            if activate:
                deactivate_sql = text("""
                    UPDATE pkg_snapshots 
                    SET is_active = FALSE 
                    WHERE env = :env::pkg_env AND is_active = TRUE AND id != :snapshot_id
                """)
                await session.execute(deactivate_sql, {"env": env, "snapshot_id": snapshot_id})
                print(f"✅ Deactivated other snapshots in env={env}")

            # Insert artifact
            insert_artifact_sql = text("""
                INSERT INTO pkg_snapshot_artifacts
                    (snapshot_id, artifact_type, artifact_bytes, sha256, created_by)
                VALUES
                    (:snapshot_id, 'wasm_pack'::pkg_artifact_type, :artifact_bytes, :sha256, 'ingest_script')
            """)
            await session.execute(
                insert_artifact_sql,
                {
                    "snapshot_id": snapshot_id,
                    "artifact_bytes": wasm_bytes,
                    "sha256": sha256_hash,
                },
            )
            print(f"✅ Inserted WASM artifact for snapshot {snapshot_id}")

            return snapshot_id


async def main():
    parser = argparse.ArgumentParser(
        description="Ingest PKG WASM file into database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic ingestion
  python ingest_pkg_wasm.py --wasm policy_rules.wasm --version rules@1.4.0

  # Ingest and activate
  python ingest_pkg_wasm.py --wasm policy_rules.wasm --version rules@1.4.0 --activate

  # Staging environment
  python ingest_pkg_wasm.py --wasm policy_rules.wasm --version rules@1.4.0 --env staging --activate

Environment Variables:
  PKG_WASM_FILE    Path to WASM file
  PKG_VERSION      Version string
  PKG_ENV          Environment (prod/staging/dev)
  PKG_ACTIVATE     Set to 'true' to activate snapshot
        """,
    )

    parser.add_argument(
        "--wasm",
        type=Path,
        default=os.getenv("PKG_WASM_FILE"),
        help="Path to WASM file (or set PKG_WASM_FILE)",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=os.getenv("PKG_VERSION"),
        help="Version string, e.g., 'rules@1.4.0' (or set PKG_VERSION)",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=os.getenv("PKG_ENV", "prod"),
        choices=["prod", "staging", "dev"],
        help="Environment (default: prod)",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        default=os.getenv("PKG_ACTIVATE", "").lower() == "true",
        help="Mark snapshot as active (deactivates others in same env)",
    )
    parser.add_argument(
        "--entrypoint",
        type=str,
        default="data.pkg",
        help="OPA/Rego entrypoint (default: data.pkg)",
    )
    parser.add_argument(
        "--notes",
        type=str,
        default=None,
        help="Optional notes about this snapshot",
    )

    args = parser.parse_args()

    if not args.wasm:
        parser.error("--wasm is required (or set PKG_WASM_FILE)")
    if not args.version:
        parser.error("--version is required (or set PKG_VERSION)")

    try:
        snapshot_id = await ingest_wasm_snapshot(
            wasm_file=args.wasm,
            version=args.version,
            env=args.env,
            activate=args.activate,
            entrypoint=args.entrypoint,
            notes=args.notes,
        )
        print(f"\n🎉 Successfully ingested snapshot id={snapshot_id}, version={args.version}")
        if args.activate:
            print(f"✅ Snapshot is now active in env={args.env}")
        else:
            print("ℹ️  Snapshot is not active. Activate with:")
            print(f"   SELECT pkg_promote_snapshot({snapshot_id}, '{args.env}'::pkg_env, 'admin', 'Manual activation');")
        return 0
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
