import pytest

from seedcore.coordinator.core.plan_executor import PlanExecutor, PlanExecutionStatus
from seedcore.models.task_payload import TaskPayload


@pytest.mark.asyncio
async def test_plan_executor_executes_implicit_steps_in_order():
    calls = []

    async def organism_execute(organ, payload, timeout_s, cid):
        calls.append((organ, payload.get("id")))
        return {"success": True, "result": {"ok": True}}

    plan = [
        {"id": "a", "type": "action", "depends_on": []},
        {"id": "b", "type": "action", "depends_on": ["a"]},
    ]
    parent = TaskPayload(task_id="root", type="action")

    executor = PlanExecutor(organism_execute=organism_execute)
    results, normalized, status = await executor.execute_plan(
        plan=plan,
        parent_task=parent,
        timeout_s=1.0,
        cid="cid",
    )

    assert [c[1] for c in calls] == ["a", "b"]
    assert all(r.get("success") for r in results if r.get("step") is not None)
    assert len(normalized) == 2
    assert status == PlanExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_plan_executor_executes_explicit_dag():
    calls = []

    async def organism_execute(organ, payload, timeout_s, cid):
        calls.append(payload.get("id"))
        return {"success": True}

    plan = {
        "nodes": [
            {"id": "wait_noise", "type": "condition"},
            {"id": "set_temp", "type": "action"},
        ],
        "edges": [["wait_noise", "set_temp"]],
    }
    parent = TaskPayload(task_id="root", type="action")

    def condition_eval(step, parent_task):
        return step.id == "wait_noise"

    executor = PlanExecutor(
        organism_execute=organism_execute,
        condition_evaluator=condition_eval,
    )
    results, normalized, status = await executor.execute_plan(
        plan=plan,
        parent_task=parent,
        timeout_s=1.0,
        cid="cid",
    )

    assert "set_temp" in calls
    assert len(normalized) == 2
    assert any(r.get("step") == "wait_noise" for r in results)
    assert status == PlanExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_plan_executor_blocks_unsatisfied_condition():
    async def organism_execute(organ, payload, timeout_s, cid):
        return {"success": True}

    plan = [
        {"id": "wait_noise", "type": "condition", "depends_on": []},
        {"id": "set_temp", "type": "action", "depends_on": ["wait_noise"]},
    ]
    parent = TaskPayload(task_id="root", type="action")

    executor = PlanExecutor(organism_execute=organism_execute)
    results, _normalized, status = await executor.execute_plan(
        plan=plan,
        parent_task=parent,
        timeout_s=1.0,
        cid="cid",
    )

    assert any(
        r.get("result", {}).get("error") == "condition_unsatisfied" for r in results
    )
    assert status == PlanExecutionStatus.WAITING
