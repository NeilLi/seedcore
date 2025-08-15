#!/usr/bin/env python3
"""
Cognitive Serve Entrypoint for SeedCore

This service runs the cognitive core and related reasoning services
as a separate Ray Serve deployment, independent of the main API.
"""

import os
import sys
import time
import signal
import traceback
from typing import Dict, Any, Optional

import ray
from ray import serve
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Import cognitive core components
from seedcore.agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)

# -------------------------------
# Configuration
# -------------------------------
RAY_ADDR = os.getenv("RAY_ADDRESS", "auto")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore")
HTTP_HOST = os.getenv("SERVE_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("SERVE_HTTP_PORT", "8000"))

# -------------------------------
# Request/Response Models
# -------------------------------
class CognitiveRequest(BaseModel):
    """Request model for cognitive tasks."""
    agent_id: str
    incident_context: Dict[str, Any] = None
    task_description: str = None
    decision_context: Dict[str, Any] = None
    historical_data: Dict[str, Any] = None
    problem_statement: str = None
    constraints: Dict[str, Any] = None
    available_tools: Dict[str, Any] = None
    memory_fragments: list = None
    synthesis_goal: str = None
    performance_data: Dict[str, Any] = None
    current_capabilities: Dict[str, Any] = None
    target_capabilities: Dict[str, Any] = None

class CognitiveResponse(BaseModel):
    """Response model for cognitive tasks."""
    success: bool
    agent_id: str
    result: Dict[str, Any]
    error: Optional[str] = None

# -------------------------------
# FastAPI App
# -------------------------------
app = FastAPI(title="SeedCore Cognitive Service", version="1.0.0")

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "seedcore-cognitive",
        "timestamp": time.time(),
        "ray_cluster": "connected" if ray.is_initialized() else "disconnected"
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "SeedCore Cognitive Service is running",
        "endpoints": [
            "/cognitive/reason-about-failure",
            "/cognitive/plan-task", 
            "/cognitive/make-decision",
            "/cognitive/solve-problem",
            "/cognitive/synthesize-memory",
            "/cognitive/assess-capabilities"
        ],
        "timestamp": time.time()
    }

# -------------------------------
# Cognitive Endpoints
# -------------------------------
@app.post("/cognitive/reason-about-failure")
async def reason_about_failure(request: CognitiveRequest):
    """Analyze agent failures using cognitive reasoning."""
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        context = CognitiveContext(
            agent_id=request.agent_id,
            task_type=CognitiveTaskType.FAILURE_ANALYSIS,
            input_data=request.incident_context or {}
        )
        
        result = cognitive_core(context)
        return CognitiveResponse(
            success=True,
            agent_id=request.agent_id,
            result={
                "thought_process": result.get("thought", ""),
                "proposed_solution": result.get("proposed_solution", ""),
                "confidence_score": result.get("confidence_score", 0.0)
            }
        )
    except Exception as e:
        return CognitiveResponse(
            success=False,
            agent_id=request.agent_id,
            result={},
            error=str(e)
        )

