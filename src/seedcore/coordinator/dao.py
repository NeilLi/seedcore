from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence
import inspect
import json
import logging
import os
import uuid
from sqlalchemy import text  # pyright: ignore[reportMissingImports]


MAX_PROTO_PLAN_BYTES = int(os.getenv("MAX_PROTO_PLAN_BYTES", str(256 * 1024)))

logger = logging.getLogger(__name__)


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


class TaskRouterTelemetryDAO:
    """Lightweight helper for persisting router telemetry snapshots."""

    def __init__(self, table_name: str = "task_router_telemetry") -> None:
        self._table_name = table_name

    async def insert(
        self,
        session,
        *,
        task_id: str,
        surprise_score: float,
        x_vector: Sequence[float],
        weights: Sequence[float],
        ocps_metadata: Dict[str, Any],
        chosen_route: str,
    ) -> None:
        stmt = text(
            f"""
            INSERT INTO {self._table_name}
            (task_id, surprise_score, x_vector, weights, ocps_metadata, chosen_route)
            VALUES (CAST(:task_id AS uuid), :surprise_score, CAST(:x_vector AS jsonb), CAST(:weights AS jsonb), CAST(:ocps_metadata AS jsonb), :chosen_route)
            """
        )
        await session.execute(
            stmt,
            {
                "task_id": task_id,
                "surprise_score": surprise_score,
                "x_vector": json.dumps(list(x_vector), sort_keys=True),
                "weights": json.dumps(list(weights), sort_keys=True),
                "ocps_metadata": json.dumps(dict(ocps_metadata or {}), sort_keys=True),
                "chosen_route": chosen_route,
            },
        )



