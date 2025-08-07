# DSPy Integration Guide for SeedCore

This guide describes the comprehensive integration of DSPy (Declarative Self-Improving Language Programs) with SeedCore, providing intelligent cognitive reasoning capabilities for your Ray-based agent architecture.

## 🎯 Overview

The DSPy integration provides **three complementary modes** that merge the strengths of lightweight library integration and deep cognitive core embedding:

1. **Embedded Cognitive Core**: DSPy as the "brain" within each agent
2. **Ray Serve Deployment**: Scalable, shared inference for heavy workloads
3. **FastAPI Endpoints**: Lightweight testing and experimentation

## 🏗️ Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    DSPy Cognitive Core                      │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Failure Analysis│  │ Task Planning   │  │ Decision     │ │
│  │ Signature       │  │ Signature       │  │ Making       │ │
│  └─────────────────┘  └─────────────────┘  │ Signature    │ │
│                                             └──────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Problem Solving │  │ Memory          │  │ Capability   │ │
│  │ Signature       │  │ Synthesis       │  │ Assessment   │ │
│  └─────────────────┘  │ Signature       │  │ Signature    │ │
│                       └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Integration Layer                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ RayAgent        │  │ Ray Serve       │  │ FastAPI      │ │
│  │ Integration     │  │ Deployment      │  │ Endpoints    │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Integration Modes

| Mode | Use Case | Advantage | Integration Point |
|------|----------|-----------|-------------------|
| **Embedded in RayAgent** | Deep agent intelligence, full state coupling | Tight integration with memory, energy, lifecycle | `ray_actor.py` |
| **Ray Serve Deployment** | Scalable, shared inference, heavy workloads | Parallel processing, resource sharing | `cognitive_serve.py` |
| **FastAPI Endpoints** | Fast prototyping, direct API calls | Quick experimentation, no infra changes | `telemetry/server.py` |

## 🚀 Quick Start

### 1. Environment Setup

Add DSPy to your requirements:

```bash
# Already added to docker/requirements-minimal.txt
dspy-ai==2.4.4
openai>=1.12.0
```

Set your API key:

```bash
# In your .env file
OPENAI_API_KEY="sk-your-openai-api-key"
```

### 2. Simple Usage (Recommended for Testing)

For quick testing and development, use the simple example:

```bash
# Test basic functionality (no API key required)
docker exec -it seedcore-api python examples/test_simple_dspy.py

# Run simple example with API key
docker exec -it seedcore-api python examples/simple_dspy_example.py
```

### 3. Basic Usage

```python
from seedcore.agents.cognitive_core import initialize_cognitive_core, CognitiveContext, CognitiveTaskType

# Initialize cognitive core
cognitive_core = initialize_cognitive_core()

# Create context for failure analysis
context = CognitiveContext(
    agent_id="my_agent",
    task_type=CognitiveTaskType.FAILURE_ANALYSIS,
    input_data={"incident_id": "incident_001", "error": "Task failed"}
)

# Perform cognitive reasoning
result = cognitive_core(context)
print(f"Analysis: {result['thought']}")
```

### 4. Ray Agent Integration

```python
import ray
from seedcore.agents.ray_actor import RayAgent

# Create agent with cognitive capabilities
agent = RayAgent.remote("cognitive_agent", {'E': 0.7, 'S': 0.2, 'O': 0.1})

# Use cognitive reasoning
```

### 5. Optimized Ray Serve Deployment (Production)

For production deployments with proper namespace management and conflict handling:

```bash
# Run optimized example with proper integration
docker exec -it seedcore-api python examples/optimized_dspy_integration_example.py
```

