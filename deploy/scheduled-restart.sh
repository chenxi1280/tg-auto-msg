#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

LOG_DIR="${LOG_DIR:-${APP_LOG_DIR:-/data/tgmsg/shared/logs}}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/scheduled-restart.log}"
LOCK_FILE="${LOCK_FILE:-/run/tgmsg-scheduled-restart.lock}"
APP_CONTAINER="${APP_CONTAINER:-tgmsg-app}"
RESTART_TIMEOUT_SECONDS="${RESTART_TIMEOUT_SECONDS:-300}"
HEALTH_WAIT_SECONDS="${HEALTH_WAIT_SECONDS:-420}"

mkdir -p "$LOG_DIR"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

load_optional_env() {
  local env_file="${TGMSG_SCHEDULED_RESTART_ENV_FILE:-/etc/tgmsg/scheduled-restart.env}"

  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

run_with_timeout() {
  local seconds="$1"
  shift
  timeout "$seconds" "$@"
}

container_health() {
  docker inspect "$APP_CONTAINER" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true
}

container_status() {
  docker inspect "$APP_CONTAINER" --format '{{.State.Status}}' 2>/dev/null || true
}

set_runtime_defaults() {
  TGMSG_APP_HEALTH_URL="${TGMSG_APP_HEALTH_URL:-http://127.0.0.1:${TGMSG_APP_HOST_PORT:-18000}/openapi.json}"
  TGMSG_PUBLIC_API_HEALTH_URL="${TGMSG_PUBLIC_API_HEALTH_URL:-https://127.0.0.1/api/admin-auth/me}"
  TGMSG_PUBLIC_API_HEALTH_HOST="${TGMSG_PUBLIC_API_HEALTH_HOST:-msg.telema.cn}"
}

wait_for_app_ready() {
  local started_at now elapsed status health
  started_at="$(date +%s)"

  while true; do
    status="$(container_status)"
    health="$(container_health)"

    if [[ "$status" == "running" && ( -z "$health" || "$health" == "healthy" ) ]]; then
      log "✅ ${APP_CONTAINER} ready: status=$status health=${health:-none}"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - started_at))
    if (( elapsed >= HEALTH_WAIT_SECONDS )); then
      log "❌ ${APP_CONTAINER} health wait timeout: status=${status:-missing} health=${health:-none}"
      docker logs --tail 120 "$APP_CONTAINER" >>"$LOG_FILE" 2>&1 || true
      return 1
    fi

    log "⏳ waiting ${APP_CONTAINER}: ${elapsed}s/${HEALTH_WAIT_SECONDS}s status=${status:-missing} health=${health:-none}"
    sleep 5
  done
}

restart_app() {
  log "==> restart app with current release: APP_DIR=$APP_DIR ENV_FILE=$ENV_FILE"
  (
    cd "$APP_DIR"
    run_with_timeout "$RESTART_TIMEOUT_SECONDS" \
      docker compose --env-file "$ENV_FILE" up -d --no-build --force-recreate app
  ) >>"$LOG_FILE" 2>&1
}

verify_http() {
  local public_status

  curl -fsS --max-time 8 "$TGMSG_APP_HEALTH_URL" >/dev/null
  public_status="$(curl -k -sS -o /dev/null -w '%{http_code}' --max-time 8 \
    -H "Host: ${TGMSG_PUBLIC_API_HEALTH_HOST}" \
    "$TGMSG_PUBLIC_API_HEALTH_URL")"

  case "$public_status" in
    200|401|403)
      log "✅ HTTP checks passed: app=${TGMSG_APP_HEALTH_URL}, public_api_status=${public_status}"
      ;;
    *)
      log "❌ public API check failed: status=${public_status:-curl-failed}"
      return 1
      ;;
  esac
}

main() {
  require_command docker
  require_command flock
  require_command timeout
  require_command curl

  load_optional_env
  if [[ "${TGMSG_SCHEDULED_RESTART_ENABLED:-1}" != "1" ]]; then
    log "scheduled restart disabled by TGMSG_SCHEDULED_RESTART_ENABLED"
    return 0
  fi

  ensure_runtime_env
  set_runtime_defaults
  export TZ="${TIMEZONE:-Asia/Shanghai}"

  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "scheduled restart already running, exit"
    return 1
  fi

  log "==> scheduled restart started"
  restart_app
  wait_for_app_ready
  verify_http
  log "==> scheduled restart completed"
}

main "$@"
