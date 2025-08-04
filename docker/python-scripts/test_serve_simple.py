#!/usr/bin/env python3
"""
Minimal Ray Serve test to debug proxy actor issues
"""

import ray
from ray import serve
import time

# Initialize Ray
ray.init(address="auto", namespace="serve")

# Create a simple FastAPI app
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from Ray Serve!"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Create a minimal deployment
@serve.deployment(
    num_replicas=1,
    ray_actor_options={"num_cpus": 0.1, "num_gpus": 0, "memory": 100000000}
)
@serve.ingress(app)
class SimpleService:
    def __init__(self):
        print("✅ SimpleService initialized")

if __name__ == "__main__":
    print("🚀 Starting minimal Ray Serve test...")
    
    # Check cluster resources
    print(f"🔍 Cluster resources: {ray.cluster_resources()}")
    
    # Start serve
    print("🔧 Starting Ray Serve...")
    serve.run(SimpleService.bind(), name="test-simple")
    
    print("✅ Ray Serve started successfully!")
    print("📊 Test endpoints:")
    print("   - Root: http://localhost:8000/")
    print("   - Health: http://localhost:8000/health")
    
    # Keep running
    while True:
        time.sleep(10)
        print("�� Still running...") 