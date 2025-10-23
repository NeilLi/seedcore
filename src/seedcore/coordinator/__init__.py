"""Coordinator package: core logic split from coordinator_service.

Modules:
- core.py: CoordinatorCore and routing pipeline
- dao.py: DAOs (telemetry, outbox, proto plan)
- routing_cache.py: Route cache and entry types
- metrics.py: MetricsTracker and prometheus counters
- models.py: Pydantic models used by coordinator
- surprise.py: Surprise score and helpers
"""


