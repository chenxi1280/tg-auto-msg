#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ALERT_ENV_FILE="${ALERT_ENV_FILE:-/etc/tgmsg/service-health.env}"
LOG_DIR="${LOG_DIR:-${APP_LOG_DIR:-/data/tgmsg/shared/logs}}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/service-health.log}"
STATE_FILE="${STATE_FILE:-${LOG_DIR}/service-health.state}"
HEALTHCHECK_TIMEZONE="${HEALTHCHECK_TIMEZONE:-${TIMEZONE:-Asia/Shanghai}}"
MEM_AVAILABLE_THRESHOLD_MB="${MEM_AVAILABLE_THRESHOLD_MB:-128}"
DISK_USAGE_THRESHOLD_PERCENT="${DISK_USAGE_THRESHOLD_PERCENT:-90}"
RECOVERY_WAIT_SECONDS="${RECOVERY_WAIT_SECONDS:-8}"
DAILY_REPORT_HOUR="${DAILY_REPORT_HOUR:-09}"
TGMSG_LOG_SCAN_WINDOW="${TGMSG_LOG_SCAN_WINDOW:-30m}"
TGMSG_ERROR_MATCH_LIMIT="${TGMSG_ERROR_MATCH_LIMIT:-6}"
TGMSG_LOG_TAIL_LINES="${TGMSG_LOG_TAIL_LINES:-400}"
TGMSG_LOG_SCAN_FILE_LIMIT="${TGMSG_LOG_SCAN_FILE_LIMIT:-3}"
APP_CONTAINER="${APP_CONTAINER:-tgmsg-app}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-app-infra-postgres}"
REDIS_CONTAINER="${REDIS_CONTAINER:-app-infra-redis}"
APP_RUNTIME_LOG_DIR="${APP_RUNTIME_LOG_DIR:-/data/tgmsg/logs}"

mkdir -p "$LOG_DIR"

if [[ -f "$ALERT_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ALERT_ENV_FILE"
  set +a
fi

normalize_alert_text() {
  sed -E \
    -e 's/\r$//' \
    -e 's/^[[:space:]]*//' \
    -e 's/^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:.:+-]+[[:space:]]+\|[[:space:]]*[A-Z]+[[:space:]]+\|[[:space:]]*//' \
    -e 's/^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:.:+-]+[[:space:]]*//' \
    -e 's/[[:space:]]+/ /g' \
    -e 's/[[:space:]]+$//'
}

dedupe_lines_by_normalized_content() {
  local line key
  declare -A seen=()

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    key="$(printf '%s' "$line" | normalize_alert_text)"
    [[ -z "$key" ]] && continue
    if [[ -z "${seen[$key]+x}" ]]; then
      seen["$key"]=1
      printf '%s\n' "$line"
    fi
  done
}

resolve_window_start_value() {
  local window="$1"

  case "$window" in
    '' )
      date '+%Y-%m-%d %H:%M:%S'
      ;;
    *m )
      date -d "${window%m} minutes ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S'
      ;;
    *h )
      date -d "${window%h} hours ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S'
      ;;
    *d )
      date -d "${window%d} days ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S'
      ;;
    * )
      date -d "$window ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S'
      ;;
  esac
}

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

json_escape() {
  awk 'BEGIN { RS = "\0"; ORS = "" } { gsub(/\\/,"\\\\"); gsub(/"/,"\\\""); gsub(/\r/,""); gsub(/\n/,"\\n"); print }'
}

send_wecom() {
  local message="$1"
  local escaped response

  if [[ -z "${QYWX_WEBHOOK_URL:-}" ]]; then
    log "⚠️ 未配置 QYWX_WEBHOOK_URL，跳过企业微信通知"
    return 1
  fi

  escaped="$(printf '%s' "$message" | json_escape)"
  response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' \
    -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"$escaped\"}}" \
    "$QYWX_WEBHOOK_URL")"

  if [[ "$response" != *'"errcode":0'* ]]; then
    log "⚠️ 企业微信通知返回异常: $response"
    return 1
  fi

  log "📨 企业微信告警已发送"
}

