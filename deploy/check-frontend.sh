#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

LOG_DIR="${LOG_DIR:-${APP_LOG_DIR:-/data/tgmsg/shared/logs}}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/frontend-watchdog.log}"

mkdir -p "$LOG_DIR"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

ensure_runtime_env

FRONTEND_HEALTH_URL="${FRONTEND_HEALTH_URL:-http://127.0.0.1/}"
FRONTEND_HEALTH_HOST="${FRONTEND_HEALTH_HOST:-msg.telema.cn}"

if curl -fsS --max-time 8 -H "Host: ${FRONTEND_HEALTH_HOST}" "$FRONTEND_HEALTH_URL" >/dev/null; then
  log "✅ 前端静态入口正常 (${FRONTEND_HEALTH_HOST} -> ${FRONTEND_HEALTH_URL})"
  exit 0
fi

log "❌ 前端静态入口异常 (${FRONTEND_HEALTH_HOST} -> ${FRONTEND_HEALTH_URL})"
exit 1
