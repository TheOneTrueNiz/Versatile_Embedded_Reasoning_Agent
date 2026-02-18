#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${ROOT_DIR}/mcp_server_and_tools/mcp-server-youtube-transcript"
DIST_PATH="${SERVER_DIR}/dist/index.js"

if [ -z "${YOUTUBE_API_KEY:-}" ]; then
  KEY_PATH="${YOUTUBE_API_KEY_PATH:-${HOME}/Documents/creds/google/youtube_api_key}"
  if [ -d "${KEY_PATH}" ]; then
    if [ -f "${KEY_PATH}/YOUTUBE_API_KEY" ]; then
      KEY_PATH="${KEY_PATH}/YOUTUBE_API_KEY"
    elif [ -f "${KEY_PATH}/youtube_api_key" ]; then
      KEY_PATH="${KEY_PATH}/youtube_api_key"
    fi
  elif [ ! -f "${KEY_PATH}" ] && [ -f "${HOME}/Documents/creds/google/YOUTUBE_API_KEY" ]; then
    KEY_PATH="${HOME}/Documents/creds/google/YOUTUBE_API_KEY"
  fi

  if [ -f "${KEY_PATH}" ]; then
    YOUTUBE_API_KEY="$(tr -d '\r\n' < "${KEY_PATH}")"
    export YOUTUBE_API_KEY
  fi
fi

if [ -z "${YTDLP_PATH:-}" ] && [ -x "${ROOT_DIR}/.venv/bin/yt-dlp" ]; then
  export YTDLP_PATH="${ROOT_DIR}/.venv/bin/yt-dlp"
fi

if [ ! -f "${DIST_PATH}" ]; then
  echo "Missing ${DIST_PATH}."
  echo "Run: (cd \"${SERVER_DIR}\" && npm install && npm run build)"
  exit 1
fi

exec node "${DIST_PATH}"
