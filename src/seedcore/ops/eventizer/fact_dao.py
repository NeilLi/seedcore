"""Lightweight DAO for recording task↔fact provenance edges."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Iterable, List, Optional, Sequence, Union

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.models.fact import Fact

UUIDLike = Union[str, uuid.UUID]


class FactDAO:
    """Helper for recording task↔fact reads/writes within an open transaction."""

    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def _normalize_uuid(value: UUIDLike) -> Optional[uuid.UUID]:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_uuid_list(cls, values: Iterable[UUIDLike]) -> List[uuid.UUID]:
        normalized: List[uuid.UUID] = []
        for value in values:
            item = cls._normalize_uuid(value)
            if item is not None:
                normalized.append(item)
        # Preserve order but drop duplicates
        seen = set()
        unique: List[uuid.UUID] = []
        for item in normalized:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique

    @asynccontextmanager
    async def _transaction(self):
        if self._session.in_transaction():
            yield
        else:
            async with self._session.begin():
                yield

    async def _ensure_task_node(self, task_id: uuid.UUID) -> None:
        await self._session.execute(
            text("SELECT ensure_task_node(:task_id::uuid)"),
            {"task_id": str(task_id)},
        )

    async def _ensure_fact_nodes(self, fact_ids: Sequence[uuid.UUID]) -> None:
        if not fact_ids:
            return
        await self._session.execute(
            text(
                "SELECT ensure_fact_node(fact_id) "
                "FROM unnest(:fact_ids::uuid[]) AS fact_id"
            ),
            {"fact_ids": [str(fid) for fid in fact_ids]},
        )

    async def get_for_task(
        self,
        fact_ids: Sequence[UUIDLike],
        task_id: UUIDLike,
    ) -> List[Fact]:
        """Fetch facts while recording a read edge for the given task."""

        normalized_task = self._normalize_uuid(task_id)
        normalized_facts = self._normalize_uuid_list(fact_ids)

        if not normalized_task or not normalized_facts:
            return []

        async with self._transaction():
            await self._ensure_task_node(normalized_task)
            await self._ensure_fact_nodes(normalized_facts)
            await self._session.execute(
                text(
                    "WITH payload AS ("
                    "    SELECT :task_id::uuid AS task_id, unnest(:fact_ids::uuid[]) AS fact_id"
                    ")"
                    "INSERT INTO task_reads_fact(task_id, fact_id) "
                    "SELECT task_id, fact_id FROM payload "
                    "ON CONFLICT (task_id, fact_id) DO NOTHING"
                ),
                {
                    "task_id": str(normalized_task),
                    "fact_ids": [str(fid) for fid in normalized_facts],
                },
            )

            result = await self._session.execute(
                select(Fact).where(Fact.id.in_(normalized_facts))
            )
            return list(result.scalars().all())

    async def record_produced_fact(
        self,
        fact_id: UUIDLike,
        task_id: UUIDLike,
    ) -> None:
        """Record that *task_id* produced *fact_id* within the coordinator transaction."""

        normalized_task = self._normalize_uuid(task_id)
        normalized_fact = self._normalize_uuid(fact_id)

        if not normalized_task or not normalized_fact:
            return

        async with self._transaction():
            await self._ensure_task_node(normalized_task)
            await self._ensure_fact_nodes([normalized_fact])
            await self._session.execute(
                text(
                    "INSERT INTO task_produces_fact(task_id, fact_id) "
                    "VALUES (:task_id::uuid, :fact_id::uuid) "
                    "ON CONFLICT (task_id, fact_id) DO NOTHING"
                ),
                {
                    "task_id": str(normalized_task),
                    "fact_id": str(normalized_fact),
                },
            )
