#!/usr/bin/env bash

service_status() {
  local service="$1"
  docker container inspect "$service" --format '{{.State.Status}}' 2>/dev/null || true
}

service_health() {
  local service="$1"
  docker container inspect "$service" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true
}

container_exists() {
  local service="$1"
  docker container inspect "$service" >/dev/null 2>&1
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

wait_for_service_ok() {
  local service="$1"
  local timeout_seconds="${2:-$RECOVERY_TIMEOUT_SECONDS}"
  local started_at now elapsed status health

  started_at="$(date +%s)"
  while true; do
    if service_ok "$service"; then
      return 0
    fi

    status="$(service_status "$service")"
    health="$(service_health "$service")"
    if [[ -z "$status" || "$status" == "exited" || "$status" == "dead" || "$health" == "unhealthy" ]]; then
      return 1
    fi

    now="$(date +%s)"
    elapsed=$((now - started_at))
    if (( elapsed >= timeout_seconds )); then
      return 1
    fi

    sleep 2
  done
}

attempt_service_recovery() {
  local service="$1"
  local compose_name="$2"
  local reason="$3"
  local current_status

  log "⚠️ 检测到 ${service} 异常，开始自愈 (reason=${reason})"
  current_status="$(service_status "$service")"

  if [[ "$current_status" == "running" ]]; then
    if docker restart "$service" >>"$LOG_FILE" 2>&1; then
      if wait_for_service_ok "$service"; then
        recovered_services+=("${service}:docker-restart")
        log "✅ ${service} 通过 docker restart 恢复成功"
        return 0
      fi
    fi
  else
    if docker start "$service" >>"$LOG_FILE" 2>&1; then
      if wait_for_service_ok "$service"; then
        recovered_services+=("${service}:docker-start")
        log "✅ ${service} 通过 docker start 恢复成功"
        return 0
      fi
    fi
  fi

  log "⚠️ 快捷启动/重启 ${service} 未能恢复，尝试 docker compose up -d --force-recreate ${compose_name}"
  compose up -d --force-recreate --no-build "$compose_name" >>"$LOG_FILE" 2>&1
  if wait_for_service_ok "$service"; then
    recovered_services+=("${service}:compose-up-recreate")
    log "✅ ${service} 通过 docker compose up -d --force-recreate ${compose_name} 恢复成功"
    return 0
  fi

  return 1
}