@app.post("/cognitive/plan-task")
async def plan_task(request: CognitiveRequest):
    """Plan complex tasks using cognitive reasoning."""
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        input_data = {
            "task_description": request.task_description,
            "agent_capabilities": request.current_capabilities or {"capability_score": 0.5},
            "available_resources": request.available_tools or {}
        }
        
        context = CognitiveContext(
            agent_id=request.agent_id,
            task_type=CognitiveTaskType.TASK_PLANNING,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        return CognitiveResponse(
            success=True,
            agent_id=request.agent_id,
            result={
                "step_by_step_plan": result.get("step_by_step_plan", ""),
                "estimated_complexity": result.get("estimated_complexity", ""),
                "risk_assessment": result.get("risk_assessment", "")
            }
        )
    except Exception as e:
        return CognitiveResponse(
            success=False,
            agent_id=request.agent_id,
            result={},
            error=str(e)
        )

@app.post("/cognitive/make-decision")
async def make_decision(request: CognitiveRequest):
    """Make decisions using cognitive reasoning."""
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        input_data = {
            "decision_context": request.decision_context or {},
            "historical_data": request.historical_data or {}
        }
        
        context = CognitiveContext(
            agent_id=request.agent_id,
            task_type=CognitiveTaskType.DECISION_MAKING,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        return CognitiveResponse(
            success=True,
            agent_id=request.agent_id,
            result={
                "reasoning": result.get("reasoning", ""),
                "decision": result.get("decision", ""),
                "confidence": result.get("confidence", 0.0),
                "alternative_options": result.get("alternative_options", "")
            }
        )
    except Exception as e:
        return CognitiveResponse(
            success=False,
            agent_id=request.agent_id,
            result={},
            error=str(e)
        )

@app.post("/cognitive/solve-problem")
async def solve_problem(request: CognitiveRequest):
    """Solve problems using cognitive reasoning."""
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        input_data = {
            "problem_statement": request.problem_statement,
            "constraints": request.constraints or {},
            "available_tools": request.available_tools or {}
        }
        
        context = CognitiveContext(
            agent_id=request.agent_id,
            task_type=CognitiveTaskType.PROBLEM_SOLVING,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        return CognitiveResponse(
            success=True,
            agent_id=request.agent_id,
            result={
                "solution_approach": result.get("solution_approach", ""),
                "solution_steps": result.get("solution_steps", ""),
                "success_metrics": result.get("success_metrics", "")
            }
        )
    except Exception as e:
        return CognitiveResponse(
            success=False,
            agent_id=request.agent_id,
            result={},
            error=str(e)
        )

@app.post("/cognitive/synthesize-memory")
async def synthesize_memory(request: CognitiveRequest):
    """Synthesize information from multiple memory sources."""
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        input_data = {
            "memory_fragments": request.memory_fragments or [],
            "synthesis_goal": request.synthesis_goal
        }
        
        context = CognitiveContext(
            agent_id=request.agent_id,
            task_type=CognitiveTaskType.MEMORY_SYNTHESIS,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        return CognitiveResponse(
            success=True,
            agent_id=request.agent_id,
            result={
                "synthesized_insight": result.get("synthesized_insight", ""),
                "confidence_level": result.get("confidence_level", 0.0),
                "related_patterns": result.get("related_patterns", "")
            }
        )
    except Exception as e:
        return CognitiveResponse(
            success=False,
            agent_id=request.agent_id,
            result={},
            error=str(e)
        )

@app.post("/cognitive/assess-capabilities")
async def assess_capabilities(request: CognitiveRequest):
    """Assess agent capabilities and suggest improvements."""
    try:
        cognitive_core = get_cognitive_core()
        if not cognitive_core:
            cognitive_core = initialize_cognitive_core()
        
        input_data = {
            "performance_data": request.performance_data or {},
            "current_capabilities": request.current_capabilities or {},
            "target_capabilities": request.target_capabilities or {}
        }
        
        context = CognitiveContext(
            agent_id=request.agent_id,
            task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT,
            input_data=input_data
        )
        
        result = cognitive_core(context)
        return CognitiveResponse(
            success=True,
            agent_id=request.agent_id,
            result={
                "capability_gaps": result.get("capability_gaps", ""),
                "improvement_plan": result.get("improvement_plan", ""),
                "priority_recommendations": result.get("priority_recommendations", "")
            }
        )
    except Exception as e:
        return CognitiveResponse(
            success=False,
            agent_id=request.agent_id,
            result={},
            error=str(e)
        )

# -------------------------------
# Ray Serve Deployment
# -------------------------------
@serve.deployment(
    name="seedcore-cognitive",
    num_replicas=2,
    ray_actor_options={
        "num_cpus": 1,
        "num_gpus": 0,
        "memory": 2 * 1024 * 1024 * 1024,  # 2GB memory
    }
)
@serve.ingress(app)
class CognitiveService:
    """Ray Serve deployment of the Cognitive Service."""
    
    def __init__(self):
        """Initialize the cognitive service."""
        print("🚀 Initializing SeedCore Cognitive Service...")
        
        # Initialize Ray if not already done
        try:
            if not ray.is_initialized():
                ray.init(address=RAY_ADDR, namespace=RAY_NS)
                print("✅ Ray initialized successfully")
            else:
                print("✅ Ray already initialized")
        except Exception as e:
            print(f"❌ Failed to initialize Ray: {e}")
            raise

# -------------------------------
# Main Entrypoint
# -------------------------------
def main():
    """Main entrypoint for the cognitive serve service."""
    print("🚀 Starting SeedCore Cognitive Service...")
    
    try:
        # Initialize Ray
        if not ray.is_initialized():
            ray.init(address=RAY_ADDR, namespace=RAY_NS)
            print(f"✅ Ray initialized at {RAY_ADDR}")
        
        # Start Serve
        serve.start(
            http_options={
                'host': HTTP_HOST,
                'port': HTTP_PORT
            },
            detached=True
        )
        print(f"✅ Serve started on {HTTP_HOST}:{HTTP_PORT}")
        
        # Deploy the cognitive service
        CognitiveService.deploy()
        print("✅ Cognitive service deployed successfully")
        
        # Keep the service running
        print("🔄 Cognitive service is running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            serve.shutdown()
            print("✅ Serve shutdown complete")
        except:
            pass

if __name__ == "__main__":
    main()
