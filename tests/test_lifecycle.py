from seedcore.agents.base import Agent
from seedcore.agents.lifecycle import evaluate_lifecycle

def test_lifecycle_call():
    a = Agent('a1', capability=0.8, mem_util=0.6)
    evaluate_lifecycle(a)  # should not raise
