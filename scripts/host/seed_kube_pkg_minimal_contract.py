#!/usr/bin/env python3
"""Seed minimal PKG contract/taxonomy rows for kube hot-path runtime gates.

This script is intentionally topology-focused for deployment verification lanes:
- finds active PKG snapshot (or uses provided snapshot id/version)
- upserts snapshot manifest + minimal taxonomy catalogs
- upserts one governed AllowedOperation fact with constrained transfer checks
- optionally triggers `POST /api/v1/pkg/reload` in-cluster
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POSTGRES_SELECTORS = [
    "app=postgres",
    "app.kubernetes.io/name=postgres",
    "app.kubernetes.io/name=postgresql",
    "app=postgresql",
]
DEFAULT_API_SELECTORS = [
    "app=seedcore-api",
    "app.kubernetes.io/name=seedcore-api",
]


def _run(
    cmd: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        input=stdin,
        capture_output=capture,
    )


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sql_jsonb(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"CAST(convert_from(decode('{encoded}', 'base64'), 'utf8') AS jsonb)"


def _resolve_credential_candidates(
    *,
    db_name: str,
    db_user: str,
    db_password: str,
) -> list[tuple[str, str, str]]:
    candidates = [
        (db_user, db_password, db_name),
        ("postgres", "password", "seedcore"),
        ("postgres", "password", "postgres"),
        ("seedcore", "seedcore", "seedcore"),
        ("seedcore", "seedcore", "postgres"),
    ]
    unique: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in candidates:
        if item in seen:
            continue
        unique.append(item)
        seen.add(item)
    return unique


def _find_pod_by_selectors(namespace: str, selectors: list[str]) -> str:
    for selector in selectors:
        selector = selector.strip()
        if not selector:
            continue
        result = _run(
            [
                "kubectl",
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                selector,
                "-o",
                "jsonpath={.items[0].metadata.name}",
            ],
            check=False,
        )
        if result.returncode != 0:
            continue
        pod_name = result.stdout.strip()
        if pod_name:
            return pod_name
    raise RuntimeError("unable_to_locate_pod_for_selectors")


def _discover_working_db_credentials(
    *,
    namespace: str,
    pod_name: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> tuple[str, str, str]:
    for user, password, name in _resolve_credential_candidates(
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
    ):
        result = _run(
            [
                "kubectl",
                "-n",
                namespace,
                "exec",
                pod_name,
                "--",
                "env",
                f"PGPASSWORD={password}",
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                user,
                "-d",
                name,
                "-Atc",
                "SELECT 1;",
            ],
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            return (user, password, name)
    raise RuntimeError("unable_to_connect_to_postgres_with_known_credentials")


def _psql_query(
    *,
    namespace: str,
    pod_name: str,
    db_user: str,
    db_password: str,
    db_name: str,
    sql: str,
) -> str:
    result = _run(
        [
            "kubectl",
            "-n",
            namespace,
            "exec",
            pod_name,
            "--",
            "env",
            f"PGPASSWORD={db_password}",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            db_user,
            "-d",
            db_name,
            "-At",
            "-c",
            sql,
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql_query_failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _resolve_snapshot(
    *,
    namespace: str,
    pod_name: str,
    db_user: str,
    db_password: str,
    db_name: str,
    snapshot_id: int | None,
    snapshot_version: str | None,
) -> tuple[int, str]:
    if snapshot_id is not None and snapshot_version:
        return snapshot_id, snapshot_version.strip()

    if snapshot_id is not None:
        out = _psql_query(
            namespace=namespace,
            pod_name=pod_name,
            db_user=db_user,
            db_password=db_password,
            db_name=db_name,
            sql=f"SELECT id::text || '|' || version FROM pkg_snapshots WHERE id = {int(snapshot_id)} LIMIT 1;",
        )
        if not out:
            raise RuntimeError(f"snapshot_id_not_found:{snapshot_id}")
        sid, version = out.split("|", 1)
        return int(sid), version

    if snapshot_version:
        escaped = snapshot_version.replace("'", "''")
        out = _psql_query(
            namespace=namespace,
            pod_name=pod_name,
            db_user=db_user,
            db_password=db_password,
            db_name=db_name,
            sql=f"SELECT id::text || '|' || version FROM pkg_snapshots WHERE version = '{escaped}' LIMIT 1;",
        )
        if not out:
            raise RuntimeError(f"snapshot_version_not_found:{snapshot_version}")
        sid, version = out.split("|", 1)
        return int(sid), version

    out = _psql_query(
        namespace=namespace,
        pod_name=pod_name,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
        sql=(
            "SELECT id::text || '|' || version "
            "FROM pkg_snapshots "
            "WHERE is_active = TRUE "
            "ORDER BY id DESC LIMIT 1;"
        ),
    )
    if not out:
        raise RuntimeError("no_active_snapshot")
    sid, version = out.split("|", 1)
    return int(sid), version


def _build_seed_sql(
    *,
    snapshot_id: int,
    snapshot_version: str,
    source_tag: str,
    principal_subject: str,
    resource_ref: str,
    operation: str,
) -> str:
    manifest_json = {
        "source": source_tag,
        "workflow_type": "restricted_custody_transfer",
        "snapshot_version": snapshot_version,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest_json, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    activation_requirements = {
        "requires_compiled_decision_graph": True,
        "requires_authority_state_binding": True,
        "requires_signed_bundle": False,
        "source": source_tag,
    }

    fact_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"seedcore:kube:minimal-contract:{snapshot_id}:{snapshot_version}",
        )
    )

    reason_metadata = {"source": source_tag}
    fact_meta = {"source": source_tag, "purpose": "hot_path_gate"}
    fact_obj = {
        "operation": operation.upper(),
        "resource": resource_ref,
        "effect": "allow",
        "required_current_custodian": True,
        "max_telemetry_age_seconds": 900,
        "require_attestation": True,
        "allow_quarantine": True,
        "zones": ["zone:seedcore-lab-a"],
        "custody_points": ["custody_point:seedcore-gate-a"],
    }
    fact_provenance = {"source": source_tag, "snapshot_id": snapshot_id}

    return f"""
