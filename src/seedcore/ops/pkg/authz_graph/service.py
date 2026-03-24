from __future__ import annotations

from dataclasses import dataclass, field
import logging
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select  # pyright: ignore[reportMissingImports]

from seedcore.database import get_async_pg_session_factory
from seedcore.models.action_intent import ActionIntent
from seedcore.models.source_registration import RegistrationDecision, SourceRegistration, TrackingEvent
from seedcore.ops.pkg.client import PKGClient

from .compiler import AuthzGraphCompiler, CompiledAuthzIndex
from .manifest import PolicyEdgeManifest
from .ontology import AuthzGraphSnapshot
from .projector import AuthzGraphProjector

logger = logging.getLogger(__name__)


Loader = Callable[..., Awaitable[List[Any]]]


@dataclass(frozen=True)
class AuthzProjectionSources:
    facts: List[Dict[str, Any]] = field(default_factory=list)
    registrations: List[SourceRegistration | Dict[str, Any]] = field(default_factory=list)
    registration_decisions: List[RegistrationDecision | Dict[str, Any]] = field(default_factory=list)
    tracking_events: List[TrackingEvent | Dict[str, Any]] = field(default_factory=list)
    action_intents: List[ActionIntent] = field(default_factory=list)
    graph_manifests: List[PolicyEdgeManifest | Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AuthzProjectionResult:
    snapshot: AuthzGraphSnapshot
    sources: AuthzProjectionSources
    stats: Dict[str, Any]


class AuthzGraphProjectionService:
    """
    Snapshot-scoped projection orchestrator for the authorization graph.

    Phase 2 goals:
    - gather deterministic authz-relevant inputs for a specific snapshot
    - build a graph snapshot from those inputs
    - optionally compile the graph snapshot into a read-only PDP index
    """

    def __init__(
        self,
        *,
        pkg_client: Optional[PKGClient] = None,
        session_factory: Optional[callable] = None,
        projector: Optional[AuthzGraphProjector] = None,
        compiler: Optional[AuthzGraphCompiler] = None,
        facts_loader: Optional[Loader] = None,
        registrations_loader: Optional[Loader] = None,
        registration_decisions_loader: Optional[Loader] = None,
        tracking_events_loader: Optional[Loader] = None,
    ) -> None:
        self.pkg_client = pkg_client or PKGClient(session_factory)
        self._sf = session_factory or getattr(self.pkg_client, "_sf", None)
        self.projector = projector or AuthzGraphProjector()
        self.compiler = compiler or AuthzGraphCompiler()
        self._facts_loader = facts_loader or self._load_governed_facts
        self._registrations_loader = registrations_loader or self._load_registrations
        self._registration_decisions_loader = (
            registration_decisions_loader or self._load_registration_decisions
        )
        self._tracking_events_loader = tracking_events_loader or self._load_tracking_events

    async def collect_sources(
        self,
        *,
        snapshot_id: Optional[int] = None,
        snapshot_version: Optional[str] = None,
        governed_only: bool = True,
        fact_namespace: Optional[str] = None,
        include_registrations: bool = True,
        include_registration_decisions: bool = False,
        include_tracking_events: bool = True,
        action_intents: Optional[Iterable[ActionIntent]] = None,
    ) -> AuthzProjectionSources:
        snapshot = await self._resolve_snapshot(snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        if snapshot is not None:
            snapshot_id = snapshot.id
            snapshot_version = snapshot.version

        if snapshot_id is None:
            raise ValueError("snapshot_id or snapshot_version is required")

        facts = await self._facts_loader(
            snapshot_id=snapshot_id,
            namespace=fact_namespace,
            governed_only=governed_only,
        )
        registrations: List[SourceRegistration | Dict[str, Any]] = []
        registration_decisions: List[RegistrationDecision | Dict[str, Any]] = []
        tracking_events: List[TrackingEvent | Dict[str, Any]] = []
        if include_registrations:
            registrations = await self._registrations_loader(snapshot_id=snapshot_id)
        if include_registration_decisions:
            registration_decisions = await self._registration_decisions_loader(snapshot_id=snapshot_id)
        if include_tracking_events:
            tracking_events = await self._tracking_events_loader(snapshot_id=snapshot_id)

        return AuthzProjectionSources(
            facts=list(facts),
            registrations=list(registrations),
            registration_decisions=list(registration_decisions),
            tracking_events=list(tracking_events),
            action_intents=list(action_intents or []),
            graph_manifests=list(getattr(snapshot, "graph_manifests", []) or []),
        )

    async def build_snapshot(
        self,
        *,
        snapshot_ref: str,
        snapshot_id: Optional[int] = None,
        snapshot_version: Optional[str] = None,
        governed_only: bool = True,
        fact_namespace: Optional[str] = None,
        include_registrations: bool = True,
        include_registration_decisions: bool = False,
        include_tracking_events: bool = True,
        action_intents: Optional[Iterable[ActionIntent]] = None,
    ) -> AuthzProjectionResult:
        sources = await self.collect_sources(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            governed_only=governed_only,
            fact_namespace=fact_namespace,
            include_registrations=include_registrations,
            include_registration_decisions=include_registration_decisions,
            include_tracking_events=include_tracking_events,
            action_intents=action_intents,
        )
        snapshot = await self._resolve_snapshot(snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        effective_snapshot_id = snapshot_id
        effective_snapshot_version = snapshot_version
        if snapshot is not None:
            effective_snapshot_id = snapshot.id
            effective_snapshot_version = snapshot.version

        snapshot = self.projector.project_snapshot(
            snapshot_ref=snapshot_ref,
            snapshot_id=effective_snapshot_id,
            snapshot_version=effective_snapshot_version,
            policy_edge_manifests=sources.graph_manifests,
            action_intents=sources.action_intents,
            facts=sources.facts,
            registrations=sources.registrations,
            registration_decisions=sources.registration_decisions,
            tracking_events=sources.tracking_events,
        )
        stats = {
            "snapshot_ref": snapshot_ref,
            "snapshot_id": effective_snapshot_id,
            "snapshot_version": effective_snapshot_version,
            "facts_count": len(sources.facts),
            "registrations_count": len(sources.registrations),
            "registration_decisions_count": len(sources.registration_decisions),
            "tracking_events_count": len(sources.tracking_events),
            "action_intents_count": len(sources.action_intents),
            "graph_manifests_count": len(sources.graph_manifests),
            "graph_nodes_count": len(snapshot.nodes),
            "graph_edges_count": len(snapshot.edges),
            "governed_only": governed_only,
            "fact_namespace": fact_namespace,
        }
        return AuthzProjectionResult(snapshot=snapshot, sources=sources, stats=stats)

    async def build_compiled_index(self, **kwargs: Any) -> tuple[CompiledAuthzIndex, AuthzProjectionResult]:
        result = await self.build_snapshot(**kwargs)
        compiled = self.compiler.compile(result.snapshot)
        return compiled, result

    async def _load_governed_facts(
        self,
        *,
        snapshot_id: int,
        namespace: Optional[str] = None,
        governed_only: bool = True,
    ) -> List[Dict[str, Any]]:
        return await self.pkg_client.get_active_governed_facts(
            snapshot_id=snapshot_id,
            namespace=namespace,
            governed_only=governed_only,
            limit=500,
        )

    async def _load_registrations(self, *, snapshot_id: int) -> List[SourceRegistration]:
        if self._sf is None:
            self._sf = get_async_pg_session_factory()
        async with self._sf() as session:
            result = await session.execute(
                select(SourceRegistration)
                .where(SourceRegistration.snapshot_id == snapshot_id)
                .order_by(SourceRegistration.created_at.asc(), SourceRegistration.id.asc())
            )
            return _result_items(result)

    async def _load_tracking_events(self, *, snapshot_id: int) -> List[TrackingEvent]:
        if self._sf is None:
            self._sf = get_async_pg_session_factory()
        async with self._sf() as session:
            result = await session.execute(
                select(TrackingEvent)
                .where(TrackingEvent.snapshot_id == snapshot_id)
                .order_by(TrackingEvent.captured_at.asc(), TrackingEvent.id.asc())
            )
            return _result_items(result)

    async def _load_registration_decisions(self, *, snapshot_id: int) -> List[RegistrationDecision]:
        try:
            if self._sf is None:
                self._sf = get_async_pg_session_factory()
            async with self._sf() as session:
                result = await session.execute(
                    select(RegistrationDecision)
                    .where(RegistrationDecision.policy_snapshot_id == snapshot_id)
                    .order_by(RegistrationDecision.decided_at.asc(), RegistrationDecision.id.asc())
                )
                return _result_items(result)
        except Exception as exc:
            logger.warning(
                "Authz graph registration-decision enrichment unavailable for snapshot_id=%s: %s",
                snapshot_id,
                exc,
            )
            return []

    async def _resolve_snapshot(
        self,
        *,
        snapshot_id: Optional[int],
        snapshot_version: Optional[str],
    ) -> Any:
        if snapshot_version is not None:
            getter = getattr(self.pkg_client, "get_snapshot_by_version", None)
            if getter is None:
                return SimpleNamespace(
                    id=snapshot_id,
                    version=snapshot_version,
                    graph_manifests=[],
                )
            snapshot = await getter(snapshot_version)
            if snapshot is None:
                raise LookupError(f"PKG snapshot version '{snapshot_version}' not found")
            return snapshot
        if snapshot_id is not None:
            getter = getattr(self.pkg_client, "get_snapshot_by_id", None)
            if getter is None:
                return SimpleNamespace(
                    id=snapshot_id,
                    version=snapshot_version,
                    graph_manifests=[],
                )
            snapshot = await getter(snapshot_id)
            if snapshot is None:
                raise LookupError(f"PKG snapshot id '{snapshot_id}' not found")
            return snapshot
        return None


def _result_items(result: Any) -> List[Any]:
    scalars = getattr(result, "scalars", None)
    if callable(scalars):
        scalar_result = scalars()
        scalar_all = getattr(scalar_result, "all", None)
        if callable(scalar_all):
            return list(scalar_all())

    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        return list(fetchall())

    scalar = getattr(result, "scalar", None)
    if callable(scalar):
        value = scalar()
        return [] if value is None else [value]

    return []
