#!/bin/bash

# Docker Image Size Analysis Script

echo "🐳 Docker Image Size Analysis"
echo "=============================="

# Function to analyze image layers
analyze_image() {
    local image_name=$1
    echo ""
    echo "📊 Analyzing image: $image_name"
    echo "--------------------------------"
    
    # Get image size
    local size=$(docker images $image_name --format "table {{.Size}}")
    echo "Image size: $size"
    
    # Create temporary container to analyze contents
    local container_id=$(docker create $image_name)
    
    echo ""
    echo "📁 Directory sizes in image:"
    docker run --rm $image_name sh -c "du -h -d 1 / 2>/dev/null | sort -hr"
    
    echo ""
    echo "🐍 Python packages size:"
    docker run --rm $image_name sh -c "du -h -d 1 /usr/local/lib/python*/site-packages/ 2>/dev/null | head -10"
    
    # Clean up
    docker rm $container_id >/dev/null 2>&1
}

# Function to build and analyze
build_and_analyze() {
    local dockerfile=$1
    local tag=$2
    
    echo ""
    echo "🔨 Building with $dockerfile..."
    docker build -f $dockerfile -t $tag ..
    
    if [ $? -eq 0 ]; then
        analyze_image $tag
    else
        echo "❌ Build failed for $dockerfile"
    fi
}

# Main execution
echo "Current directory: $(pwd)"
echo ""

# Check if we're in the right directory
if [ ! -f "Dockerfile" ]; then
    echo "❌ Error: Dockerfile not found in current directory"
    echo "Please run this script from the docker/ directory"
    exit 1
fi

# Analyze existing images if they exist
if docker images | grep -q "seedcore-api"; then
    echo "📋 Existing seedcore-api images:"
    docker images | grep seedcore-api
    echo ""
fi

# Build and analyze with different Dockerfiles
echo "🚀 Building optimized images for comparison..."

# Build with standard Dockerfile
build_and_analyze "docker/Dockerfile" "seedcore-api:optimized"

# Alpine Dockerfile removed - using optimized Dockerfile instead

echo ""
echo "✅ Analysis complete!"
echo ""
echo "💡 Recommendations:"
echo "1. Use the smaller image (likely Alpine-based)"
echo "2. Consider removing unused dependencies"
echo "3. Use multi-stage builds (already implemented)"
echo "4. Mount data volumes instead of copying into image" 