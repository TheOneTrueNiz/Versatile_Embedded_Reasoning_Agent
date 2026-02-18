#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="${ROOT_DIR}/services/memvid_sdk/.venv"
WORKER="${ROOT_DIR}/services/memvid_sdk/memvid_worker.py"

if [ ! -x "${ENV_DIR}/bin/python" ]; then
  if [ -x "${ROOT_DIR}/scripts/setup_memvid_sdk_env.sh" ]; then
    "${ROOT_DIR}/scripts/setup_memvid_sdk_env.sh" >&2
  fi
fi

if [ ! -x "${ENV_DIR}/bin/python" ]; then
  echo "Memvid SDK env not found and auto-bootstrap failed." >&2
  exit 1
fi

exec "${ENV_DIR}/bin/python" "${WORKER}"
