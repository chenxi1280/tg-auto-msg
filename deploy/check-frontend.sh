#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

LOG_DIR="${LOG_DIR:-/data/tgmsg/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/frontend-watchdog.log}"

mkdir -p "$LOG_DIR"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

ensure_runtime_env

container_id="$(docker ps -aq -f name='^tgmsg-frontend$')"
if [[ -z "$container_id" ]]; then
  log "⚠️ tgmsg-frontend 不存在，执行 docker compose up -d frontend"
  compose up -d frontend >>"$LOG_FILE" 2>&1
  exit 0
fi

status="$(docker inspect tgmsg-frontend --format '{{.State.Status}}' 2>/dev/null || true)"
health="$(docker inspect tgmsg-frontend --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"

if [[ "$status" == "running" && "$health" == "healthy" ]]; then
  log "✅ tgmsg-frontend 正常运行 (status=$status, health=$health)"
  exit 0
fi

log "⚠️ tgmsg-frontend 异常 (status=${status:-unknown}, health=${health:-none})，尝试拉起"
if docker start tgmsg-frontend >>"$LOG_FILE" 2>&1; then
  sleep 3
else
  log "⚠️ docker start 失败，回退到 docker compose up -d frontend"
  compose up -d frontend >>"$LOG_FILE" 2>&1
  sleep 3
fi

status="$(docker inspect tgmsg-frontend --format '{{.State.Status}}' 2>/dev/null || true)"
health="$(docker inspect tgmsg-frontend --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"

if [[ "$status" == "running" ]]; then
  log "✅ tgmsg-frontend 已恢复 (status=$status, health=${health:-none})"
  exit 0
fi

log "❌ tgmsg-frontend 恢复失败 (status=${status:-unknown}, health=${health:-none})"
exit 1
