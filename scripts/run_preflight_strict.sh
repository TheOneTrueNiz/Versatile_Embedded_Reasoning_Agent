#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${VERA_API_HOST:-127.0.0.1}"
PORT="${VERA_API_PORT:-8788}"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "${PYTHON_BIN}" ] || [ ! -x "${PYTHON_BIN}" ]; then
  echo "[FAIL] No usable Python interpreter found."
  exit 1
fi

cd "${ROOT_DIR}"

echo "[INFO] Running extended preflight (golden + automation)..."
"${ROOT_DIR}/scripts/run_preflight_extended.sh"

echo "[INFO] Running controlled checks (restart/discord/voice/fallback/budget)..."
CONTROLLED_REPORT="${ROOT_DIR}/tmp/controlled_checks_strict_$(date -u +%Y%m%dT%H%M%SZ).json"
if "${PYTHON_BIN}" scripts/vera_controlled_checks.py --host "${HOST}" --port "${PORT}" --output "${CONTROLLED_REPORT}"; then
  echo "[PASS] Controlled checks passed."
else
  echo "[WARN] Controlled checks reported failures. See: ${CONTROLLED_REPORT}"
fi

echo "[INFO] Building strict checklist unresolved-items report..."
GAPS_REPORT="${ROOT_DIR}/tmp/checklist_gaps_strict_$(date -u +%Y%m%dT%H%M%SZ).json"
"${PYTHON_BIN}" scripts/vera_checklist_gap_report.py --output "${GAPS_REPORT}"

UNRESOLVED="$("${PYTHON_BIN}" - <<'PY' "${GAPS_REPORT}"
import json, sys
obj=json.load(open(sys.argv[1], "r", encoding="utf-8"))
print(int(obj.get("unresolved_count") or 0))
PY
)"

if [ "${UNRESOLVED}" -gt 0 ]; then
  echo "[WARN] Strict checklist still has ${UNRESOLVED} unresolved items."
  echo "[WARN] Controlled report: ${CONTROLLED_REPORT}"
  echo "[WARN] Gap report: ${GAPS_REPORT}"
  exit 1
fi

echo "[PASS] Strict preflight complete with zero unresolved checklist items."
exit 0
