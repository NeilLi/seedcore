import numpy as np

from seedcore.control.fast_loop import fast_loop_select_agent
from seedcore.control.slow_loop import slow_loop_update_roles
from seedcore.control.mem_loop import adaptive_mem_update
from seedcore.agents.base import Agent


class DummyAgent(Agent):
    def __init__(self, agent_id: str):
        super().__init__(agent_id=agent_id)
        self.role_probs = {"E": 1/3, "S": 1/3, "O": 1/3}
        self.capability = 0.5
        self.mem_util = 0.2


class DummyOrgan:
    def __init__(self, ids=("a1", "a2")):
        self.agents = {aid: DummyAgent(aid) for aid in ids}

    def select_agent(self, task):
        # Legacy fallback path
        return self.agents[list(self.agents.keys())[0]]


def test_fast_loop_selects_some_agent():
    organ = DummyOrgan()
    agent = fast_loop_select_agent(organ, task={})
    assert agent is not None


def test_slow_loop_updates_roles_without_crashing():
    organ = DummyOrgan()
    slow_loop_update_roles(list(organ.agents.values()), learning_rate=0.01)
    # Ensure probabilities remain valid
    for agent in organ.agents.values():
        s = sum(agent.role_probs.values())
        assert abs(s - 1.0) < 1e-6


def test_mem_loop_updates_compression_without_crashing():
    organ = DummyOrgan()
    knob = adaptive_mem_update([organ], compression_knob=0.5)
    assert 0.0 <= knob <= 1.0

