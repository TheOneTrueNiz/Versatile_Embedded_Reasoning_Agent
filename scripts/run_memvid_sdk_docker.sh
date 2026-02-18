#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="vera-memvid-sdk:latest"

docker_exec() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}

if ! docker_exec image inspect "${IMAGE}" >/dev/null 2>&1; then
  "${ROOT_DIR}/scripts/build_memvid_sdk_docker.sh" >&2
fi

if [ -n "${MEMVID_PATH:-}" ]; then
  if [[ "${MEMVID_PATH}" == /data/* ]]; then
    MEM_PATH="${MEMVID_PATH}"
  else
    MEM_PATH="/data/$(basename "${MEMVID_PATH}")"
  fi
else
  MEM_PATH="/data/memvid.mv2"
fi
MEM_KIND="${MEMVID_KIND:-basic}"

exec docker_exec run --rm -i \
  -e MEMVID_PATH="${MEM_PATH}" \
  -e MEMVID_KIND="${MEM_KIND}" \
  -v "${MEMVID_HOST_DIR:-${ROOT_DIR}/vera_memory}:/data" \
  "${IMAGE}"
