#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="${ROOT_DIR}/services/memvid_sdk/.venv"
PYTHON_CMD="$(command -v python3 || command -v python || true)"

if [ -z "${PYTHON_CMD}" ]; then
  echo "Error: python3/python not found." >&2
  exit 1
fi

if [ ! -x "${ENV_DIR}/bin/python" ]; then
  rm -rf "${ENV_DIR}"
  "${PYTHON_CMD}" -m venv "${ENV_DIR}"
fi

if ! "${ENV_DIR}/bin/python" -m pip --version >/dev/null 2>&1; then
  "${ENV_DIR}/bin/python" -m ensurepip --upgrade
fi

"${ENV_DIR}/bin/python" -m pip install --upgrade pip
"${ENV_DIR}/bin/python" -m pip install memvid-sdk

echo "Memvid SDK env ready at ${ENV_DIR}"