**Key Features:**
- ✅ **Conflict Prevention**: Checks for existing deployments
- ✅ **Namespace Management**: Consistent with serve_entrypoint.py
- ✅ **Health Monitoring**: Built-in health checks and status reporting
- ✅ **Resource Optimization**: Single deployment with proper route management
result = await agent.reason_about_failure.remote("incident_001")
print(f"Agent analysis: {result['thought_process']}")
```

## 📚 Examples

### Simple Examples (Recommended for Development)

#### 1. Basic Testing (No API Key Required)
```bash
docker exec -it seedcore-api python examples/test_simple_dspy.py
```
Tests the basic structure and imports without requiring an API key.

#### 2. Simple DSPy Integration
```bash
docker exec -it seedcore-api python examples/simple_dspy_example.py
```
Demonstrates all 6 cognitive task types with direct cognitive core usage.

**Features:**
- ✅ Lightweight - No Ray Serve deployment overhead
- ✅ Fast - Direct cognitive core usage
- ✅ Simple - Easy to understand and modify
- ✅ Resource-efficient - Minimal memory and CPU usage

### Advanced Examples (Production Ready)

#### 3. Optimized Ray Serve Integration
```bash
docker exec -it seedcore-api python examples/optimized_dspy_integration_example.py
```
Production-ready example with proper namespace management and conflict handling.

**Features:**
- ✅ **Conflict Prevention**: Checks for existing deployments
- ✅ **Namespace Management**: Consistent with serve_entrypoint.py
- ✅ **Health Monitoring**: Built-in health checks and status reporting
- ✅ **Resource Optimization**: Single deployment with proper route management
- ✅ **Integration**: Works seamlessly with existing Ray cluster

#### 4. Debug and Troubleshooting
```bash
docker exec -it seedcore-api python examples/debug_dspy.py
```
Comprehensive debugging tool for DSPy integration issues.

### Example Comparison

| Example | Use Case | Resource Usage | Complexity | Production Ready |
|---------|----------|----------------|------------|------------------|
| `test_simple_dspy.py` | Basic testing | Minimal | Low | ❌ |
| `simple_dspy_example.py` | Development | Low | Low | ❌ |
| `optimized_dspy_integration_example.py` | Production | Medium | Medium | ✅ |
| `debug_dspy.py` | Troubleshooting | Low | Low | ❌ |

## 🔧 Troubleshooting

### Common Issues and Solutions

#### 1. API Key Issues
**Problem**: `OPENAI_API_KEY` not found or invalid
```bash
# Check if API key is set
docker exec -it seedcore-api env | grep OPENAI

# Set API key in docker/.env file
echo "OPENAI_API_KEY=sk-your-actual-api-key" >> docker/.env

# Restart API container to pick up new environment
./sc-cmd.sh restart-api
```

#### 2. Ray Serve Deployment Conflicts
**Problem**: `Prefix / is being used by application "seedcore-ml"`
```bash
# Use the optimized example that handles conflicts
docker exec -it seedcore-api python examples/optimized_dspy_integration_example.py
```

#### 3. Cognitive Core Not Available
**Problem**: `cognitive_core_available: false` in status endpoint
```bash
# Check if cognitive core is initialized
docker exec -it seedcore-api python examples/debug_dspy.py

# Initialize cognitive core manually
docker exec -it seedcore-api python -c "
from seedcore.agents.cognitive_core import initialize_cognitive_core
core = initialize_cognitive_core()
print('Cognitive core initialized:', core is not None)
"
```

#### 4. Ray Cluster Issues
**Problem**: Ray dashboard errors or connection issues
```bash
# Restart Ray cluster
./sc-cmd.sh down
./sc-cmd.sh up

# Check Ray status
docker exec -it seedcore-api python -c "
import ray; ray.init(); print('Ray status:', ray.is_initialized())
"
```

### Debug Tools

#### 1. Status Endpoints
```bash
# Check DSPy status
curl http://localhost:8002/dspy/status

# Check Ray Serve status
curl http://localhost:8000/health

# Check cognitive core health (if deployed)
curl http://localhost:8000/cognitive/health
```

#### 2. Debug Scripts
```bash
# Comprehensive debugging
docker exec -it seedcore-api python examples/debug_dspy.py

