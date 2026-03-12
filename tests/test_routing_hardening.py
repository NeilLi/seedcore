import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.organs.organism_core import OrganismCore
from seedcore.organs.router import HardRoutingFailure, RoutingDirectory
from seedcore.agents.roles import create_default_registry, Specialization


class _StubTunnelManager:
    async def get_assigned_agent(self, _conv_id):
        return None

    async def assign(self, _conv_id, _agent_id):
        return None

    async def get_actor_handle(self, _agent_id):
        return None


class _StubOrganism:
    def __init__(self):
        self.router_cfgs = {}
        self.organs = {}
        self.tunnel_manager = _StubTunnelManager()
        self.organ_specs = {}
        self.role_registry = create_default_registry()

    async def execute_on_agent(self, organ_id, agent_id, payload):
        raise AssertionError(
            f"execution should halt before dispatch (organ_id={organ_id}, agent_id={agent_id}, payload={payload})"
        )


@pytest.mark.asyncio
async def test_router_raises_on_missing_required_specialization():
    router = RoutingDirectory(organism=_StubOrganism())
    payload = {
        "task_id": "task-hard-stop",
        "type": "action",
        "domain": "physical",
        "params": {
            "routing": {"required_specialization": "ghost_specialist"},
            "risk": {"is_high_stakes": True},
        },
    }

    with pytest.raises(HardRoutingFailure) as exc_info:
        await router.route_only(payload)

    exc = exc_info.value
    assert exc.error_type == "required_specialization_unregistered"
    assert exc.meta["halted"] is True
    assert exc.meta["required_specialization"] == "ghost_specialist"
    assert exc.meta["alert"]["kind"] == "routing_halt"


@pytest.mark.asyncio
async def test_route_and_execute_returns_halt_envelope_for_missing_required_specialization():
    router = RoutingDirectory(organism=_StubOrganism())
    payload = {
        "task_id": "task-envelope-stop",
        "type": "action",
        "params": {
            "routing": {"required_specialization": "ghost_specialist"},
        },
    }

    result = await router.route_and_execute(payload)

    assert result["success"] is False
    assert result["retry"] is False
    assert result["error_type"] == "required_specialization_unregistered"
    assert result["decision_kind"] == "error"
    assert result["payload"]["halted"] is True
    assert result["meta"]["halted"] is True


def test_router_allows_general_query_for_generalist_soft_routing():
    router = RoutingDirectory(organism=_StubOrganism())

    allowed = router._tools_allowed_for_spec(
        Specialization.GENERALIST.value,
        ["general_query"],
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_organism_core_halts_instead_of_cognitive_fallback_for_unregistered_required_specialization():
    organism = OrganismCore.__new__(OrganismCore)
    organism.logger = Mock()

    result = await organism._cognitive_fallback_for_unregistered_spec(
        organ_id="utility_organ",
        organ_handle=SimpleNamespace(),
        agent_id="agent-1",
        task_id="task-core-stop",
        required_spec="ghost_specialist",
        task_dict={"params": {"risk": {"is_high_stakes": True}}},
    )

    assert result["success"] is False
    assert result["retry"] is False
    assert result["error_type"] == "required_specialization_unregistered"
    assert result["decision_kind"] == "error"
    assert result["payload"]["halted"] is True
    assert result["payload"]["alert"]["severity"] == "critical"