BEGIN;

INSERT INTO pkg_snapshot_manifests (
  snapshot_id,
  workflow_type,
  decision_contract_version,
  request_schema_version,
  evidence_contract_version,
  reason_code_taxonomy_version,
  trust_gap_taxonomy_version,
  obligation_taxonomy_version,
  consistency_contract_version,
  safety_profile,
  requires_signed_bundle,
  requires_compiled_decision_graph,
  requires_authority_state_binding,
  activation_requirements,
  manifest_json,
  manifest_hash
)
VALUES (
  {snapshot_id},
  'restricted_custody_transfer',
  {_sql_str(snapshot_version)},
  {_sql_str(snapshot_version)},
  {_sql_str(snapshot_version)},
  {_sql_str(snapshot_version)},
  {_sql_str(snapshot_version)},
  {_sql_str(snapshot_version)},
  {_sql_str(snapshot_version)},
  {_sql_str(source_tag)},
  FALSE,
  TRUE,
  TRUE,
  {_sql_jsonb(activation_requirements)},
  {_sql_jsonb(manifest_json)},
  {_sql_str(manifest_hash)}
)
ON CONFLICT (snapshot_id) DO UPDATE SET
  workflow_type = EXCLUDED.workflow_type,
  decision_contract_version = EXCLUDED.decision_contract_version,
  request_schema_version = EXCLUDED.request_schema_version,
  evidence_contract_version = EXCLUDED.evidence_contract_version,
  reason_code_taxonomy_version = EXCLUDED.reason_code_taxonomy_version,
  trust_gap_taxonomy_version = EXCLUDED.trust_gap_taxonomy_version,
  obligation_taxonomy_version = EXCLUDED.obligation_taxonomy_version,
  consistency_contract_version = EXCLUDED.consistency_contract_version,
  safety_profile = EXCLUDED.safety_profile,
  requires_signed_bundle = EXCLUDED.requires_signed_bundle,
  requires_compiled_decision_graph = EXCLUDED.requires_compiled_decision_graph,
  requires_authority_state_binding = EXCLUDED.requires_authority_state_binding,
  activation_requirements = EXCLUDED.activation_requirements,
  manifest_json = EXCLUDED.manifest_json,
  manifest_hash = EXCLUDED.manifest_hash,
  updated_at = NOW();

INSERT INTO pkg_reason_codes (
  snapshot_id, taxonomy_version, code, disposition_family, severity, operator_message, machine_category, metadata, deprecated
) VALUES (
  {snapshot_id},
  {_sql_str(snapshot_version)},
  'hot_path_dependency_unavailable',
  'quarantine',
  'high',
  'Hot-path dependency is unavailable in current topology.',
  'runtime_dependency',
  {_sql_jsonb(reason_metadata)},
  FALSE
)
ON CONFLICT (snapshot_id, taxonomy_version, code) DO UPDATE SET
  disposition_family = EXCLUDED.disposition_family,
  severity = EXCLUDED.severity,
  operator_message = EXCLUDED.operator_message,
  machine_category = EXCLUDED.machine_category,
  metadata = EXCLUDED.metadata,
  deprecated = EXCLUDED.deprecated;

