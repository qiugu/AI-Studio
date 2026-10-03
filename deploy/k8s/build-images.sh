#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_IMAGE="ai-studio-backend:local"
FRONTEND_IMAGE="ai-studio-frontend:local"
BUILD_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${BUILD_DIR}"
}
trap cleanup EXIT

command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
command -v ctr >/dev/null || { echo "ctr is required" >&2; exit 1; }

echo "Building ${BACKEND_IMAGE} for linux/arm64..."
sudo docker build --platform linux/arm64 -t "${BACKEND_IMAGE}" "${PROJECT_ROOT}/backend"

echo "Building ${FRONTEND_IMAGE} for linux/arm64..."
sudo docker build --platform linux/arm64 -f "${PROJECT_ROOT}/frontend/Dockerfile.k8s" \
  -t "${FRONTEND_IMAGE}" "${PROJECT_ROOT}/frontend"

for image in "${BACKEND_IMAGE}" "${FRONTEND_IMAGE}"; do
  archive="${BUILD_DIR}/${image%%:*}.tar"
  echo "Importing ${image} into containerd namespace k8s.io..."
  sudo docker save --output "${archive}" "${image}"
  sudo ctr --namespace k8s.io images import "${archive}"
done

sudo ctr --namespace k8s.io images list | grep -E 'ai-studio-(backend|frontend)' || true
