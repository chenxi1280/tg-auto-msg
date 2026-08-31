#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/service-recovery.sh"

ALERT_ENV_FILE="${ALERT_ENV_FILE:-/etc/tgmsg/service-health.env}"
LOG_DIR="${LOG_DIR:-${APP_LOG_DIR:-/data/tgmsg/shared/logs}}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/service-health.log}"
STATE_FILE="${STATE_FILE:-${LOG_DIR}/service-health.state}"
HEALTHCHECK_TIMEZONE="${HEALTHCHECK_TIMEZONE:-${TIMEZONE:-Asia/Shanghai}}"
MEM_AVAILABLE_THRESHOLD_MB="${MEM_AVAILABLE_THRESHOLD_MB:-128}"
DISK_USAGE_THRESHOLD_PERCENT="${DISK_USAGE_THRESHOLD_PERCENT:-90}"
RECOVERY_WAIT_SECONDS="${RECOVERY_WAIT_SECONDS:-8}"
RECOVERY_TIMEOUT_SECONDS="${RECOVERY_TIMEOUT_SECONDS:-75}"
DAILY_REPORT_HOUR="${DAILY_REPORT_HOUR:-09}"
TGMSG_LOG_SCAN_WINDOW="${TGMSG_LOG_SCAN_WINDOW:-30m}"
TGMSG_ERROR_MATCH_LIMIT="${TGMSG_ERROR_MATCH_LIMIT:-6}"
TGMSG_LOG_TAIL_LINES="${TGMSG_LOG_TAIL_LINES:-400}"
TGMSG_LOG_SCAN_FILE_LIMIT="${TGMSG_LOG_SCAN_FILE_LIMIT:-3}"
APP_CONTAINER="${APP_CONTAINER:-tgmsg-app}"
LEGACY_FRONTEND_CONTAINER="${LEGACY_FRONTEND_CONTAINER:-tgmsg-frontend}"
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

expected_app_binding() {
  printf '%s:%s' "${TGMSG_APP_BIND_HOST:-127.0.0.1}" "${TGMSG_APP_HOST_PORT:-18000}"
}

current_app_binding() {
  docker port "$APP_CONTAINER" 8000/tcp 2>/dev/null | awk 'NR == 1 {print $1}'
}

app_binding_ok() {
  [[ "$(current_app_binding)" == "$(expected_app_binding)" ]]
}

legacy_frontend_present() {
  container_exists "$LEGACY_FRONTEND_CONTAINER"
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

attempt_app_alignment_recovery() {
  local reason="$1"

  log "⚠️ 检测到 tgmsg 发布漂移，开始按当前 compose 对齐 (reason=${reason})"
  compose up -d --force-recreate --no-build --remove-orphans app >>"$LOG_FILE" 2>&1

  if wait_for_service_ok "$APP_CONTAINER" && app_binding_ok && ! legacy_frontend_present; then
    recovered_services+=("${APP_CONTAINER}:compose-align")
    log "✅ tgmsg 发布漂移已自动修复"
    return 0
  fi

  return 1
}

ensure_runtime_env
HEALTHCHECK_TIMEZONE="${HEALTHCHECK_TIMEZONE:-${TIMEZONE:-Asia/Shanghai}}"
TGMSG_APP_HEALTH_URL="${TGMSG_APP_HEALTH_URL:-http://127.0.0.1:${TGMSG_APP_HOST_PORT:-18000}/openapi.json}"
TGMSG_FRONTEND_HEALTH_URL="${TGMSG_FRONTEND_HEALTH_URL:-http://127.0.0.1/}"
TGMSG_FRONTEND_HEALTH_HOST="${TGMSG_FRONTEND_HEALTH_HOST:-msg.telema.cn}"
TGMSG_PUBLIC_API_HEALTH_URL="${TGMSG_PUBLIC_API_HEALTH_URL:-https://127.0.0.1/api/admin-auth/me}"
TGMSG_PUBLIC_API_HEALTH_HOST="${TGMSG_PUBLIC_API_HEALTH_HOST:-msg.telema.cn}"
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

alignment_reasons=()
current_binding="$(current_app_binding)"
if ! app_binding_ok; then
  alignment_reasons+=(
    "tgmsg-app 宿主机端口映射异常: expected=$(expected_app_binding), actual=${current_binding:-missing}"
  )
fi
if legacy_frontend_present; then
  alignment_reasons+=(
    "检测到遗留容器: ${LEGACY_FRONTEND_CONTAINER} (status=$(service_status "$LEGACY_FRONTEND_CONTAINER"))"
  )
fi

if (( ${#alignment_reasons[@]} > 0 )); then
  alignment_reason_text="$(printf '%s; ' "${alignment_reasons[@]}")"
  if ! attempt_app_alignment_recovery "$alignment_reason_text"; then
    for reason in "${alignment_reasons[@]}"; do
      issues+=("$reason")
    done
    issues+=("tgmsg 发布漂移自动修复失败")
  fi
fi

if ! curl -fsS --max-time 8 -H "Host: ${TGMSG_FRONTEND_HEALTH_HOST}" "$TGMSG_FRONTEND_HEALTH_URL" >/dev/null; then
  issues+=("HTTP 首页异常: ${TGMSG_FRONTEND_HEALTH_HOST} -> ${TGMSG_FRONTEND_HEALTH_URL}")
fi

if ! curl -fsS --max-time 8 "$TGMSG_APP_HEALTH_URL" >/dev/null; then
  issues+=("HTTP OpenAPI 异常: ${TGMSG_APP_HEALTH_URL}")
fi

public_api_status="$(curl -k -sS -o /dev/null -w '%{http_code}' --max-time 8 \
  -H "Host: ${TGMSG_PUBLIC_API_HEALTH_HOST}" \
  "$TGMSG_PUBLIC_API_HEALTH_URL" || true)"
case "$public_api_status" in
  200|401|403)
    ;;
  *)
    issues+=(
      "宿主机 API 反代异常: ${TGMSG_PUBLIC_API_HEALTH_HOST} -> ${TGMSG_PUBLIC_API_HEALTH_URL} (status=${public_api_status:-curl-failed})"
    )
    ;;
esac

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
