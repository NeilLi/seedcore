#!/usr/bin/env python3
"""
Seed/adjust local PKG policy so governed PUBLISH_CONTENT intents route to executable steps.

This script is host-mode oriented:
1) Resolves target snapshot (defaults to active snapshot)
2) Upserts publish-related subtask types with routing/tool hints
3) Replaces the PUBLISH_CONTENT routing rule for the snapshot
4) Optionally compiles and re-activates the snapshot through PKG API
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import requests


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST_ENV = ROOT / "deploy" / "local" / "host-env.sh"
RULE_NAME = "route_publish_content_governed_youtube"


def _run(
    cmd: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=capture,
        check=check,
        input=stdin,
    )


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sql_jsonb(value: Any) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"CAST(convert_from(decode('{encoded}', 'base64'), 'utf8') AS jsonb)"


def _resolve_pg_dsn(explicit_dsn: str | None) -> str:
    if explicit_dsn and explicit_dsn.strip():
        return explicit_dsn.strip()
    env_dsn = os.getenv("PG_DSN", "").strip()
    if env_dsn:
        return env_dsn
    user = os.getenv("POSTGRES_USER", "").strip() or os.getenv("USER", "postgres")
    host = os.getenv("POSTGRES_HOST", "").strip() or "127.0.0.1"
    port = os.getenv("POSTGRES_PORT", "").strip() or "5432"
    db = os.getenv("POSTGRES_DB", "").strip() or "seedcore"
    return f"postgresql://{user}@{host}:{port}/{db}"


def _psql_query(pg_dsn: str, sql: str) -> str:
    res = _run(
        ["psql", pg_dsn, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"psql query failed: {res.stderr.strip()}")
    return res.stdout.strip()


def _psql_exec(pg_dsn: str, sql: str) -> None:
    res = _run(
        ["psql", pg_dsn, "-v", "ON_ERROR_STOP=1"],
        check=False,
        stdin=sql,
    )
    if res.returncode != 0:
        raise RuntimeError(f"psql execution failed: {res.stderr.strip()}")


def _resolve_snapshot(pg_dsn: str, snapshot_id: int | None, snapshot_version: str | None) -> Tuple[int, str]:
    if snapshot_id is not None:
        out = _psql_query(
            pg_dsn,
            f"SELECT id::text || '|' || version FROM pkg_snapshots WHERE id = {int(snapshot_id)} LIMIT 1;",
        )
        if not out:
            raise RuntimeError(f"snapshot id not found: {snapshot_id}")
        sid, version = out.split("|", 1)
        return int(sid), version

    if snapshot_version:
        escaped = snapshot_version.replace("'", "''")
        out = _psql_query(
            pg_dsn,
            f"SELECT id::text || '|' || version FROM pkg_snapshots WHERE version = '{escaped}' LIMIT 1;",
        )
        if not out:
            raise RuntimeError(f"snapshot version not found: {snapshot_version}")
        sid, version = out.split("|", 1)
        return int(sid), version

    out = _psql_query(
        pg_dsn,
        "SELECT id::text || '|' || version FROM pkg_snapshots WHERE is_active = TRUE ORDER BY id DESC LIMIT 1;",
    )
    if not out:
        raise RuntimeError("no active snapshot found")
    sid, version = out.split("|", 1)
    return int(sid), version


def _build_seed_sql(snapshot_id: int) -> str:
    publish_subtask_default = {
        "task_type": "action",
        "allowed_tools": ["youtube.publish_video", "forensic.seal"],
        "executor": {
            "specialization": "generalist",
            "agent_class": "BaseAgent",
            "kind": "agent",
        },
        "routing": {
            "required_specialization": "generalist",
            "tools": ["youtube.publish_video", "forensic.seal"],
            "preferred_organ": "user_experience_organ",
            "hints": {"workflow": "youtube_publish", "governed": True},
        },
        "tool_policy": {"allow": ["youtube.publish_video", "forensic.seal"]},
        "governance": {"intent_type": "PUBLISH_CONTENT"},
    }
    seal_subtask_default = {
        "task_type": "action",
        "allowed_tools": ["forensic.seal"],
        "executor": {
            "specialization": "generalist",
            "agent_class": "BaseAgent",
            "kind": "agent",
        },
        "routing": {
            "required_specialization": "generalist",
            "tools": ["forensic.seal"],
            "preferred_organ": "verification_organ",
            "hints": {"workflow": "youtube_publish", "forensic": True},
        },
        "tool_policy": {"allow": ["forensic.seal"]},
    }
    rule_metadata = {
        "workflow": "creator_publish",
        "intent_type": "PUBLISH_CONTENT",
        "source": "seed_publish_content_pkg_policy.py",
        "zero_trust_boundary": "ActionIntent->PDP->tokenized_handoff",
    }
    emission_publish = {
        "routing": {
            "required_specialization": "generalist",
            "tools": ["youtube.publish_video", "forensic.seal"],
            "hints": {"phase": "publish"},
        }
    }
    emission_seal = {
        "routing": {
            "required_specialization": "generalist",
            "tools": ["forensic.seal"],
            "hints": {"phase": "seal"},
        }
    }
    return f"""
BEGIN;

INSERT INTO pkg_subtask_types (snapshot_id, name, default_params)
VALUES
  ({snapshot_id}, 'publish_youtube_video_governed', {_sql_jsonb(publish_subtask_default)}),
  ({snapshot_id}, 'seal_youtube_publish_forensics', {_sql_jsonb(seal_subtask_default)})
ON CONFLICT (snapshot_id, name)
DO UPDATE SET default_params = EXCLUDED.default_params;

