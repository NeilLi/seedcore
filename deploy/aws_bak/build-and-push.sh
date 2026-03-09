#!/usr/bin/env bash
# Build and Push Docker Images to ECR
# Builds SeedCore and NIM images and pushes them to AWS ECR

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Load environment variables
load_env() {
    local env_file="${SCRIPT_DIR}/.env.aws"
    
    if [ ! -f "$env_file" ]; then
        error "Environment file not found: $env_file"
        echo "Please run ./aws-init.sh first to set up the environment"
        exit 1
    fi
    
    log "Loading environment variables from $env_file"
    source "$env_file"
}

# Login to ECR
login_ecr() {
    log "Logging in to ECR..."
    
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$ECR_REGISTRY"
    
    success "Successfully logged in to ECR"
}

# Build SeedCore image
build_seedcore() {
    log "Building SeedCore Docker image..."
    
    cd "$PROJECT_ROOT"
    
    # Build the image for linux/amd64 platform to run on AWS
    docker build --platform linux/amd64 -t "$ECR_REPO:$SEEDCORE_IMAGE_TAG" .
    
    # Tag for ECR
    docker tag "$ECR_REPO:$SEEDCORE_IMAGE_TAG" "$ECR_REPO:latest"
    
    success "SeedCore image built successfully"
}

# Build NIM Retrieval image
build_nim_retrieval() {
    log "Building NIM Retrieval Docker image..."
    
    # This would typically be in a separate repository or subdirectory
    # For now, we'll create a placeholder Dockerfile
    local nim_dir="${PROJECT_ROOT}/nim-retrieval"
    
    if [ ! -d "$nim_dir" ]; then
        warn "NIM Retrieval directory not found. Creating placeholder..."
        mkdir -p "$nim_dir"
        cat > "$nim_dir/Dockerfile" << 'EOF'
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF
        
        cat > "$nim_dir/requirements.txt" << 'EOF'
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
numpy==1.24.3
torch==2.1.0
transformers==4.35.0
sentence-transformers==2.2.2
EOF
        
        cat > "$nim_dir/main.py" << 'EOF'
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="NIM Retrieval Service", version="1.0.0")

class QueryRequest(BaseModel):
    query: str
    top_k: int = 5

class QueryResponse(BaseModel):
    results: list
    query: str

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    # Placeholder implementation
    return QueryResponse(
        query=request.query,
        results=[
            {"id": f"doc_{i}", "score": 0.9 - i * 0.1, "text": f"Document {i} content"}
            for i in range(request.top_k)
        ]
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
EOF
    fi
    
    cd "$nim_dir"
    
    # Build the image for linux/amd64 platform
    docker build --platform linux/amd64 -t "$ECR_NIM_REPO:$NIM_RETRIEVAL_TAG" .
    
    # Tag for ECR
    docker tag "$ECR_NIM_REPO:$NIM_RETRIEVAL_TAG" "$ECR_NIM_REPO:latest"
    
    success "NIM Retrieval image built successfully"
}

# Build NIM Llama image
build_nim_llama() {
    log "Building NIM Llama Docker image..."
    
    # This would typically be in a separate repository or subdirectory
    # For now, we'll create a placeholder Dockerfile
    local nim_dir="${PROJECT_ROOT}/nim-llama"
    
    if [ ! -d "$nim_dir" ]; then
        warn "NIM Llama directory not found. Creating placeholder..."
        mkdir -p "$nim_dir"
        cat > "$nim_dir/Dockerfile" << 'EOF'
FROM nvidia/cuda:11.8-runtime-ubuntu20.04

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF
        
        cat > "$nim_dir/requirements.txt" << 'EOF'
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
torch==2.1.0
transformers==4.35.0
accelerate==0.24.0
bitsandbytes==0.41.0
EOF
        
        cat > "$nim_dir/main.py" << 'EOF'
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="NIM Llama Service", version="1.0.0")

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 100
    temperature: float = 0.7

class GenerateResponse(BaseModel):
    text: str
    prompt: str

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/generate", response_model=GenerateResponse)
async def generate_text(request: GenerateRequest):
    # Placeholder implementation
    return GenerateResponse(
        prompt=request.prompt,
        text=f"Generated response for: {request.prompt}"
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
EOF
    fi
    
    cd "$nim_dir"
    
    # Build the image for linux/amd64 platform
    docker build --platform linux/amd64 -t "$ECR_LLAMA_REPO:$NIM_LLAMA_TAG" .
    
    # Tag for ECR
    docker tag "$ECR_LLAMA_REPO:$NIM_LLAMA_TAG" "$ECR_LLAMA_REPO:latest"
    
    success "NIM Llama image built successfully"
}

# Push images to ECR
push_images() {
    log "Pushing images to ECR..."
    
    # Push SeedCore image
    log "Pushing SeedCore image..."
    docker push "$ECR_REPO:$SEEDCORE_IMAGE_TAG"
    docker push "$ECR_REPO:latest"
    
    # Push NIM Retrieval image
    log "Pushing NIM Retrieval image..."
    docker push "$ECR_NIM_REPO:$NIM_RETRIEVAL_TAG"
    docker push "$ECR_NIM_REPO:latest"
    
    # Push NIM Llama image
    log "Pushing NIM Llama image..."
    docker push "$ECR_LLAMA_REPO:$NIM_LLAMA_TAG"
    docker push "$ECR_LLAMA_REPO:latest"
    
    success "All images pushed successfully to ECR"
}

# Clean up local images (optional)
cleanup_local() {
    if [ "${CLEANUP_LOCAL:-false}" = "true" ]; then
        log "Cleaning up local images..."
        
        docker rmi "$ECR_REPO:$SEEDCORE_IMAGE_TAG" || true
        docker rmi "$ECR_REPO:latest" || true
        docker rmi "$ECR_NIM_REPO:$NIM_RETRIEVAL_TAG" || true
        docker rmi "$ECR_NIM_REPO:latest" || true
        docker rmi "$ECR_LLAMA_REPO:$NIM_LLAMA_TAG" || true
        docker rmi "$ECR_LLAMA_REPO:latest" || true
        
        success "Local images cleaned up"
    fi
}

# Main function
main() {
    log "Starting Docker image build and push process..."
    
    load_env
    login_ecr
    build_seedcore
    build_nim_retrieval
    build_nim_llama
    push_images
    cleanup_local
    
    success "Docker image build and push completed successfully!"
    
    echo
    echo "Images pushed to ECR:"
    echo "  - SeedCore: $ECR_REPO:$SEEDCORE_IMAGE_TAG"
    echo "  - NIM Retrieval: $ECR_NIM_REPO:$NIM_RETRIEVAL_TAG"
    echo "  - NIM Llama: $ECR_LLAMA_REPO:$NIM_LLAMA_TAG"
    echo
    echo "Next step: ./deploy-all.sh"
}

# Run main function
main "$@"


