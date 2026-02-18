#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="vera-memvid-sdk:latest"
CONTEXT="${ROOT_DIR}/services/memvid_sdk"

docker_exec() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}

docker_exec build -f "${ROOT_DIR}/services/memvid_sdk/Dockerfile" -t "${IMAGE}" "${CONTEXT}"
echo "Built ${IMAGE}"