INSERT INTO pkg_trust_gap_codes (
  snapshot_id, taxonomy_version, code, disposition_family, severity, operator_message, machine_category, metadata, deprecated
) VALUES
  ({snapshot_id}, {_sql_str(snapshot_version)}, 'missing_current_custodian', 'quarantine', 'high', 'Asset current custodian is missing.', 'trust_gap', {_sql_jsonb(reason_metadata)}, FALSE),
  ({snapshot_id}, {_sql_str(snapshot_version)}, 'stale_telemetry', 'quarantine', 'high', 'Telemetry evidence is stale.', 'trust_gap', {_sql_jsonb(reason_metadata)}, FALSE)
ON CONFLICT (snapshot_id, taxonomy_version, code) DO UPDATE SET
  disposition_family = EXCLUDED.disposition_family,
  severity = EXCLUDED.severity,
  operator_message = EXCLUDED.operator_message,
  machine_category = EXCLUDED.machine_category,
  metadata = EXCLUDED.metadata,
  deprecated = EXCLUDED.deprecated;

INSERT INTO pkg_obligation_codes (
  snapshot_id, taxonomy_version, code, disposition_family, severity, operator_message, machine_category, metadata, deprecated
) VALUES
  ({snapshot_id}, {_sql_str(snapshot_version)}, 'update_verification_surface', 'general', 'medium', 'Refresh verification surface after custody transfer decision.', 'obligation', {_sql_jsonb(reason_metadata)}, FALSE),
  ({snapshot_id}, {_sql_str(snapshot_version)}, 'attach_telemetry_proof', 'general', 'medium', 'Attach telemetry proof bundle before completion.', 'obligation', {_sql_jsonb(reason_metadata)}, FALSE)
ON CONFLICT (snapshot_id, taxonomy_version, code) DO UPDATE SET
  disposition_family = EXCLUDED.disposition_family,
  severity = EXCLUDED.severity,
  operator_message = EXCLUDED.operator_message,
  machine_category = EXCLUDED.machine_category,
  metadata = EXCLUDED.metadata,
  deprecated = EXCLUDED.deprecated;

INSERT INTO facts (
  id,
  text,
  tags,
  meta_data,
  snapshot_id,
  namespace,
  subject,
  predicate,
  object_data,
  valid_from,
  valid_to,
  created_by,
  pkg_rule_id,
  pkg_provenance,
  validation_status
) VALUES (
  {_sql_str(fact_id)}::uuid,
  'Seeded minimal constrained allowed operation for RCT hot-path gate',
  ARRAY['allowedoperation','rct','seeded'],
  {_sql_jsonb(fact_meta)},
  {snapshot_id},
  'default',
  {_sql_str(principal_subject)},
  'AllowedOperation',
  {_sql_jsonb(fact_obj)},
  NOW() - INTERVAL '1 minute',
  NULL,
  {_sql_str(source_tag)},
  'rct_seed_minimal_rule',
  {_sql_jsonb(fact_provenance)},
  'pkg_validated'
)
ON CONFLICT (id) DO UPDATE SET
  text = EXCLUDED.text,
  tags = EXCLUDED.tags,
  meta_data = EXCLUDED.meta_data,
  snapshot_id = EXCLUDED.snapshot_id,
  namespace = EXCLUDED.namespace,
  subject = EXCLUDED.subject,
  predicate = EXCLUDED.predicate,
  object_data = EXCLUDED.object_data,
  valid_from = EXCLUDED.valid_from,
  valid_to = EXCLUDED.valid_to,
  created_by = EXCLUDED.created_by,
  pkg_rule_id = EXCLUDED.pkg_rule_id,
  pkg_provenance = EXCLUDED.pkg_provenance,
  validation_status = EXCLUDED.validation_status,
  updated_at = NOW();

COMMIT;

SELECT
  {snapshot_id}::text AS snapshot_id,
  {_sql_str(snapshot_version)}::text AS snapshot_version,
  (SELECT count(*) FROM pkg_reason_codes WHERE snapshot_id = {snapshot_id})::text AS reason_count,
  (SELECT count(*) FROM pkg_trust_gap_codes WHERE snapshot_id = {snapshot_id})::text AS trust_gap_count,
  (SELECT count(*) FROM pkg_obligation_codes WHERE snapshot_id = {snapshot_id})::text AS obligation_count,
  (SELECT count(*) FROM facts WHERE snapshot_id = {snapshot_id} AND namespace = 'default' AND pkg_rule_id IS NOT NULL)::text AS governed_fact_count;