DELETE FROM pkg_policy_rules
WHERE snapshot_id = {snapshot_id}
  AND rule_name = {_sql_str(RULE_NAME)};

WITH inserted_rule AS (
  INSERT INTO pkg_policy_rules (
    snapshot_id, rule_name, priority, rule_source, compiled_rule, engine, metadata, disabled
  )
  VALUES (
    {snapshot_id},
    {_sql_str(RULE_NAME)},
    55,
    {_sql_str('Host policy: route governed PUBLISH_CONTENT intents to publish+forensic execution.')},
    NULL,
    'wasm',
    {_sql_jsonb(rule_metadata)},
    FALSE
  )
  RETURNING id
),
publish_subtask AS (
  SELECT id FROM pkg_subtask_types
  WHERE snapshot_id = {snapshot_id}
    AND name = 'publish_youtube_video_governed'
),
seal_subtask AS (
  SELECT id FROM pkg_subtask_types
  WHERE snapshot_id = {snapshot_id}
    AND name = 'seal_youtube_publish_forensics'
)
INSERT INTO pkg_rule_conditions (rule_id, condition_type, condition_key, operator, value, position)
SELECT id, 'VALUE'::pkg_condition_type, 'context.params.governance.action_intent.action.type', '='::pkg_operator, 'PUBLISH_CONTENT', 0 FROM inserted_rule
UNION ALL
SELECT id, 'VALUE'::pkg_condition_type, 'context.type', '='::pkg_operator, 'action', 1 FROM inserted_rule
UNION ALL
SELECT id, 'VALUE'::pkg_condition_type, 'context.domain', '='::pkg_operator, 'creator', 2 FROM inserted_rule;

WITH inserted_rule AS (
  SELECT id
  FROM pkg_policy_rules
  WHERE snapshot_id = {snapshot_id}
    AND rule_name = {_sql_str(RULE_NAME)}
  ORDER BY created_at DESC
  LIMIT 1
),
publish_subtask AS (
  SELECT id FROM pkg_subtask_types
  WHERE snapshot_id = {snapshot_id}
    AND name = 'publish_youtube_video_governed'
),
seal_subtask AS (
  SELECT id FROM pkg_subtask_types
  WHERE snapshot_id = {snapshot_id}
    AND name = 'seal_youtube_publish_forensics'
)
INSERT INTO pkg_rule_emissions (rule_id, subtask_type_id, relationship_type, params, position)
SELECT r.id, p.id, 'EMITS'::pkg_relation, {_sql_jsonb(emission_publish)}, 0
FROM inserted_rule r CROSS JOIN publish_subtask p
UNION ALL
SELECT r.id, s.id, 'ORDERS'::pkg_relation, {_sql_jsonb(emission_seal)}, 1
FROM inserted_rule r CROSS JOIN seal_subtask s;

COMMIT;
"""


def _post_json(base_url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    res = requests.post(url, json=payload, timeout=60)
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    if res.status_code >= 400:
        raise RuntimeError(f"{path} failed: HTTP {res.status_code} {body}")
    return body


def _compile_and_activate(api_base: str, snapshot_id: int, snapshot_version: str) -> None:
    _post_json(
        api_base,
        f"/api/v1/pkg/snapshots/{snapshot_id}/compile-rules",
        {"entrypoint": "data.pkg.result"},
    )
    _post_json(
        api_base,
        f"/api/v1/pkg/snapshots/{snapshot_version}/activate",
        {
            "actor": "seed_publish_content_pkg_policy.py",
            "reason": "enable_publish_content_youtube_route",
            "target": "router",
            "region": "global",
            "rollout_percent": 100,
            "publish_update": True,
            "edge_targets": [],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed PKG rule for governed PUBLISH_CONTENT YouTube flow")
    parser.add_argument("--pg-dsn", default="", help="Postgres DSN (defaults to PG_DSN env or localhost fallback)")
    parser.add_argument("--snapshot-id", type=int, default=None)
    parser.add_argument("--snapshot-version", default=None)
    parser.add_argument("--seedcore-api", default=os.getenv("SEEDCORE_API_URL", "http://127.0.0.1:8002"))
    parser.add_argument(
        "--compile-activate",
        action="store_true",
        help="Compile rules to WASM and activate the snapshot after seeding.",
    )
    parser.add_argument(
        "--source-host-env",
        action="store_true",
        help="Load deploy/local/host-env.sh in a subshell to resolve DB env vars.",
    )
    args = parser.parse_args()

    if args.source_host_env:
        if not DEFAULT_HOST_ENV.exists():
            raise FileNotFoundError(f"host env file not found: {DEFAULT_HOST_ENV}")
        cmd = (
            f"source {str(DEFAULT_HOST_ENV)!r} >/dev/null 2>&1; "
            "python - <<'PY'\n"
            "import os\n"
            "print(os.getenv('PG_DSN',''))\n"
            "PY"
        )
        res = _run(["bash", "-lc", cmd], check=False)
        if res.returncode == 0 and res.stdout.strip():
            os.environ["PG_DSN"] = res.stdout.strip()

    pg_dsn = _resolve_pg_dsn(args.pg_dsn)
    snapshot_id, snapshot_version = _resolve_snapshot(pg_dsn, args.snapshot_id, args.snapshot_version)

    _psql_exec(pg_dsn, _build_seed_sql(snapshot_id))
    print(f"✅ Seeded PKG publish policy into snapshot id={snapshot_id}, version={snapshot_version}")

    if args.compile_activate:
        _compile_and_activate(args.seedcore_api, snapshot_id, snapshot_version)
        print("✅ Compiled and activated snapshot after seeding.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(1)
