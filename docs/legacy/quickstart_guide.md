# DSPy Integration Quickstart Guide

This guide provides a complete end-to-end walkthrough for getting started with the DSPy integration in SeedCore, from initial setup to running your first cognitive reasoning tasks.

## 🚀 Prerequisites

Before you begin, ensure you have:

- **Python 3.8+** installed
- **Docker** and **Docker Compose** installed
- **Git** for cloning the repository
- **OpenAI API key** (or other LLM provider key)

## 📋 Step 1: Clone and Setup

### 1.1 Clone the Repository

```bash
git clone https://github.com/your-org/seedcore.git
cd seedcore
```

### 1.2 Set Up Environment

```bash
# Copy environment template
cp docker/env.example docker/.env

# Edit the environment file with your API keys
nano docker/.env
```

**Required Environment Variables:**
```bash
# LLM Configuration
OPENAI_API_KEY=sk-your-openai-api-key-here
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=1024
LLM_TEMPERATURE=0.7

# Optional: Additional LLM providers
ANTHROPIC_API_KEY=sk-ant-your-key-here
GOOGLE_API_KEY=your-google-api-key-here
```

### 1.3 Build and Start Services

```bash
# Build Docker images
docker-compose build

# Start services
docker-compose up -d

# Check service status
docker-compose ps
```

## 🧠 Step 2: Verify Installation

### 2.1 Check Service Health

```bash
# Check API health
curl http://localhost:8002/health

# Check DSPy status
curl http://localhost:8002/dspy/status
```

Expected response:
```json
{
  "success": true,
  "cognitive_core_available": true,
  "serve_client_available": false,
  "supported_task_types": [
    "failure_analysis",
    "task_planning", 
    "decision_making",
    "problem_solving",
    "memory_synthesis",
    "capability_assessment"
  ],
  "timestamp": 1234567890.123
}
```

### 2.2 Run Basic Example

```bash
# Run the integration example
docker exec -it seedcore-api python examples/dspy_integration_example.py
```

You should see output like:
```
🧠 DSPy Integration Examples for SeedCore
============================================================

=== Example 1: Basic Cognitive Core Usage ===
✅ Cognitive core initialized: <CognitiveCore object>
🔍 Failure Analysis Result:
  Success: True
  Thought Process: The task failed due to timeout...
  Proposed Solution: Increase timeout and add retry logic...
  Confidence Score: 0.85

✅ All DSPy integration examples completed successfully!
```

## 🎯 Step 3: Your First Cognitive Task

### 3.1 Basic Failure Analysis

Create a simple Python script to test cognitive reasoning:

```python
# test_cognitive.py
import requests
import json

# Test failure analysis
response = requests.post(
    "http://localhost:8002/dspy/reason-about-failure",
    json={
        "incident_id": "test_incident_001",
        "agent_id": "my_first_agent"
    }
)

result = response.json()
print("Failure Analysis Result:")
print(f"Success: {result.get('success')}")
print(f"Thought Process: {result.get('thought_process', '')[:200]}...")
print(f"Proposed Solution: {result.get('proposed_solution', '')[:200]}...")
print(f"Confidence: {result.get('confidence_score', 0.0)}")
```

Run the test:
```bash
python test_cognitive.py
```

### 3.2 Task Planning

```python
# Test task planning
response = requests.post(
    "http://localhost:8002/dspy/plan-task",
    json={
        "task_description": "Build a monitoring dashboard for system metrics",
        "agent_id": "planner_agent",
        "agent_capabilities": {
            "capability_score": 0.8,
            "frontend_skills": 0.9,
            "backend_skills": 0.7
        },
        "available_resources": {
            "time_limit": "2 weeks",
            "team_size": 3,
            "budget": 5000
        }
    }
)

result = response.json()
print("Task Planning Result:")
print(f"Success: {result.get('success')}")
print(f"Plan: {result.get('step_by_step_plan', '')[:300]}...")
```

## 🔧 Step 4: Advanced Usage

### 4.1 Ray Agent Integration

Create a Ray agent with cognitive capabilities:

```python
# advanced_agent.py
import ray
import asyncio
from seedcore.agents.ray_agent import RayAgent

# Initialize Ray
ray.init(ignore_reinit_error=True)

# Create agent
agent = RayAgent.remote("cognitive_agent_001", {'E': 0.7, 'S': 0.2, 'O': 0.1})

# Test agent functionality
agent_id = ray.get(agent.get_id.remote())
print(f"Created agent: {agent_id}")

# Test cognitive reasoning
result = await agent.reason_about_failure.remote("incident_002")
print(f"Agent analysis: {result.get('thought_process', '')[:200]}...")
```

### 4.2 Ray Serve Deployment

For scalable, production workloads:

```python
# deploy_cognitive.py
from seedcore.serve.cognitive_serve import deploy_cognitive_core, CognitiveCoreClient

# Deploy cognitive core
deployment_name = deploy_cognitive_core(
    llm_provider="openai",
    model="gpt-4o",
    num_replicas=2,
    name="production_cognitive_core"
)

print(f"Deployed cognitive core: {deployment_name}")

# Use the deployment
client = CognitiveCoreClient("production_cognitive_core")
result = await client.reason_about_failure("agent_001", {
    "incident_id": "prod_incident_001",
    "error_message": "Database connection timeout"
})

print(f"Production result: {result}")
```

## 📊 Step 5: Monitoring and Metrics

### 5.1 Check Cognitive Metrics

```bash
# Get cognitive task metrics
curl http://localhost:8002/metrics | grep cognitive

# Check resource status
curl http://localhost:8002/dspy/status
```

### 5.2 Monitor Agent Capabilities

```python
# monitor_capabilities.py
from seedcore.agents.capability_feedback import get_agent_assessment, get_improvement_plan

# Get agent assessment
assessment = get_agent_assessment("my_first_agent")
if assessment:
    print(f"Agent Level: {assessment.current_level.value}")
    print(f"Overall Score: {assessment.overall_score:.3f}")
    print(f"Strengths: {assessment.strengths}")
    print(f"Improvement Areas: {assessment.improvement_areas}")

# Get improvement plan
plan = get_improvement_plan("my_first_agent")
print(f"Improvement Plan: {json.dumps(plan, indent=2)}")
```

## 🔍 Step 6: Troubleshooting

### 6.1 Common Issues

**Issue: "Cognitive core not initialized"**
```bash
# Check API key
echo $OPENAI_API_KEY

# Restart services
docker-compose restart api

# Check logs
docker-compose logs api
```

**Issue: "Rate limit exceeded"**
```bash
# Check rate limiting configuration
curl http://localhost:8002/dspy/status

# Wait and retry, or adjust rate limits in configuration
```

**Issue: "Task timeout"**
```bash
# Check resource usage
docker stats

# Increase timeout in configuration
# Edit docker/.env and add:
LLM_TIMEOUT=120
```

### 6.2 Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Test cognitive core
from seedcore.cognitive.cognitive_core import initialize_cognitive_core
core = initialize_cognitive_core()
print(f"Cognitive core: {core}")
```

## 🎯 Step 7: Next Steps

### 7.1 Explore Examples

- **Basic Examples**: `examples/dspy_integration_example.py`
- **Advanced Patterns**: `examples/llm_config_example.py`
- **Custom Plugins**: Create your own cognitive task types

### 7.2 Production Deployment

1. **Configure Production Environment**:
   ```bash
   # Set production environment variables
   export ENVIRONMENT=production
   export LOG_LEVEL=INFO
   export METRICS_ENABLED=true
   ```

2. **Deploy with Ray Serve**:
   ```python
   # Deploy for production
   deploy_cognitive_core(
       num_replicas=4,
       ray_actor_options={
           "num_cpus": 2,
           "memory": 4 * 1024 * 1024 * 1024,  # 4GB
       }
   )
   ```

3. **Set Up Monitoring**:
   ```bash
   # Configure Prometheus metrics
   # Set up Grafana dashboards
   # Configure alerting
   ```

### 7.3 Custom Development

1. **Create Custom Signatures**:
   ```python
   import dspy
   from seedcore.cognitive.cognitive_registry import cognitive_signature

   @cognitive_signature("custom_analysis")
   class CustomAnalysisSignature(dspy.Signature):
       input_data = dspy.InputField(desc="Input data")
       analysis_result = dspy.OutputField(desc="Analysis result")
   ```

2. **Add Custom Handlers**:
   ```python
   from seedcore.cognitive.cognitive_registry import cognitive_handler

   @cognitive_handler("custom_analysis")
   def custom_analysis_handler(context):
       # Your custom logic here
       return {"result": "custom analysis complete"}
   ```

## 📚 Additional Resources

- **Full Documentation**: `docs/dspy_integration_guide.md`
- **API Reference**: `docs/api/reference/`
- **Configuration Guide**: `docs/configuration.md`
- **Troubleshooting**: `docs/troubleshooting.md`

## 🆘 Getting Help

- **Issues**: Create an issue on GitHub
- **Discussions**: Use GitHub Discussions
- **Documentation**: Check the docs folder
- **Examples**: Review the examples directory

---

**Congratulations!** You've successfully set up and tested the DSPy integration with SeedCore. You now have a powerful cognitive reasoning system that can analyze failures, plan tasks, make decisions, and continuously improve agent capabilities.

**Next Steps**: Explore the advanced features, create custom cognitive tasks, and scale your deployment for production workloads. 