"""


def _seed_contract_rows(
    *,
    namespace: str,
    pod_name: str,
    db_user: str,
    db_password: str,
    db_name: str,
    sql: str,
) -> str:
    result = _run(
        [
            "kubectl",
            "-n",
            namespace,
            "exec",
            "-i",
            pod_name,
            "--",
            "env",
            f"PGPASSWORD={db_password}",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            db_user,
            "-d",
            db_name,
            "-At",
            "-f",
            "-",
        ],
        check=False,
        stdin=sql,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql_seed_failed:{result.stderr.strip()}")
    return result.stdout


def _reload_runtime(namespace: str, api_pod: str) -> tuple[dict, dict]:
    reload_res = _run(
        [
            "kubectl",
            "-n",
            namespace,
            "exec",
            api_pod,
            "--",
            "curl",
            "-fsS",
            "-X",
            "POST",
            "http://127.0.0.1:8002/api/v1/pkg/reload",
            "-H",
            "Content-Type: application/json",
            "-d",
            "{}",
        ],
        check=False,
    )
    if reload_res.returncode != 0:
        raise RuntimeError(f"pkg_reload_failed:{reload_res.stderr.strip()}")
    status_res = _run(
        [
            "kubectl",
            "-n",
            namespace,
            "exec",
            api_pod,
            "--",
            "curl",
            "-fsS",
            "http://127.0.0.1:8002/api/v1/pdp/hot-path/status",
        ],
        check=False,
    )
    if status_res.returncode != 0:
        raise RuntimeError(f"hot_path_status_failed:{status_res.stderr.strip()}")
    pkg_status_res = _run(
        [
            "kubectl",
            "-n",
            namespace,
            "exec",
            api_pod,
            "--",
            "curl",
            "-fsS",
            "http://127.0.0.1:8002/api/v1/pkg/status",
        ],
        check=False,
    )
    if pkg_status_res.returncode != 0:
        raise RuntimeError(f"pkg_status_failed:{pkg_status_res.stderr.strip()}")
    return json.loads(status_res.stdout), json.loads(pkg_status_res.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed minimal PKG manifest/taxonomy/governed-fact rows on kube Postgres.",
    )
    parser.add_argument("--namespace", default="seedcore-dev")
    parser.add_argument("--db-name", default="seedcore")
    parser.add_argument("--db-user", default="postgres")
    parser.add_argument("--db-password", default="password")
    parser.add_argument(
        "--postgres-pod-selectors",
        default=",".join(DEFAULT_POSTGRES_SELECTORS),
        help="Comma-separated selectors for Postgres pod discovery.",
    )
    parser.add_argument(
        "--api-pod-selectors",
        default=",".join(DEFAULT_API_SELECTORS),
        help="Comma-separated selectors for seedcore-api pod discovery.",
    )
    parser.add_argument("--snapshot-id", type=int, default=None)
    parser.add_argument("--snapshot-version", default=None)
    parser.add_argument("--source-tag", default="seed_minimal_contract")
    parser.add_argument("--principal-subject", default="principal:seedcore-gate-agent")
    parser.add_argument("--resource-ref", default="asset:rct-seeded-asset-001")
    parser.add_argument("--operation", default="MOVE")
    parser.add_argument("--skip-reload", action="store_true")
    args = parser.parse_args()

    pg_selectors = [item.strip() for item in args.postgres_pod_selectors.split(",") if item.strip()]
    api_selectors = [item.strip() for item in args.api_pod_selectors.split(",") if item.strip()]

    pg_pod = _find_pod_by_selectors(args.namespace, pg_selectors)
    db_user, db_password, db_name = _discover_working_db_credentials(
        namespace=args.namespace,
        pod_name=pg_pod,
        db_name=args.db_name,
        db_user=args.db_user,
        db_password=args.db_password,
    )
    snapshot_id, snapshot_version = _resolve_snapshot(
        namespace=args.namespace,
        pod_name=pg_pod,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
        snapshot_id=args.snapshot_id,
        snapshot_version=args.snapshot_version,
    )

    sql = _build_seed_sql(
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        source_tag=args.source_tag,
        principal_subject=args.principal_subject,
        resource_ref=args.resource_ref,
        operation=args.operation,
    )
    out = _seed_contract_rows(
        namespace=args.namespace,
        pod_name=pg_pod,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
        sql=sql,
    )
    sys.stdout.write(out)

    if args.skip_reload:
        return 0

    api_pod = _find_pod_by_selectors(args.namespace, api_selectors)
    hot_path_status, pkg_status = _reload_runtime(args.namespace, api_pod)
    summary = {
        "runtime_ready": bool(hot_path_status.get("runtime_ready")),
        "authz_graph_ready": bool(hot_path_status.get("authz_graph_ready")),
        "restricted_transfer_ready": bool(hot_path_status.get("restricted_transfer_ready")),
        "active_snapshot_version": hot_path_status.get("active_snapshot_version"),
        "pkg_active_version": pkg_status.get("active_version"),
        "pkg_authz_graph_ready": bool(pkg_status.get("authz_graph_ready")),
    }
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