# Test basic functionality
docker exec -it seedcore-api python examples/test_simple_dspy.py
```

#### 3. Logs
```bash
# Check API logs
./sc-cmd.sh logs api

# Check Ray head logs
./sc-cmd.sh logs ray-head

# Check specific container logs
docker logs seedcore-api --tail 50
```
```

## 📚 Detailed Usage

### Cognitive Task Types

The DSPy integration supports six specialized cognitive tasks:

#### 1. Failure Analysis (`FAILURE_ANALYSIS`)

Analyze agent failures and propose solutions.

```python
context = CognitiveContext(
    agent_id="agent_001",
    task_type=CognitiveTaskType.FAILURE_ANALYSIS,
    input_data={
        "incident_id": "incident_001",
        "error_message": "Task execution failed due to timeout",
        "agent_state": {
            "capability_score": 0.6,
            "memory_utilization": 0.4,
            "tasks_processed": 15
        }
    }
)
```

#### 2. Task Planning (`TASK_PLANNING`)

Plan complex tasks with multiple steps.

```python
context = CognitiveContext(
    agent_id="planner_agent",
    task_type=CognitiveTaskType.TASK_PLANNING,
    input_data={
        "task_description": "Analyze customer support data",
        "agent_capabilities": {
            "capability_score": 0.7,
            "data_analysis_skills": 0.8
        },
        "available_resources": {
            "time_constraint": "48 hours",
            "compute_power": "high"
        }
    }
)
```

#### 3. Decision Making (`DECISION_MAKING`)

Make decisions based on available information.

```python
context = CognitiveContext(
    agent_id="decision_agent",
    task_type=CognitiveTaskType.DECISION_MAKING,
    input_data={
        "decision_context": {
            "options": ["Option A", "Option B", "Option C"],
            "constraints": {"budget": 1000, "time": "1 week"}
        },
        "historical_data": {
            "previous_decisions": [...],
            "success_rates": {...}
        }
    }
)
```

#### 4. Problem Solving (`PROBLEM_SOLVING`)

Solve complex problems using systematic reasoning.

```python
context = CognitiveContext(
    agent_id="solver_agent",
    task_type=CognitiveTaskType.PROBLEM_SOLVING,
    input_data={
        "problem_statement": "System performance degradation",
        "constraints": {"downtime": "minimal", "cost": "low"},
        "available_tools": ["monitoring", "logging", "profiling"]
    }
)
```

#### 5. Memory Synthesis (`MEMORY_SYNTHESIS`)

Synthesize information from multiple memory sources.

```python
context = CognitiveContext(
    agent_id="synthesis_agent",
    task_type=CognitiveTaskType.MEMORY_SYNTHESIS,
    input_data={
        "memory_fragments": [
            {"content": "Fragment 1", "timestamp": 1234567890},
            {"content": "Fragment 2", "timestamp": 1234567891}
        ],
        "synthesis_goal": "Identify patterns in system behavior"
    }
)
```

#### 6. Capability Assessment (`CAPABILITY_ASSESSMENT`)

Assess agent capabilities and suggest improvements.

```python
context = CognitiveContext(
    agent_id="assessment_agent",
    task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT,
    input_data={
        "performance_data": {"tasks_processed": 50, "success_rate": 0.84},
        "current_capabilities": {"capability_score": 0.75},
        "target_capabilities": {"capability_score": 0.9}
    }
)
```

### Ray Agent Integration

Ray agents now have built-in cognitive reasoning capabilities:

```python
# Create agent
agent = RayAgent.remote("cognitive_agent", {'E': 0.7, 'S': 0.2, 'O': 0.1})

# Cognitive reasoning methods
await agent.reason_about_failure.remote("incident_001")
await agent.plan_complex_task.remote("Analyze data", {"time": "2 hours"})
await agent.make_decision.remote({"options": ["A", "B"]}, {"history": []})
await agent.synthesize_memory.remote([{"content": "..."}], "Find patterns")
await agent.assess_capabilities.remote({"target": "..."})
```

