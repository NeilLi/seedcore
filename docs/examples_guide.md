# DSPy Examples Guide

This guide provides comprehensive documentation for all DSPy integration examples in SeedCore, from simple testing to production-ready deployments.

## 📋 Overview

SeedCore provides multiple DSPy examples to suit different use cases:

| Example | Purpose | Resource Usage | Complexity | Production Ready |
|---------|---------|----------------|------------|------------------|
| `test_simple_dspy.py` | Basic testing | Minimal | Low | ❌ |
| `simple_dspy_example.py` | Development | Low | Low | ❌ |
| `optimized_dspy_integration_example.py` | Production | Medium | Medium | ✅ |
| `debug_dspy.py` | Troubleshooting | Low | Low | ❌ |

## 🧪 Simple Examples (Development)

### 1. Basic Testing (`test_simple_dspy.py`)

**Purpose**: Test the basic DSPy integration structure without requiring an API key.

**Usage**:
```bash
docker exec -it seedcore-api python examples/test_simple_dspy.py
```

**Features**:
- ✅ No API key required
- ✅ Tests imports and basic structure
- ✅ Validates cognitive task types
- ✅ Checks API endpoints
- ✅ Quick validation of setup

**Output Example**:
```
🧪 Simple DSPy Integration Test (No API Key Required)
============================================================
🔍 Testing imports...
✅ All cognitive core imports successful
✅ LLM config imports successful

🔍 Testing cognitive task types...
✅ Found 6 task types:
   - failure_analysis
   - task_planning
   - decision_making
   - problem_solving
   - memory_synthesis
   - capability_assessment

📊 Test Summary
============================================================
✅ PASS Imports
✅ PASS Cognitive Task Types
✅ PASS Cognitive Context
✅ PASS Cognitive Core Structure
✅ PASS LLM Configuration
✅ PASS API Endpoints

Results: 6/6 tests passed
🎉 All tests passed! DSPy integration is ready.
```

### 2. Simple DSPy Integration (`simple_dspy_example.py`)

**Purpose**: Demonstrate all cognitive task types with direct cognitive core usage.

**Usage**:
```bash
docker exec -it seedcore-api python examples/simple_dspy_example.py
```

**Features**:
- ✅ Lightweight - No Ray Serve deployment overhead
- ✅ Fast - Direct cognitive core usage (2-5 seconds per task)
- ✅ Simple - Easy to understand and modify
- ✅ Resource-efficient - Minimal memory and CPU usage
- ✅ All 6 cognitive task types demonstrated

**Cognitive Tasks Demonstrated**:

1. **Failure Analysis**: Analyze agent failures and propose solutions
2. **Task Planning**: Create step-by-step plans for complex tasks
3. **Decision Making**: Make decisions with reasoning and confidence
4. **Problem Solving**: Solve problems with systematic approaches
5. **Memory Synthesis**: Synthesize information from multiple sources
6. **Capability Assessment**: Assess agent capabilities and suggest improvements

**Output Example**:
```
🧠 Simple DSPy Integration Example for SeedCore
============================================================
✅ LLM configuration loaded

🚀 Initializing cognitive core...
✅ Cognitive core initialized successfully

=== Example 1: Failure Analysis ===
✅ Failure analysis completed
   Thought: The root cause of the task timeout appears to be related to the complexity...
   Solution: To prevent recurrence, we should first analyze the specific task...
   Confidence: 1.0

=== Example 2: Task Planning ===
✅ Task planning completed
   Plan: 1. Load the dataset in manageable chunks to optimize memory usage...
   Complexity: 7 - The task involves multiple steps that require careful management...
   Risk: Potential risks include memory overflow, exceeding the time limit...

🎉 Simple DSPy integration example completed!
```

## 🚀 Advanced Examples (Production)

### 3. Optimized Ray Serve Integration (`optimized_dspy_integration_example.py`)

**Purpose**: Production-ready example with proper namespace management and conflict handling.

**Usage**:
```bash
docker exec -it seedcore-api python examples/optimized_dspy_integration_example.py
```

**Key Features**:
- ✅ **Conflict Prevention**: Checks for existing deployments
- ✅ **Namespace Management**: Consistent with serve_entrypoint.py
- ✅ **Health Monitoring**: Built-in health checks and status reporting
- ✅ **Resource Optimization**: Single deployment with proper route management
- ✅ **Integration**: Works seamlessly with existing Ray cluster

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                    Optimized Deployment                     │
├─────────────────────────────────────────────────────────────┤
│  App Name: "cognitive"                            │
│  Route Prefix: "/cognitive"                                │
│  Namespace: Default (consistent with serve_entrypoint.py)  │
│  Health Endpoint: "/cognitive/health"                      │
└─────────────────────────────────────────────────────────────┘
```

**Deployment Process**:
1. **Conflict Detection**: Checks for existing deployments
2. **Ray Initialization**: Ensures proper Ray cluster connection
3. **Serve Management**: Starts Serve if not running
4. **Deployment**: Creates optimized deployment with proper naming
5. **Health Check**: Waits for deployment to be ready
6. **Testing**: Tests all cognitive functions through Ray Serve
7. **Cleanup**: Proper undeployment and cleanup

**Output Example**:
```
🧠 Optimized DSPy Integration Example for SeedCore
============================================================
✅ LLM configuration loaded

=== Example 1: Basic Cognitive Core Usage ===
✅ Cognitive core initialized
✅ Failure analysis completed