hash_text() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

service_status() {
  local service="$1"
  docker inspect "$service" --format '{{.State.Status}}' 2>/dev/null || true
}

service_health() {
  local service="$1"
  docker inspect "$service" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true
}

service_ok() {
  local service="$1"
  local status health

  status="$(service_status "$service")"
  health="$(service_health "$service")"

  if [[ "$status" != "running" ]]; then
    return 1
  fi

  if [[ -n "$health" && "$health" != "healthy" ]]; then
    return 1
  fi

  return 0
}

tail_container_errors() {
  local container="$1"

  docker logs --since "$TGMSG_LOG_SCAN_WINDOW" --tail "$TGMSG_LOG_TAIL_LINES" "$container" 2>&1 \
    | grep -E '(\| ERROR\s+\||\| CRITICAL\s+\||ERROR:|CRITICAL:|FATAL:|PANIC:)' \
    | tail -n "$TGMSG_ERROR_MATCH_LIMIT" || true
}

runtime_log_errors() {
  local log_files

  log_files="$(find "$APP_RUNTIME_LOG_DIR" -maxdepth 1 -type f -name 'app_*.log' 2>/dev/null \
    | sort \
    | tail -n "$TGMSG_LOG_SCAN_FILE_LIMIT")"
  if [[ -z "$log_files" ]]; then
    return 0
  fi

  xargs awk -v start="$LOG_WINDOW_START_VALUE" -v end="$LOG_WINDOW_END_VALUE" '
    function is_error_line(line) {
      return line ~ /\| (ERROR|CRITICAL)[[:space:]]+\|/ || line ~ /^(ERROR|CRITICAL|FATAL|PANIC):/
    }

    /^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}/ {
      timestamp = substr($0, 1, 19)
      gsub(/T/, " ", timestamp)
      if (timestamp >= start && timestamp <= end && is_error_line($0)) {
        print
      }
    }
  ' <<<"$log_files" | tail -n "$TGMSG_ERROR_MATCH_LIMIT" || true
}

check_tgmsg_recent_errors() {
  local matches log_source

  matches=""
  log_source="容器日志"
  if [[ -d "$APP_RUNTIME_LOG_DIR" ]]; then
    matches="$(runtime_log_errors)"
    if [[ -n "$matches" ]]; then
      log_source="运行日志文件"
    fi
  fi

  if [[ -z "$matches" ]]; then
    matches="$(tail_container_errors "$APP_CONTAINER")"
    log_source="容器日志"
  fi

  matches="$(printf '%s\n' "$matches" | dedupe_lines_by_normalized_content)"

  if [[ -n "$matches" ]]; then
    issues+=("tgmsg 最近 ${TGMSG_LOG_SCAN_WINDOW} 存在错误日志 (${log_source}):")
    while IFS= read -r line; do
      [[ -n "$line" ]] && issues+=("  $line")
    done <<<"$matches"
  fi
}

check_postgres_middleware() {
  local status health stderr_file

  status="$(service_status "$POSTGRES_CONTAINER")"
  health="$(service_health "$POSTGRES_CONTAINER")"

  if [[ -z "$status" ]]; then
    issues+=("PostgreSQL 容器缺失: $POSTGRES_CONTAINER")
    return
  fi

  if [[ "$status" != "running" ]]; then
    issues+=("PostgreSQL 容器未运行: $POSTGRES_CONTAINER (status=$status)")
    return
  fi

  if [[ -n "$health" && "$health" != "healthy" ]]; then
    issues+=("PostgreSQL 容器健康异常: $POSTGRES_CONTAINER (health=$health)")
  fi

  stderr_file="$(mktemp)"
  if ! docker exec -u postgres "$POSTGRES_CONTAINER" psql -U postgres -d postgres -Atqc 'select 1;' >/dev/null 2>"$stderr_file"; then
    cat "$stderr_file" >>"$LOG_FILE"
    rm -f "$stderr_file"
    issues+=("PostgreSQL 查询失败: $POSTGRES_CONTAINER")
    return
  fi
  rm -f "$stderr_file"
}

