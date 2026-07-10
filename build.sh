#!/bin/bash
set -e

# Build script for NILScript Control Plane
# Usage: ./build.sh [tag] [registry]
# Example: ./build.sh latest ghcr.io/nilscript-org

TAG="${1:-latest}"
REGISTRY="${2:-basheirkh}"
IMAGE_NAME="${REGISTRY}/nilscript:controlplane-${TAG}"

echo "🐳 Building Docker image: $IMAGE_NAME"

docker build -t "$IMAGE_NAME" .

echo "✅ Build complete: $IMAGE_NAME"
echo ""
echo "To push to registry:"
echo "  docker push $IMAGE_NAME"
echo ""
echo "To run locally:"
echo "  docker run -p 8000:8000 -e DATABASE_URL=sqlite:///./nilscript.db $IMAGE_NAME"