=== Example 2: Optimized Ray Serve Deployment ===
🔍 Existing applications: ['seedcore-ml']
📝 Cognitive app 'cognitive' not found, will deploy
🚀 Deploying cognitive core as 'cognitive'...
✅ Connected to Ray cluster at ray://ray-head:10001
✅ Serve is running
⏳ Waiting for cognitive core deployment to be ready...
✅ Cognitive core deployed successfully as 'cognitive'
   Route: /cognitive
   Health: http://localhost:8000/cognitive/health

✅ Created cognitive core client for 'cognitive'

🔍 Ray Serve Failure Analysis Result:
  Success: True
  Agent ID: serve_agent_001
  Incident ID: serve_test_001
  Thought Process: The root cause of the failure likely stems from a mismatch...
  Proposed Solution: To prevent recurrence, the agent's capability should be enhanced...

📊 Deployment Status:
  App: cognitive
  Status: RUNNING
  Route: /cognitive
  Deployments: ['cognitive']

🎉 Optimized DSPy integration example completed!
```

### 4. Debug and Troubleshooting (`debug_dspy.py`)

**Purpose**: Comprehensive debugging tool for DSPy integration issues.

**Usage**:
```bash
docker exec -it seedcore-api python examples/debug_dspy.py
```

**Features**:
- ✅ Step-by-step component testing
- ✅ Detailed error reporting
- ✅ API key validation
- ✅ DSPy functionality testing
- ✅ Cognitive core initialization testing
- ✅ Ray Serve deployment testing

**Debug Tests**:
1. **LLM Configuration**: Tests API key and configuration
2. **DSPy Imports**: Validates DSPy installation
3. **Cognitive Core**: Tests initialization and basic functionality
4. **Simple DSPy Call**: Tests basic DSPy functionality
5. **Cognitive Task**: Tests full cognitive reasoning pipeline

## 🔧 Configuration

### Environment Variables

All examples use the following environment variables:

```bash
# Required for LLM functionality
OPENAI_API_KEY=sk-your-openai-api-key

# Optional: Ray cluster configuration
RAY_ADDRESS=ray://ray-head:10001

# Optional: Model configuration
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=1024
LLM_TEMPERATURE=0.7
```

### API Endpoints

The examples provide access to various endpoints:

| Endpoint | Description | Example |
|----------|-------------|---------|
| `GET /dspy/status` | DSPy system status | `curl http://localhost:8002/dspy/status` |
| `POST /dspy/reason-about-failure` | Failure analysis | `curl -X POST "http://localhost:8002/dspy/reason-about-failure?incident_id=test&agent_id=agent"` |
| `GET /cognitive/health` | Cognitive core health | `curl http://localhost:8000/cognitive/health` |

## 🚨 Troubleshooting

### Common Issues

#### 1. API Key Not Set
```bash
# Check if API key is set
docker exec -it seedcore-api env | grep OPENAI

# Set API key and restart
echo "OPENAI_API_KEY=sk-your-key" >> docker/.env
./sc-cmd.sh restart-api
```

#### 2. Ray Serve Conflicts
```bash
# Use optimized example that handles conflicts
docker exec -it seedcore-api python examples/optimized_dspy_integration_example.py
```

#### 3. Cognitive Core Not Available
```bash
# Run debug script
docker exec -it seedcore-api python examples/debug_dspy.py
```

### Debug Commands

```bash
# Check system status
curl http://localhost:8002/dspy/status | jq .

# Check Ray cluster
docker exec -it seedcore-api python -c "import ray; ray.init(); print('Ray status:', ray.is_initialized())"

# Check Serve applications
docker exec -it seedcore-api python -c "from ray import serve; print('Apps:', list(serve.list_applications().keys()))"

# Check logs
./sc-cmd.sh logs api | tail -20
```

## 📊 Performance Comparison

| Metric | Simple Example | Optimized Example |
|--------|----------------|-------------------|
| **Startup Time** | 2-5 seconds | 10-30 seconds |
| **Memory Usage** | ~500MB | ~2GB |
| **CPU Usage** | Low | Medium |
| **Deployment Complexity** | None | Ray Serve |
| **Scalability** | Single instance | Multiple replicas |
| **Production Ready** | ❌ | ✅ |

## 🎯 Recommendations
## 🧪 Unified State & HGNN Examples (New)

### 1. Unified State Verification (`examples/verify_unified_state_hgnn.py`)
- Purpose: End-to-end verification of unified state assembly, HGNN pattern shim wiring, and energy computation.
- Highlights:
  - Simulates OCPS escalations and reads `E_patterns` via `SHIM.get_E_patterns()`
  - Builds `UnifiedState` (`agents`, `organs`, `system.E_patterns`, `memory`)
  - Uses energy calculator unified APIs to compute total energy and breakdown
- Run:
```bash
docker exec -it seedcore-api python examples/verify_unified_state_hgnn.py
```

### 2. HGNN Shim Quick Test (`examples/test_hgnn_shim_simple.py`)
- Purpose: Smoke test of pattern shim decay, normalization, and mapping.
- Run:
```bash
docker exec -it seedcore-api python examples/test_hgnn_shim_simple.py
```


### For Development
- Start with `test_simple_dspy.py` to validate setup
- Use `simple_dspy_example.py` for development and testing
- Use `debug_dspy.py` for troubleshooting

### For Production
- Use `optimized_dspy_integration_example.py` for production deployments
- Ensure proper API key configuration
- Monitor deployment status and health endpoints
- Use proper error handling and logging

### For Testing
- Use `test_simple_dspy.py` for CI/CD validation
- Use `debug_dspy.py` for comprehensive testing
- Test all cognitive task types before deployment