check_redis_middleware() {
  local status health redis_password stderr_file

  status="$(service_status "$REDIS_CONTAINER")"
  health="$(service_health "$REDIS_CONTAINER")"

  if [[ -z "$status" ]]; then
    issues+=("Redis 容器缺失: $REDIS_CONTAINER")
    return
  fi

  if [[ "$status" != "running" ]]; then
    issues+=("Redis 容器未运行: $REDIS_CONTAINER (status=$status)")
    return
  fi

  if [[ -n "$health" && "$health" != "healthy" ]]; then
    issues+=("Redis 容器健康异常: $REDIS_CONTAINER (health=$health)")
  fi

  redis_password="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$REDIS_CONTAINER" 2>/dev/null | awk -F= '/^REDIS_PASSWORD=/{print substr($0,16); exit}')"
  if [[ -z "$redis_password" ]]; then
    issues+=("Redis 密码读取失败: $REDIS_CONTAINER")
    return
  fi

  stderr_file="$(mktemp)"
  if ! docker exec "$REDIS_CONTAINER" redis-cli -a "$redis_password" ping >/dev/null 2>"$stderr_file"; then
    cat "$stderr_file" >>"$LOG_FILE"
    rm -f "$stderr_file"
    issues+=("Redis PING 失败: $REDIS_CONTAINER")
    return
  fi
  rm -f "$stderr_file"
}

attempt_service_recovery() {
  local service="$1"
  local compose_name="$2"
  local reason="$3"

  log "⚠️ 检测到 ${service} 异常，开始自愈 (reason=${reason})"

  if docker start "$service" >>"$LOG_FILE" 2>&1; then
    sleep "$RECOVERY_WAIT_SECONDS"
  else
    log "⚠️ docker start ${service} 失败，回退到 docker compose up -d ${compose_name}"
  fi

  if service_ok "$service"; then
    recovered_services+=("${service}:docker-start")
    log "✅ ${service} 通过 docker start 恢复成功"
    return 0
  fi

  compose up -d "$compose_name" >>"$LOG_FILE" 2>&1
  sleep "$RECOVERY_WAIT_SECONDS"

  if service_ok "$service"; then
    recovered_services+=("${service}:compose-up")
    log "✅ ${service} 通过 docker compose up -d ${compose_name} 恢复成功"
    return 0
  fi

  return 1
}

ensure_runtime_env
HEALTHCHECK_TIMEZONE="${HEALTHCHECK_TIMEZONE:-${TIMEZONE:-Asia/Shanghai}}"
TGMSG_APP_HEALTH_URL="${TGMSG_APP_HEALTH_URL:-http://127.0.0.1:${TGMSG_APP_HOST_PORT:-18000}/openapi.json}"
TGMSG_FRONTEND_HEALTH_URL="${TGMSG_FRONTEND_HEALTH_URL:-http://127.0.0.1/}"
TGMSG_FRONTEND_HEALTH_HOST="${TGMSG_FRONTEND_HEALTH_HOST:-msg.telema.cn}"
export TZ="$HEALTHCHECK_TIMEZONE"

LOG_WINDOW_END_VALUE="$(date '+%Y-%m-%d %H:%M:%S')"
LOG_WINDOW_START_VALUE="$(resolve_window_start_value "$TGMSG_LOG_SCAN_WINDOW")"

issues=()
recovered_services=()
services=("$APP_CONTAINER")

