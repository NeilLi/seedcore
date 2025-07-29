#!/usr/bin/env python3
"""
Simple script to deploy a basic Ray Serve application.
"""

import ray
from ray import serve
from fastapi import FastAPI
import time

# Initialize Ray Serve
serve.start(detached=True)

# Create a simple FastAPI app
app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from Ray Serve!", "timestamp": time.time()}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "simple-serve"}

# Deploy the application
@serve.deployment(name="simple-serve", num_replicas=1)
@serve.ingress(app)
class SimpleServe:
    def __init__(self):
        print("🚀 Simple Serve initialized!")

def main():
    print("🚀 Deploying simple Ray Serve application...")
    
    # Deploy the application
    app = SimpleServe.bind()
    serve.run(app, name="simple-serve")
    
    print("✅ Simple Serve deployed successfully!")
    print("📊 Check the dashboard at: http://localhost:8265/#/serve")
    print("🔗 Test endpoint: http://localhost:8000/")

if __name__ == "__main__":
    main() 