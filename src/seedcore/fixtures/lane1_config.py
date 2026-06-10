"""Lane 1 freshness-SLA targets for RCT fixture and simulator tests."""

LANE_1_TARGETS = {
    "convergence_p99_max_ms": 1.0,
    "sample_count": 1000,
    "source_reference": "docs/development/freshness_sla_edge_stress_schedule.md:72",
}

__all__ = ["LANE_1_TARGETS"]
