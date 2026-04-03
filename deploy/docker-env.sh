#!/usr/bin/env bash

set -euo pipefail

BASE_DIR="${BASE_DIR:-/data/tgmsg}"
CURRENT_APP_DIR="${BASE_DIR}/current"
LEGACY_APP_DIR="${BASE_DIR}/app"

if [[ -n "${APP_DIR:-}" ]]; then
  APP_DIR="$APP_DIR"
elif [[ -L "$CURRENT_APP_DIR" || -d "$CURRENT_APP_DIR" ]]; then
  APP_DIR="$CURRENT_APP_DIR"
else
  APP_DIR="$LEGACY_APP_DIR"
fi

SHARED_DIR="${SHARED_DIR:-${BASE_DIR}/shared}"
COMPOSE_FILE="${COMPOSE_FILE:-${APP_DIR}/docker-compose.yml}"

if [[ -n "${ENV_FILE:-}" ]]; then
  ENV_FILE="$ENV_FILE"
elif [[ -f "${SHARED_DIR}/.env" ]]; then
  ENV_FILE="${SHARED_DIR}/.env"
else
  ENV_FILE="${APP_DIR}/.env"
fi

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ 缺少命令: $cmd" >&2
    exit 1
  fi
}

load_base_env() {
  require_command docker

  if [[ ! -f "$ENV_FILE" ]]; then
    echo "❌ 未找到环境变量文件: $ENV_FILE" >&2
    exit 1
  fi

  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

_inspect_env_value() {
  local container="$1"
  local key="$2"
  docker inspect "$container" \
    --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | awk -F= -v name="$key" '$1 == name {print substr($0, index($0, "=") + 1); exit}'
}

ensure_runtime_env() {
  load_base_env

  export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(_inspect_env_value tgmsg-postgres POSTGRES_PASSWORD)}"
  export REDIS_PASSWORD="${REDIS_PASSWORD:-$(_inspect_env_value tgmsg-redis REDIS_PASSWORD)}"

  export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(_inspect_env_value tgmsg-app JWT_SECRET_KEY)}"
  export ENCRYPTION_KEY="${ENCRYPTION_KEY:-$(_inspect_env_value tgmsg-app ENCRYPTION_KEY)}"
  export H5_BASE_URL="${H5_BASE_URL:-$(_inspect_env_value tgmsg-app H5_BASE_URL)}"
  export WORKER_INTERVAL="${WORKER_INTERVAL:-$(_inspect_env_value tgmsg-app WORKER_INTERVAL)}"
  export MAX_FAILURE_COUNT="${MAX_FAILURE_COUNT:-$(_inspect_env_value tgmsg-app MAX_FAILURE_COUNT)}"
  export BIND_MAX_FAILURES="${BIND_MAX_FAILURES:-$(_inspect_env_value tgmsg-app BIND_MAX_FAILURES)}"
  export BIND_FAILURE_WINDOW_SECONDS="${BIND_FAILURE_WINDOW_SECONDS:-$(_inspect_env_value tgmsg-app BIND_FAILURE_WINDOW_SECONDS)}"
  export BIND_LOCK_SECONDS="${BIND_LOCK_SECONDS:-$(_inspect_env_value tgmsg-app BIND_LOCK_SECONDS)}"
  export SERVE_FRONTEND="${SERVE_FRONTEND:-$(_inspect_env_value tgmsg-app SERVE_FRONTEND)}"
  export POSTGRES_DB="${POSTGRES_DB:-$(_inspect_env_value tgmsg-postgres POSTGRES_DB)}"
  export POSTGRES_USER="${POSTGRES_USER:-$(_inspect_env_value tgmsg-postgres POSTGRES_USER)}"

  local required=(
    TG_API_ID
    TG_API_HASH
    BOT_TOKEN
    ADMIN_API_TOKEN
    POSTGRES_PASSWORD
    REDIS_PASSWORD
    JWT_SECRET_KEY
  )

  local missing=()
  local key
  for key in "${required[@]}"; do
    if [[ -z "${!key:-}" ]]; then
      missing+=("$key")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "❌ 缺少运行所需环境变量: ${missing[*]}" >&2
    exit 1
  fi
}

compose() {
  (cd "$APP_DIR" && docker compose --env-file "$ENV_FILE" "$@")
}
