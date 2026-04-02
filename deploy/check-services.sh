#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ALERT_ENV_FILE="${ALERT_ENV_FILE:-/etc/tgmsg/service-health.env}"
LOG_DIR="${LOG_DIR:-/data/tgmsg/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/service-health.log}"
STATE_FILE="${STATE_FILE:-${LOG_DIR}/service-health.state}"
MEM_AVAILABLE_THRESHOLD_MB="${MEM_AVAILABLE_THRESHOLD_MB:-128}"
DISK_USAGE_THRESHOLD_PERCENT="${DISK_USAGE_THRESHOLD_PERCENT:-90}"
RECOVERY_WAIT_SECONDS="${RECOVERY_WAIT_SECONDS:-8}"
DAILY_REPORT_HOUR="${DAILY_REPORT_HOUR:-09}"

mkdir -p "$LOG_DIR"

if [[ -f "$ALERT_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ALERT_ENV_FILE"
  set +a
fi

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

issues=()
recovered_services=()
services=(tgmsg-postgres tgmsg-redis tgmsg-app tgmsg-frontend)

for service in "${services[@]}"; do
  status="$(service_status "$service")"
  health="$(service_health "$service")"

  if [[ -z "$status" ]]; then
    issues+=("容器缺失: $service")
    continue
  fi

  if [[ "$service" == "tgmsg-app" || "$service" == "tgmsg-frontend" ]]; then
    if ! service_ok "$service"; then
      compose_name="${service#tgmsg-}"
      reason="status=${status:-missing},health=${health:-none}"
      if ! attempt_service_recovery "$service" "$compose_name" "$reason"; then
        issues+=("容器自愈失败: $service (status=$(service_status "$service"), health=$(service_health "$service"))")
      fi
    fi
    continue
  fi

  if [[ "$status" != "running" ]]; then
    issues+=("容器未运行: $service (status=$status)")
    continue
  fi

  if [[ -n "$health" && "$health" != "healthy" ]]; then
    issues+=("容器健康异常: $service (health=$health)")
  fi
done

if ! curl -fsS --max-time 8 http://127.0.0.1/ >/dev/null; then
  issues+=("HTTP 首页异常: http://127.0.0.1/")
fi

if ! curl -fsS --max-time 8 http://127.0.0.1/openapi.json >/dev/null; then
  issues+=("HTTP OpenAPI 异常: http://127.0.0.1/openapi.json")
fi

available_mb="$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)"
if (( available_mb < MEM_AVAILABLE_THRESHOLD_MB )); then
  issues+=("可用内存过低: ${available_mb}MB")
fi

disk_usage_percent="$(df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
if (( disk_usage_percent >= DISK_USAGE_THRESHOLD_PERCENT )); then
  issues+=("系统盘使用率过高: ${disk_usage_percent}%")
fi

current_status="HEALTHY"
summary="服务全部正常"

if (( ${#issues[@]} > 0 )); then
  current_status="ALERT"
  summary="$(printf '%s\n' "${issues[@]}")"
fi

current_fingerprint="$(printf '%s' "$summary" | hash_text)"
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
