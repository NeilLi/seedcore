from prometheus_client import Gauge, Counter, Histogram
from typing import Dict, Any
import time

# ─────────────────────────────────────────────────────────────────────── #
#   Existing Metrics (Enhanced)
# ─────────────────────────────────────────────────────────────────────── #

COSTVQ = Gauge("costvq_current", "Current CostVQ memory cost")
ENERGY_SLOPE = Gauge("energy_delta_last", "Latest dE/dk slope")
MEM_WRITES = Counter("memory_write_total", "Holons written", ["tier"])

# ─────────────────────────────────────────────────────────────────────── #
#   Agent Metrics (New)
# ─────────────────────────────────────────────────────────────────────── #

AGENT_CAPABILITY = Gauge(
    "agent_capability",
    "Capability score per agent",
    ["agent_id", "agent_type"]
)

AGENT_MEM_UTILITY = Gauge(
    "agent_mem_util",
    "Memory utility score per agent",
    ["agent_id", "agent_type"]
)

AGENT_SUCCESS_RATE = Gauge(
    "agent_success_rate",
    "Success rate per agent",
    ["agent_id", "agent_type"]
)

AGENT_TASKS_PROCESSED = Counter(
    "agent_tasks_processed_total",
    "Total tasks processed per agent",
    ["agent_id", "agent_type"]
)

AGENT_ROLE_PROBS = Gauge(
    "agent_role_probability",
    "Role probability per agent",
    ["agent_id", "role"]
)

# ─────────────────────────────────────────────────────────────────────── #
#   Energy Metrics (New)
# ─────────────────────────────────────────────────────────────────────── #

ENERGY_TERMS = Gauge(
    "energy_term_value",
    "Unified energy term values",
    ["term"]
)

ENERGY_TOTAL = Gauge("energy_total", "Total unified energy")
ENERGY_DELTA = Gauge("energy_delta_last_task", "ΔE of last task")

# ─────────────────────────────────────────────────────────────────────── #
#   Memory Metrics (New)
# ─────────────────────────────────────────────────────────────────────── #

MEMORY_TIER_USAGE_BYTES = Gauge(
    "memory_tier_usage_bytes",
    "Memory usage in bytes per tier",
    ["tier"]
)

MEMORY_COMPRESSION_RATIO = Gauge(
    "memory_compression_ratio",
    "Average compression ratio"
)

MEMORY_HITS = Counter(
    "memory_hits_total",
    "Memory hits per tier",
    ["tier"]
)

MEMORY_MISSES = Counter(
    "memory_misses_total",
    "Memory misses per tier",
    ["tier"]
)

# ─────────────────────────────────────────────────────────────────────── #
#   API Metrics (New)
# ─────────────────────────────────────────────────────────────────────── #

API_REQUESTS_TOTAL = Counter(
    "api_requests_total",
    "Total API requests",
    ["endpoint", "method"]
)

API_REQUEST_DURATION = Histogram(
    "api_request_duration_seconds",
    "API request duration",
    ["endpoint", "method"]
)

# ─────────────────────────────────────────────────────────────────────── #
#   System Metrics (New)
# ─────────────────────────────────────────────────────────────────────── #

SYSTEM_ACTIVE_AGENTS = Gauge(
    "system_active_agents",
    "Number of active agents"
)

SYSTEM_TOTAL_AGENTS = Gauge(
    "system_total_agents",
    "Total number of agents"
)

SYSTEM_MEMORY_UTILIZATION_KB = Gauge(
    "system_memory_utilization_kb",
    "System memory utilization in KB"
)

# ─────────────────────────────────────────────────────────────────────── #
#   Update Functions
# ─────────────────────────────────────────────────────────────────────── #

def update_agent_metrics(agent_data: Dict[str, Any]) -> None:
    """Update agent-specific metrics from agent data."""
    agent_id = agent_data.get("id", "unknown")
    agent_type = agent_data.get("type", "unknown")
    
    AGENT_CAPABILITY.labels(agent_id, agent_type).set(
        agent_data.get("capability", 0.0)
    )
    AGENT_MEM_UTILITY.labels(agent_id, agent_type).set(
        agent_data.get("mem_util", 0.0)
    )
    AGENT_SUCCESS_RATE.labels(agent_id, agent_type).set(
        agent_data.get("success_rate", 0.0)
    )
    
    # Update role probabilities
    role_probs = agent_data.get("role_probs", {})
    for role, prob in role_probs.items():
        AGENT_ROLE_PROBS.labels(agent_id, role).set(prob)

def update_energy_metrics(energy_data: Dict[str, Any]) -> None:
    """Update energy metrics from energy data."""
    energy_terms = energy_data.get("E_terms", {})
    
    for term, value in energy_terms.items():
        ENERGY_TERMS.labels(term).set(value)
    
    ENERGY_TOTAL.set(energy_terms.get("total", 0.0))
    ENERGY_DELTA.set(energy_data.get("deltaE_last", 0.0))

def update_memory_metrics(memory_data: Dict[str, Any]) -> None:
    """Update memory metrics from memory data."""
    MEMORY_COMPRESSION_RATIO.set(
        memory_data.get("compression_ratio", 1.0)
    )
    
    # Update tier usage if available
    usage_bytes = memory_data.get("usage_bytes", {})
    for tier, bytes_used in usage_bytes.items():
        MEMORY_TIER_USAGE_BYTES.labels(tier).set(bytes_used)

def update_system_metrics(system_data: Dict[str, Any]) -> None:
    """Update system-wide metrics."""
    SYSTEM_TOTAL_AGENTS.set(
        system_data.get("total_agents", 0)
    )
    SYSTEM_ACTIVE_AGENTS.set(
        system_data.get("active_agents", 0)
    )
    SYSTEM_MEMORY_UTILIZATION_KB.set(
        system_data.get("memory_utilization_kb", 0.0)
    )

def update_all_metrics_from_api_data(
    energy_data: Dict[str, Any] = None,
    agents_data: Dict[str, Any] = None,
    system_data: Dict[str, Any] = None
) -> None:
    """Update all metrics from API endpoint data."""
    
    if energy_data:
        update_energy_metrics(energy_data)
    
    if agents_data:
        agents = agents_data.get("agents", [])
        for agent in agents:
            update_agent_metrics(agent)
    
    if system_data:
        update_system_metrics(system_data)
        
        memory_data = system_data.get("memory_system", {})
        if not isinstance(memory_data, dict):
            memory_data = {}
        update_memory_metrics(memory_data) 