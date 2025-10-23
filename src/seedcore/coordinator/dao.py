from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence
import json
from sqlalchemy import text


MAX_PROTO_PLAN_BYTES = 256 * 1024


class TaskRouterTelemetryDAO:
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
    _TABLE_NAME = "task_outbox"

    async def enqueue_embed_task(
        self,
        session,
        *,
        task_id: str,
        reason: str = "coordinator",
        dedupe_key: Optional[str] = None,
    ) -> bool:
        payload = {"reason": reason, "task_id": task_id}
        encoded_payload = json.dumps(payload, sort_keys=True)
        if len(encoded_payload.encode("utf-8")) > MAX_PROTO_PLAN_BYTES:
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
                "event_type": "embed_task",
                "payload": encoded_payload,
                "dedupe_key": dedupe_key,
            },
        )
        return bool(getattr(result, "rowcount", 0))

    async def list_pending_embed_tasks(self, session, limit: int = 100) -> List[Any]:
        """List pending embed_task events from the outbox."""
        stmt = text(
            f"""
            SELECT id, task_id, payload, attempts
            FROM {self._TABLE_NAME}
            WHERE event_type = 'embed_task'
            ORDER BY id
            LIMIT :limit
            """
        )
        result = await session.execute(stmt, {"limit": limit})
        rows = result.fetchall()
        
        # Convert to simple objects with attributes
        class Row:
            def __init__(self, id_val, task_id, payload, attempts):
                self.id = id_val
                self.task_id = task_id
                self.payload = payload
                self.attempts = attempts or 0
                self.reason = "outbox"  # Default reason
        
        return [Row(row.id, row.task_id, row.payload, row.attempts) for row in rows]

    async def delete(self, session, id_val: Any) -> None:
        """Delete a row from the outbox by ID."""
        stmt = text(f"DELETE FROM {self._TABLE_NAME} WHERE id = :id")
        await session.execute(stmt, {"id": id_val})

    async def backoff(self, session, id_val: Any) -> None:
        """Increment attempts and schedule retry for a row."""
        stmt = text(
            f"""
            UPDATE {self._TABLE_NAME}
            SET attempts = COALESCE(attempts, 0) + 1,
                available_at = NOW() + (LEAST(COALESCE(attempts, 0) + 1, 5) * INTERVAL '30 seconds')
            WHERE id = :id
            """
        )
        await session.execute(stmt, {"id": id_val})


class TaskProtoPlanDAO:
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
            preview = encoded[: MAX_PROTO_PLAN_BYTES - 128].decode("utf-8", "ignore")
            proto_plan = {"_truncated": True, "size_bytes": len(encoded), "preview": preview}
            serialized = json.dumps(proto_plan, sort_keys=True)
        stmt = text(
            """
            INSERT INTO task_proto_plan (task_id, route, proto_plan)
            VALUES (CAST(:task_id AS uuid), :route, CAST(:proto_plan AS jsonb))
            ON CONFLICT (task_id) DO UPDATE
            SET route = EXCLUDED.route,
                proto_plan = EXCLUDED.proto_plan
            """
        )
        await session.execute(
            stmt,
            {"task_id": task_id, "route": route, "proto_plan": serialized},
        )
        return {"truncated": truncated}