### Ray Serve Deployment

For scalable, shared inference:

```python
from seedcore.serve.cognitive_serve import deploy_cognitive_core, CognitiveCoreClient

# Deploy cognitive core
deploy_cognitive_core(
    llm_provider="openai",
    model="gpt-4o",
    num_replicas=2,
    name="cognitive_core"
)

# Use client
client = CognitiveCoreClient("cognitive_core")
result = await client.reason_about_failure("agent_001", incident_context)
```

### FastAPI Endpoints

Lightweight testing and experimentation:

```bash
# Check status
curl http://localhost:8002/dspy/status

# Analyze failure
curl -X POST http://localhost:8002/dspy/reason-about-failure \
  -H "Content-Type: application/json" \
  -d '{"incident_id": "incident_001", "agent_id": "agent_001"}'

# Plan task
curl -X POST http://localhost:8002/dspy/plan-task \
  -H "Content-Type: application/json" \
  -d '{"task_description": "Analyze data", "agent_id": "agent_001"}'
```

## 🔧 Configuration

### LLM Configuration

The cognitive core uses the same LLM configuration system as SeedCore:

```python
from seedcore.config.llm_config import configure_llm_openai

# Configure OpenAI
configure_llm_openai(
    api_key="your-key",
    model="gpt-4o",
    max_tokens=1024,
    temperature=0.7
)
```

### Environment Variables

```bash
# LLM Provider Configuration
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=1024
LLM_TEMPERATURE=0.7
OPENAI_API_KEY=your-api-key

# Cognitive Core Configuration
LLM_ENABLE_CACHING=true
LLM_CACHE_TTL=3600
LLM_LOG_REQUESTS=true
LLM_LOG_TOKENS=true
```

## 🎯 Advanced Usage

### Custom DSPy Signatures

You can extend the cognitive core with custom signatures:

```python
import dspy

class CustomSignature(dspy.Signature):
    input_field = dspy.InputField(desc="Your input description")
    output_field = dspy.OutputField(desc="Your output description")

# Add to CognitiveCore class
self.custom_handler = dspy.ChainOfThought(CustomSignature)
```

### Energy Integration

Cognitive reasoning is integrated with SeedCore's energy system:

```python
# Energy cost is automatically calculated and tracked
reg_delta = 0.01 * len(reasoning_result.get("thought", ""))

# Update energy state
current_energy = agent.get_energy_state()
current_energy["cognitive_cost"] += reg_delta
agent.update_energy_state(current_energy)
```

### Memory Integration

Cognitive tasks have access to agent memory context:

```python
# Memory context is automatically provided
memory_context = {
    "memory_utilization": agent.mem_util,
    "memory_writes": agent.memory_writes,
    "compression_gain": agent.total_compression_gain,
    "skill_deltas": agent.skill_deltas.copy()
}
```

## 📊 Monitoring and Observability

### Performance Metrics

Track cognitive reasoning performance:

```python
# Get cognitive core status
status = await get_dspy_status()
print(f"Cognitive core available: {status['cognitive_core_available']}")
print(f"Serve client available: {status['serve_client_available']}")
```

### Logging

Comprehensive logging is enabled by default:

```python
import logging
logging.getLogger("seedcore.agents.cognitive_core").setLevel(logging.DEBUG)
```

### Metrics Collection

Monitor cognitive reasoning costs and performance:

```python
# Energy metrics
energy_state = agent.get_energy_state()
cognitive_cost = energy_state.get("cognitive_cost", 0.0)

# Performance metrics
stats = agent.get_summary_stats()
capability_score = stats.get("capability_score", 0.0)
```

## 🚀 Deployment Strategies

### Development Mode

For rapid prototyping and testing:

```python
# Direct cognitive core usage
cognitive_core = initialize_cognitive_core()
result = cognitive_core(context)
```

### Production Mode

For scalable, production workloads:

```python
# Ray Serve deployment
deploy_cognitive_core(num_replicas=4, name="prod_cognitive_core")
client = CognitiveCoreClient("prod_cognitive_core")
result = await client.reason_about_failure(agent_id, incident_context)
```

### Hybrid Mode

Combine both approaches:

```python
# Use embedded core for simple tasks
if task_complexity < 0.5:
    result = agent.reason_about_failure.remote(incident_id)
else:
    # Use Ray Serve for complex tasks
    result = await client.reason_about_failure(agent_id, incident_context)
```

## 🔍 Troubleshooting

### Common Issues

1. **API Key Not Set**
   ```bash
   export OPENAI_API_KEY="your-key"
   ```

2. **Ray Serve Not Available**
   ```python
   # Fallback to direct cognitive core
   cognitive_core = get_cognitive_core()
   if not cognitive_core:
       cognitive_core = initialize_cognitive_core()
   ```

3. **Memory Systems Not Available**
   ```python
   # Check memory client availability
   if not agent.mfb_client:
       logger.warning("Memory client not available")
   ```

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Test cognitive core
cognitive_core = initialize_cognitive_core()
print(f"Cognitive core: {cognitive_core}")
```

### Validation

Validate cognitive core configuration:

```python
from seedcore.agents.cognitive_core import get_cognitive_core

core = get_cognitive_core()
if core:
    print("✅ Cognitive core is available")
else:
    print("❌ Cognitive core not available")
```

## 📈 Performance Optimization

### Caching

Enable response caching to reduce API costs:

```bash
LLM_ENABLE_CACHING=true
LLM_CACHE_TTL=3600
```

### Rate Limiting

Configure rate limits to avoid API quotas:

```bash
LLM_RATE_LIMIT_REQUESTS_PER_MINUTE=60
LLM_RATE_LIMIT_TOKENS_PER_MINUTE=150000
```

### Resource Allocation

For Ray Serve deployments:

```python
deploy_cognitive_core(
    num_replicas=4,  # Scale based on load
    ray_actor_options={
        "num_cpus": 2,
        "memory": 4 * 1024 * 1024 * 1024,  # 4GB
    }
)
```

## 🔮 Future Enhancements

### Planned Features

1. **Multi-Provider Support**: Anthropic, Google, Azure
2. **Custom Signature Builder**: Visual signature creation
3. **Advanced Caching**: Redis-based distributed caching
4. **Performance Analytics**: Detailed reasoning performance metrics
5. **A/B Testing**: Compare different reasoning strategies

### Extension Points

The architecture is designed for easy extension:

```python
# Add new task types
class NEW_TASK_TYPE(Enum):
    CUSTOM_TASK = "custom_task"

# Add new signatures
class CustomTaskSignature(dspy.Signature):
    # Define your signature

# Extend CognitiveCore
class ExtendedCognitiveCore(CognitiveCore):
    def __init__(self):
        super().__init__()
        self.custom_handler = dspy.ChainOfThought(CustomTaskSignature)
```

## 📚 Examples

See `examples/dspy_integration_example.py` for comprehensive examples covering:

- Basic cognitive core usage
- Task planning and decision making
- Ray agent integration
- Ray Serve deployment
- Memory synthesis
- Capability assessment

## 🤝 Contributing

To contribute to the DSPy integration:

1. Follow the existing code patterns
2. Add comprehensive tests
3. Update documentation
4. Ensure backward compatibility
5. Add performance benchmarks

## 📄 License

This DSPy integration follows the same Apache 2.0 license as SeedCore.

---

**Next Steps**: Start with the embedded cognitive core for rapid experimentation, then scale to Ray Serve deployment as your workloads grow. The integration provides both elegance and power, enabling you to build sophisticated, intelligent agent ecosystems. 