class TaskOutboxDAO:
    """DAO for managing coordinator outbox events (enqueue, list, delete, backoff).

    Implements the Outbox Pattern to ensure reliable, decoupled communication
    between the coordinator and downstream task processors.

    Lifecycle:
      1. enqueue_nim_task_embed() — write event to outbox
      2. list_pending_nim_task_embeds() — read pending events
      3. delete() — remove processed event
      4. backoff() — defer retry for failed event
    """

    _TABLE_NAME = "task_outbox"

    async def enqueue_nim_task_embed(
        self,
        session,
        *,
        task_id: str,
        reason: str = "coordinator",
        dedupe_key: Optional[str] = None,
    ) -> bool:
        """Insert a 'nim_task_embed' event into the outbox.

        Args:
            session: Active database session.
            task_id: The UUID of the related task.
            reason: Origin or cause of the enqueue (default: 'coordinator').
            dedupe_key: Optional key for idempotent insert.

        Returns:
            True if the event was inserted, False if skipped due to deduplication.
        """
        payload = {"reason": reason, "task_id": task_id}
        encoded_payload = json.dumps(payload, sort_keys=True)

        if len(encoded_payload.encode("utf-8")) > MAX_PROTO_PLAN_BYTES:
            logger.warning(
                "[Coordinator] Outbox payload for %s exceeded %s bytes; truncating.",
                task_id,
                MAX_PROTO_PLAN_BYTES,
            )
            encoded_payload = json.dumps(
                {"reason": reason, "task_id": task_id, "_truncated": True},
                sort_keys=True,
            )

        stmt = text(
            """
            INSERT INTO task_outbox (task_id, event_type, payload, dedupe_key)
            VALUES (CAST(:task_id AS uuid), :event_type, CAST(:payload AS jsonb), :dedupe_key)
            ON CONFLICT (dedupe_key) DO NOTHING
            """
        )

        result = await session.execute(
            stmt,
            {
                "task_id": task_id,
                "event_type": "nim_task_embed",
                "payload": encoded_payload,
                "dedupe_key": dedupe_key,
            },
        )

        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, (int, float)):
            inserted = rowcount > 0
        elif hasattr(result, "fetchone"):
            try:
                inserted = bool(result.fetchone())
            except Exception:  # pragma: no cover - defensive for mocks only
                inserted = False
        else:
            inserted = False
        if inserted:
            logger.debug(f"[Coordinator] Enqueued nim_task_embed for {task_id}")
        else:
            logger.debug(f"[Coordinator] Skipped duplicate nim_task_embed for {task_id}")
        return inserted

    async def enqueue_embed_task(
        self,
        session,
        *,
        task_id: str,
        reason: str = "coordinator",
        dedupe_key: Optional[str] = None,
    ) -> bool:
        """Backward-compatible alias for legacy enqueue method."""
        return await self.enqueue_nim_task_embed(
            session,
            task_id=task_id,
            reason=reason,
            dedupe_key=dedupe_key,
        )

    async def list_pending_nim_task_embeds(self, session, limit: int = 100) -> List[Any]:
        """Retrieve pending 'nim_task_embed' events awaiting processing."""
        stmt = text(
            f"""
            SELECT id, task_id, payload, attempts
            FROM {self._TABLE_NAME}
            WHERE event_type = 'nim_task_embed'
            ORDER BY id
            LIMIT :limit
            """
        )
        result = await session.execute(stmt, {"limit": limit})
        rows = result.fetchall()

        class Row:
            """Simple DTO wrapper for pending outbox entries."""

            def __init__(self, id_val, task_id, payload, attempts):
                self.id = id_val
                self.task_id = task_id
                self.payload = payload
                self.attempts = attempts or 0
                self.reason = payload.get("reason", "outbox") if isinstance(payload, dict) else "outbox"

        return [Row(row.id, row.task_id, row.payload, row.attempts) for row in rows]

    async def claim_pending_nim_task_embeds(
        self, session, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Claim pending 'nim_task_embed' events for processing with FOR UPDATE SKIP LOCKED.
        
        This method uses row-level locking to ensure concurrent-safe processing:
        - FOR UPDATE SKIP LOCKED prevents multiple workers from processing the same event
        - Filters by available_at (scheduling/backoff) and attempts (poison pill protection)
        - Returns events that are ready to be processed (not locked by other workers)
        
        Production Tip: This query enables multiple Coordinator pods to process different
        outbox rows concurrently without contention. Each pod claims different rows atomically.
        
        Args:
            session: Active database session (must be in a transaction).
            limit: Maximum number of events to claim.
            
        Returns:
            List of dictionaries with 'id' and 'payload' keys.
        """
        stmt = text(
            f"""
            WITH cte AS (
              SELECT id, payload
                FROM {self._TABLE_NAME}
               WHERE event_type = 'nim_task_embed'
                 AND available_at <= NOW()  -- Only claim events that are ready (respects backoff)
                 AND COALESCE(attempts, 0) < 10  -- Poison pill protection (max 10 retries)
            ORDER BY available_at ASC, id ASC  -- Process oldest available events first
               FOR UPDATE SKIP LOCKED  -- The "Magic" concurrency command - prevents pod contention
               LIMIT :limit
            )
            SELECT id, payload FROM cte
            """
        )
        result = await session.execute(stmt, {"limit": limit})

        rows: List[Any] = []
        try:
            mappings_fn = getattr(result, "mappings", None)
            if callable(mappings_fn):
                mapped = mappings_fn()
                all_fn = getattr(mapped, "all", None)
                if callable(all_fn):
                    maybe_rows = all_fn()
                    if isinstance(maybe_rows, list):
                        rows = maybe_rows
        except Exception:
            rows = []

        if not rows:
            fetchall = getattr(result, "fetchall", None)
            if callable(fetchall):
                maybe_rows = fetchall()
                rows = await maybe_rows if inspect.isawaitable(maybe_rows) else maybe_rows
        return [{"id": row["id"], "payload": row["payload"]} for row in rows]

    async def delete(
        self,
        session,
        id_val: Any | None = None,
        *,
        event_id: Any | None = None,
    ) -> None:
        """Delete a processed event from the outbox."""
        target_id = id_val if id_val is not None else event_id
        if target_id is None:
            raise ValueError("delete() requires id_val or event_id")
        stmt = text(f"DELETE FROM {self._TABLE_NAME} WHERE id = :id")
        await session.execute(stmt, {"id": target_id})
        logger.debug(f"[Coordinator] Deleted outbox event {target_id}")

    async def backoff(
        self,
        session,
        id_val: Any | None = None,
        *,
        event_id: Any | None = None,
    ) -> None:
        """Increment retry attempts and defer event availability using backoff strategy."""
        target_id = id_val if id_val is not None else event_id
        if target_id is None:
            raise ValueError("backoff() requires id_val or event_id")
        stmt = text(
            f"""
            UPDATE {self._TABLE_NAME}
            SET attempts = COALESCE(attempts, 0) + 1,
                available_at = NOW() + (LEAST(COALESCE(attempts, 0) + 1, 5) * INTERVAL '30 seconds')
            WHERE id = :id
            """
        )
        await session.execute(stmt, {"id": target_id})
        logger.warning(f"[Coordinator] Backed off event {target_id} for retry.")


class TaskProtoPlanDAO:
    """DAO for persisting proto-plan payloads for downstream workers."""

    _TABLE_NAME = "task_proto_plan"

    async def upsert(
        self,
        session,
        *,
        task_id: str,
        route: str,
        proto_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        serialized = json.dumps(proto_plan, sort_keys=True)
        encoded = serialized.encode("utf-8")
        truncated = False
        if len(encoded) > MAX_PROTO_PLAN_BYTES:
            truncated = True
            logger.warning(
                "[Coordinator] Proto-plan for %s exceeded %s bytes (got %s); truncating",
                task_id,
                MAX_PROTO_PLAN_BYTES,
                len(encoded),
            )
            preview = encoded[: MAX_PROTO_PLAN_BYTES - 128].decode("utf-8", "ignore")
            proto_plan = {
                "_truncated": True,
                "size_bytes": len(encoded),
                "preview": preview,
            }
            serialized = json.dumps(proto_plan, sort_keys=True)

        stmt = text(
            """
            INSERT INTO task_proto_plan (task_id, route, proto_plan)
            VALUES (CAST(:task_id AS uuid), :route, CAST(:proto_plan AS jsonb))
            ON CONFLICT (task_id) DO UPDATE
            SET route = EXCLUDED.route,
                proto_plan = EXCLUDED.proto_plan
            RETURNING id
            """
        )
        result = await session.execute(
            stmt,
            {
                "task_id": task_id,
                "route": route,
                "proto_plan": serialized,
            },
        )
        row = None
        if hasattr(result, "fetchone"):
            maybe_row = result.fetchone()
            row = await maybe_row if inspect.isawaitable(maybe_row) else maybe_row

        response: Dict[str, Any] = {"truncated": truncated}
        if row is not None:
            if isinstance(row, dict):
                id_value = row.get("id")
            else:
                id_value = getattr(row, "id", None)
            if isinstance(id_value, (int, str)):
                response["id"] = id_value
        return response

    async def get_by_task_id(
        self, session, *, task_id: str
    ) -> Optional[Dict[str, Any]]:
        stmt = text(
            """
            SELECT id, task_id, route, proto_plan
              FROM task_proto_plan
             WHERE task_id = CAST(:task_id AS uuid)
            """
        )
        result = await session.execute(stmt, {"task_id": task_id})

        row = None
        fetchone = getattr(result, "fetchone", None)
        if callable(fetchone):
            maybe_row = fetchone()
            row = await maybe_row if inspect.isawaitable(maybe_row) else maybe_row

        if not row:
            return None

        # Support both dict-like and object-style rows
        get = row.get if isinstance(row, dict) else lambda k, default=None: getattr(row, k, default)
        proto_plan_raw = get("proto_plan")
        try:
            proto_plan = json.loads(proto_plan_raw) if isinstance(proto_plan_raw, str) else proto_plan_raw
        except (TypeError, json.JSONDecodeError):
            proto_plan = proto_plan_raw

        return {
            "id": get("id"),
            "task_id": get("task_id"),
            "route": get("route"),
            "proto_plan": proto_plan,
        }


class GovernedExecutionAuditDAO:
    """Append-only persistence helper for governed execution audit records."""

    _TABLE_NAME = "governed_execution_audit"

    async def append_record(
        self,
        session,
        *,
        task_id: str,
        record_type: str,
        intent_id: str,
        token_id: Optional[str] = None,
        policy_snapshot: Optional[str] = None,
        policy_decision: Optional[Dict[str, Any]] = None,
        action_intent: Optional[Dict[str, Any]] = None,
        policy_case: Optional[Dict[str, Any]] = None,
        evidence_bundle: Optional[Dict[str, Any]] = None,
        actor_agent_id: Optional[str] = None,
        actor_organ_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = dict(action_intent or {})
        case = dict(policy_case or {})
        decision = dict(policy_decision or {})
        evidence = dict(evidence_bundle or {}) if isinstance(evidence_bundle, dict) else {}
        input_hash = self._sha256_hex(
            _canonical_json(
                {
                    "action_intent": payload,
                    "policy_case": case,
                    "policy_decision": decision,
                }
            )
        )
        evidence_hash = (
            self._sha256_hex(_canonical_json(evidence))
            if evidence
            else None
        )

        stmt = text(
            f"""
            INSERT INTO {self._TABLE_NAME}
            (
                task_id,
                record_type,
                intent_id,
                token_id,
                policy_snapshot,
                policy_decision,
                action_intent,
                policy_case,
                evidence_bundle,
                actor_agent_id,
                actor_organ_id,
                input_hash,
                evidence_hash
            )
            VALUES (
                CAST(:task_id AS uuid),
                :record_type,
                :intent_id,
                :token_id,
                :policy_snapshot,
                CAST(:policy_decision AS jsonb),
                CAST(:action_intent AS jsonb),
                CAST(:policy_case AS jsonb),
                CAST(:evidence_bundle AS jsonb),
                :actor_agent_id,
                :actor_organ_id,
                :input_hash,
                :evidence_hash
            )
            RETURNING id, recorded_at
            """
        )
        result = await session.execute(
            stmt,
            {
                "task_id": str(uuid.UUID(str(task_id))),
                "record_type": record_type,
                "intent_id": intent_id,
                "token_id": token_id,
                "policy_snapshot": policy_snapshot,
                "policy_decision": _canonical_json(decision),
                "action_intent": _canonical_json(payload),
                "policy_case": _canonical_json(case),
                "evidence_bundle": _canonical_json(evidence),
                "actor_agent_id": actor_agent_id,
                "actor_organ_id": actor_organ_id,
                "input_hash": input_hash,
                "evidence_hash": evidence_hash,
            },
        )
        row = result.mappings().one()
        return {
            "entry_id": str(row["id"]),
            "recorded_at": row["recorded_at"].isoformat() if row["recorded_at"] else None,
            "input_hash": input_hash,
            "evidence_hash": evidence_hash,
        }

    async def list_for_task(
        self,
        session,
        *,
        task_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        stmt = text(
            f"""
            SELECT
                id,
                task_id,
                record_type,
                intent_id,
                token_id,
                policy_snapshot,
                policy_decision,
                action_intent,
                policy_case,
                evidence_bundle,
                actor_agent_id,
                actor_organ_id,
                input_hash,
                evidence_hash,
                recorded_at
            FROM {self._TABLE_NAME}
            WHERE task_id = CAST(:task_id AS uuid)
            ORDER BY recorded_at DESC, id DESC
            LIMIT :limit
            """
        )
        result = await session.execute(
            stmt,
            {"task_id": str(uuid.UUID(str(task_id))), "limit": max(1, min(int(limit), 500))},
        )
        return [self._mapping_to_dict(row) for row in result.mappings().all()]

    async def get_latest_for_task(self, session, *, task_id: str) -> Optional[Dict[str, Any]]:
        rows = await self.list_for_task(session, task_id=task_id, limit=1)
        return rows[0] if rows else None

    def _mapping_to_dict(self, row: Any) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "task_id": str(row["task_id"]),
            "record_type": row["record_type"],
            "intent_id": row["intent_id"],
            "token_id": row["token_id"],
            "policy_snapshot": row["policy_snapshot"],
            "policy_decision": dict(row["policy_decision"] or {}),
            "action_intent": dict(row["action_intent"] or {}),
            "policy_case": dict(row["policy_case"] or {}),
            "evidence_bundle": dict(row["evidence_bundle"] or {}),
            "actor_agent_id": row["actor_agent_id"],
            "actor_organ_id": row["actor_organ_id"],
            "input_hash": row["input_hash"],
            "evidence_hash": row["evidence_hash"],
            "recorded_at": row["recorded_at"].isoformat() if row["recorded_at"] else None,
        }

    def _sha256_hex(self, payload: str) -> str:
        import hashlib

        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
