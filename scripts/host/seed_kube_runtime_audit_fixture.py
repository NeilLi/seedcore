#!/usr/bin/env python3
"""Seed a runtime-shaped governed_execution_audit record into kube Postgres.

This is intended for deployment verification on fresh/dev topologies where the
runtime has not yet produced any governed audit rows, but we still want to
exercise runtime-backed replay and verification endpoints with a realistic
fixture-derived record.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "demo" / "rct_signoff_v1"
DEFAULT_POSTGRES_SELECTORS = [
    "app=postgres",
    "app.kubernetes.io/name=postgres",
    "app.kubernetes.io/name=postgresql",
    "app=postgresql",
]


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sql_jsonb(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"CAST(convert_from(decode('{encoded}', 'base64'), 'utf8') AS jsonb)"


def _run(
    cmd: list[str],
    *,
    capture: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


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


def _find_postgres_pod(namespace: str, selectors: list[str]) -> str:
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
    raise RuntimeError("unable_to_locate_postgres_pod")


def _load_fixture_record(case_name: str) -> dict:
    fixture_path = FIXTURE_ROOT / case_name / "runtime_replay.json"
    if not fixture_path.exists():
        raise FileNotFoundError(f"fixture runtime replay not found: {fixture_path}")
    payload = json.loads(fixture_path.read_text())
    record = payload.get("view", {}).get("audit_record")
    if not isinstance(record, dict):
        raise ValueError(f"runtime replay fixture missing view.audit_record: {fixture_path}")
    return record


def _build_sql(*, case_name: str, record: dict) -> str:
    audit_id = str(uuid.UUID(str(record["id"])))
    task_id = str(uuid.UUID(str(record["task_id"])))
    intent_id = str(record["intent_id"])
    record_type = str(record["record_type"])
    token_id = record.get("token_id")
    policy_snapshot = record.get("policy_snapshot")
    actor_agent_id = record.get("actor_agent_id")
    actor_organ_id = record.get("actor_organ_id")
    input_hash = record.get("input_hash")
    evidence_hash = record.get("evidence_hash")
    recorded_at = record.get("recorded_at")

    task_params = {
        "seeded_fixture_case": case_name,
        "seed_source": "tests/fixtures/demo/rct_signoff_v1",
        "intent_id": intent_id,
        "audit_id": audit_id,
    }

    return f"""
BEGIN;
WITH ensured_snapshot AS (
    INSERT INTO pkg_snapshots (
        version,
        env,
        entrypoint,
        schema_version,
        checksum,
        is_active,
        notes
    )
    SELECT
        'kube-fixture-{case_name}-' || SUBSTRING(MD5('{audit_id}') FROM 1 FOR 16),
        'prod',
        'data.pkg',
        '1',
        REPEAT('0', 64),
        FALSE,
        'seed_kube_runtime_audit_fixture.py bootstrap'
    WHERE NOT EXISTS (SELECT 1 FROM pkg_snapshots)
    ON CONFLICT (version) DO NOTHING
    RETURNING id
), chosen_snapshot AS (
    SELECT id FROM ensured_snapshot
    UNION ALL
    SELECT id FROM pkg_snapshots ORDER BY id DESC LIMIT 1
)
INSERT INTO tasks (
    id,
    type,
    domain,
    description,
    params,
    snapshot_id,
    status,
    attempts,
    drift_score
)
VALUES (
    CAST('{task_id}' AS uuid),
    'action',
    'verification',
    'Seeded kube verification runtime fixture ({case_name})',
    {_sql_jsonb(task_params)},
    (SELECT id FROM chosen_snapshot LIMIT 1),
    'completed',
    0,
    0.0
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO governed_execution_audit (
    id,
    task_id,
    record_type,
    intent_id,
    token_id,
    policy_snapshot,
    policy_decision,
    action_intent,
    policy_case,
    policy_receipt,
    evidence_bundle,
    actor_agent_id,
    actor_organ_id,
    input_hash,
    evidence_hash,
    recorded_at
)
VALUES (
    CAST('{audit_id}' AS uuid),
    CAST('{task_id}' AS uuid),
    {_sql_str(record_type)},
    {_sql_str(intent_id)},
    {_sql_str(str(token_id) if token_id is not None else None)},
    {_sql_str(str(policy_snapshot) if policy_snapshot is not None else None)},
    {_sql_jsonb(record.get("policy_decision") or {})},
    {_sql_jsonb(record.get("action_intent") or {})},
    {_sql_jsonb(record.get("policy_case") or {})},
    {_sql_jsonb(record.get("policy_receipt") or {})},
    {_sql_jsonb(record.get("evidence_bundle") or {})},
    {_sql_str(str(actor_agent_id) if actor_agent_id is not None else None)},
    {_sql_str(str(actor_organ_id) if actor_organ_id is not None else None)},
    {_sql_str(str(input_hash) if input_hash is not None else None)},
    {_sql_str(str(evidence_hash) if evidence_hash is not None else None)},
    CAST({_sql_str(str(recorded_at) if recorded_at is not None else None)} AS timestamptz)
)
ON CONFLICT (id) DO NOTHING;

SELECT id::text, intent_id, record_type
FROM governed_execution_audit
WHERE id = CAST('{audit_id}' AS uuid);
COMMIT;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed kube Postgres with a fixture-derived governed audit record.")
    parser.add_argument("--namespace", default="seedcore-dev")
    parser.add_argument("--fixture-case", default="allow_case")
    parser.add_argument("--db-name", default="seedcore")
    parser.add_argument("--db-user", default="postgres")
    parser.add_argument("--db-password", default="password")
    parser.add_argument(
        "--postgres-pod-selectors",
        default=",".join(DEFAULT_POSTGRES_SELECTORS),
        help="Comma-separated label selectors tried in order to find the Postgres pod.",
    )
    args = parser.parse_args()

    selectors = [item.strip() for item in args.postgres_pod_selectors.split(",") if item.strip()]
    record = _load_fixture_record(args.fixture_case)
    pod_name = _find_postgres_pod(args.namespace, selectors)
    db_user, db_password, db_name = _discover_working_db_credentials(
        namespace=args.namespace,
        pod_name=pod_name,
        db_name=args.db_name,
        db_user=args.db_user,
        db_password=args.db_password,
    )
    sql = _build_sql(case_name=args.fixture_case, record=record)

    cmd = [
        "kubectl",
        "-n",
        args.namespace,
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
    ]
    result = subprocess.run(
        cmd,
        check=False,
        text=True,
        input=sql,
        capture_output=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"psql_seed_failed (exit={result.returncode})")

    sys.stdout.write(result.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