for service in "${services[@]}"; do
  status="$(service_status "$service")"
  health="$(service_health "$service")"

  if [[ -z "$status" ]]; then
    issues+=("容器缺失: $service")
    continue
  fi

  if ! service_ok "$service"; then
    compose_name="${service#tgmsg-}"
    reason="status=${status:-missing},health=${health:-none}"
    if ! attempt_service_recovery "$service" "$compose_name" "$reason"; then
      issues+=("容器自愈失败: $service (status=$(service_status "$service"), health=$(service_health "$service"))")
    fi
  fi
done

check_postgres_middleware
check_redis_middleware

if ! curl -fsS --max-time 8 -H "Host: ${TGMSG_FRONTEND_HEALTH_HOST}" "$TGMSG_FRONTEND_HEALTH_URL" >/dev/null; then
  issues+=("HTTP 首页异常: ${TGMSG_FRONTEND_HEALTH_HOST} -> ${TGMSG_FRONTEND_HEALTH_URL}")
fi

if ! curl -fsS --max-time 8 "$TGMSG_APP_HEALTH_URL" >/dev/null; then
  issues+=("HTTP OpenAPI 异常: ${TGMSG_APP_HEALTH_URL}")
fi

available_mb="$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)"
if (( available_mb < MEM_AVAILABLE_THRESHOLD_MB )); then
  issues+=("可用内存过低: ${available_mb}MB")
fi

disk_usage_percent="$(df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
if (( disk_usage_percent >= DISK_USAGE_THRESHOLD_PERCENT )); then
  issues+=("系统盘使用率过高: ${disk_usage_percent}%")
fi

check_tgmsg_recent_errors

current_status="HEALTHY"
summary="服务全部正常"

if (( ${#issues[@]} > 0 )); then
  current_status="ALERT"
  summary="$(printf '%s\n' "${issues[@]}")"
fi

current_fingerprint="$(printf '%s' "$summary" | normalize_alert_text | hash_text)"
previous_status=""
previous_fingerprint=""
last_daily_report_date=""

if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
  previous_status="${STATUS:-}"
  previous_fingerprint="${FINGERPRINT:-}"
  last_daily_report_date="${LAST_DAILY_REPORT_DATE:-}"
fi

host_name="$(hostname)"
timestamp="$(date '+%Y-%m-%d %H:%M:%S %Z')"
today="$(date '+%Y-%m-%d')"
current_hour="$(date '+%H')"

if [[ "$current_status" == "ALERT" ]]; then
  log "❌ 服务巡检发现异常"
  printf '%s\n' "$summary" | tee -a "$LOG_FILE"

  if [[ "$previous_status" != "ALERT" || "$previous_fingerprint" != "$current_fingerprint" ]]; then
    send_wecom "【tgmsg 线上告警】
时间: $timestamp
主机: $host_name

$summary"
  fi
else
  log "✅ 服务巡检正常"

  if [[ "$previous_status" == "ALERT" ]]; then
    send_wecom "【tgmsg 告警恢复】
时间: $timestamp
主机: $host_name

服务状态已恢复正常。"
  fi

  if (( ${#recovered_services[@]} > 0 )); then
    recovered_summary="$(printf '%s\n' "${recovered_services[@]}")"
    send_wecom "【tgmsg 自动恢复成功】
时间: $timestamp
主机: $host_name

以下服务已自动恢复:
$recovered_summary"
  fi

  if [[ "$current_hour" == "$DAILY_REPORT_HOUR" && "$last_daily_report_date" != "$today" ]]; then
    send_wecom "【tgmsg 每日巡检正常】
时间: $timestamp
主机: $host_name
可用内存: ${available_mb}MB
系统盘使用率: ${disk_usage_percent}%

当前容器状态正常，首页与 OpenAPI 检查通过。"
    last_daily_report_date="$today"
  fi
fi

cat >"$STATE_FILE" <<EOF
STATUS=$current_status
FINGERPRINT=$current_fingerprint
LAST_DAILY_REPORT_DATE=$last_daily_report_date
EOF

if [[ "$current_status" == "ALERT" ]]; then
  exit 1
fi

exit 0
