## BaseAgent Cloning Reference

`BaseAgent` is built as a universal chassis: every runtime instance shares the same control flow while its behaviour is driven entirely by configuration (specialization, skills, RBAC, tooling). You do **not** create bespoke subclasses for each persona; you spawn the same class with different inputs.

```53:104:src/seedcore/agents/base.py
class BaseAgent:
    """
    Production-ready base agent.
    ...
        self.specialization: Specialization = specialization
        self.role_profile: RoleProfile = self._role_registry.get(self.specialization)

        # Tool surface
        from seedcore.tools.manager import ToolManager  # local import to avoid cycles

        if tool_manager is None:
            logger.warning(
                "BaseAgent %s started without ToolManager; creating dedicated instance. "
                "Prefer injecting a shared ToolManager.",
                agent_id,
            )
        self.tools: ToolManager = tool_manager or ToolManager()
```

### Automatic Cloning Flow

1. **Define role profiles (done):** The default registry already enumerates specializations, allowed tools, routing tags, and safety policies for agents such as `GEA`, `AAC`, and `BHM`.[^roles]
2. **Centralize tools:** Back each operation with concrete clients inside a single `ToolManager`. This registry is async-safe and exposes execution plus schema discovery for observability.[^tool-manager]
3. **Spawn configured agents:** Upstream orchestrators (for example `Tier0MemoryManager`) instantiate `BaseAgent` with an identifier, specialization, organ, and the shared `ToolManager`.

```python
from seedcore.agents.base import BaseAgent
from seedcore.agents.roles.specialization import Specialization
from seedcore.tools.manager import ToolManager
from integrations.crm import CrmClient
from integrations.iot import IotClient
from integrations.robotics import RoboticsClient
from integrations.security import SecurityClient

tool_manager = ToolManager()
await tool_manager.register("crm.lookup", CrmClient())
await tool_manager.register("iot.read", IotClient())
await tool_manager.register("robot.dispatch", RoboticsClient())
await tool_manager.register("security.key.issue", SecurityClient())

gea_agent = BaseAgent(
    agent_id="gea-01",
    specialization=Specialization.GEA,
    organ_id="Guest_Relations_Organ",
    tool_manager=tool_manager,
)

bhm_agent = BaseAgent(
    agent_id="bhm-01",
    specialization=Specialization.BHM,
    organ_id="Engineering_Organ",
    tool_manager=tool_manager,
)
```

Each call above produces a logically “cloned” agent. The only differences are the specialization-linked role profile and the shared tool surface.

### RBAC-Driven Behaviour

`BaseAgent.execute_task` delegates access control to the role profile’s RBAC policy before any tool call is attempted.[^rbac]

- A building-health agent (`BHM`) authorises `iot.read`, so the call is executed through the injected `ToolManager`.
- A guest-empathy agent (`GEA`) lacks that permission, so the same request is rejected and an RBAC error is returned. No subclassing is required—permissions live in configuration.

### When to Subclass

Inheritance is reserved for agents whose core loop diverges from the task-execution contract. The Utility & Learning Agent forces its specialization, runs its own background loop, and overrides task handling to reject unrelated work.[^ula]

```57:119:src/seedcore/agents/ula_agent.py
class UtilityLearningAgent(BaseAgent):
    ...
        super().__init__(agent_id=agent_id, specialization=Specialization.ULA, **kwargs)
    ...
    async def observe_and_tune_system(self) -> Dict[str, Any]:
        """
        Main ULA tick:
          1) Read system metrics & router/agents status
          2) Detect simple issues (backlogs, high latency, rising drift)
          3) Propose/Apply small policy nudges (weights/thresholds)
          4) Emit telemetry
        """
```

Override the base only when the behaviour matrix changes (observers, auditors, evaluators). For the other 95 % of personas, configuration plus RBAC is sufficient.

### Operational Checklist

- Instantiate one `ToolManager` per deployment scope and inject it into every agent clone.
- Keep the role registry authoritative for skills, permissions, and routing tags.
- Use specialization-specific tooling or behaviour by updating registry entries, not by forking agent classes.
- Leverage the base `advertise_capabilities` output when wiring agents into routers or schedulers.

[^roles]: ```93:170:src/seedcore/agents/roles/role_registry_defaults.py
reg.register(RoleProfile(
    name=Specialization.GEA,
    ...
        allowed_tools={
            T["mem_read"], T["mem_write"], T["notify"],
            T["crm_lookup"], T["crm_update"], T["msg_guest"], T["ticket_create"]
        },
```

[^tool-manager]: ```50:123:src/seedcore/tools/manager.py
class ToolManager:
    """
    Manages the lifecycle and execution of registered tools.

    This class is async-safe and provides RBAC-aware execution.
    """
    ...
    async def execute(self, name: str, args: Dict[str, Any]) -> Any:
        """
        Execute a tool with robust error handling.
        """
```

[^rbac]: ```423:474:src/seedcore/agents/base.py
        for call in tv.tool_calls:
            tool_name = call.get("name")
            ...
            decision = self.authorize_tool(
                tool_name,
                cost_usd=0.0,
                context={"task_id": tv.task_id, "agent_id": self.agent_id},
            )
            if not decision.allowed:
                tool_errors.append({"tool": tool_name, "error": f"rbac_denied:{decision.reason or 'policy_block'}"})
                continue
            ...
                output = await asyncio.wait_for(tool_manager.execute(tool_name, args), timeout=tool_timeout)
```

[^ula]: ```302:335:src/seedcore/agents/ula_agent.py
    async def _safe_tool_read(self, name: str, args: Dict[str, Any], timeout_s: float = 8.0) -> Optional[Dict[str, Any]]:
        """RBAC + existence + timeout wrapper for read-like tools."""
        try:
            if not self._authorize(name, args):
                return None
            tool_manager = getattr(self, "tools", None)
            if not tool_manager:
                return None
            has_result = tool_manager.has(name)
            if inspect.isawaitable(has_result):
                has_result = await has_result
            if not has_result:
                return None
            execute_coro = tool_manager.execute(name, args)
            if inspect.isawaitable(execute_coro):
                return await asyncio.wait_for(execute_coro, timeout=timeout_s)
            return None
        except Exception:
            return None
```

