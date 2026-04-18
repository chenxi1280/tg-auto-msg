#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ensure_runtime_env

echo "==> 发布目录: $APP_DIR"
echo "==> 环境文件: $ENV_FILE"

require_image() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" ]]; then
    echo "❌ 缺少镜像变量: ${name}，请确认 release 目录存在 .image.env" >&2
    exit 1
  fi
}

docker_login_ghcr() {
  if [[ "$TGMSG_APP_IMAGE" != ghcr.io/* && "$TGMSG_FRONTEND_IMAGE" != ghcr.io/* ]]; then
    return 0
  fi

  if [[ -z "${GHCR_USERNAME:-}" || -z "${GHCR_TOKEN:-}" ]]; then
    echo "❌ 拉取 GHCR 镜像需要 GHCR_USERNAME 和 GHCR_TOKEN" >&2
    exit 1
  fi

  printf '%s\n' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin >/dev/null
}

prune_static_releases() {
  local releases_dir="$1"
  local current_link="$2"
  local keep="${3:-5}"
  mapfile -t release_paths < <(find "$releases_dir" -mindepth 1 -maxdepth 1 -type d | sort)
  local total="${#release_paths[@]}"

  if (( total <= keep )); then
    return 0
  fi

  local current_target=""
  if [[ -L "$current_link" ]]; then
    current_target="$(readlink -f "$current_link")"
  fi

  local remove_count=$(( total - keep ))
  local idx=0
  while (( idx < remove_count )); do
    if [[ "${release_paths[$idx]}" != "$current_target" ]]; then
      rm -rf "${release_paths[$idx]}"
    fi
    idx=$((idx + 1))
  done
}

publish_static_from_image() {
  local image="$1"
  local base_dir="$2"
  local release_id="$3"
  local keep="$4"
  local html_dir="/usr/share/nginx/html"
  local releases_dir="${base_dir}/releases"
  local release_dir="${releases_dir}/${release_id}"
  local tmp_dir="${release_dir}.tmp"
  local current_link="${base_dir}/current"
  local container_id=""

  echo "==> 发布前端静态文件: ${image} -> ${release_dir}"
  mkdir -p "$releases_dir"
  rm -rf "$tmp_dir"
  mkdir -p "$tmp_dir"

  container_id="$(docker create "$image")"
  cleanup_static_container() {
    if [[ -n "$container_id" ]]; then
      docker rm "$container_id" >/dev/null 2>&1 || true
    fi
  }
  trap 'cleanup_static_container; trap - RETURN' RETURN

  docker cp "${container_id}:${html_dir}/." "$tmp_dir/"
  test -f "${tmp_dir}/index.html"

  cleanup_static_container
  container_id=""
  trap - RETURN

  rm -rf "$release_dir"
  mv "$tmp_dir" "$release_dir"
  ln -sfn "$release_dir" "${current_link}.tmp"
  mv -Tf "${current_link}.tmp" "$current_link"
  prune_static_releases "$releases_dir" "$current_link" "$keep"
}

require_image TGMSG_APP_IMAGE
require_image TGMSG_FRONTEND_IMAGE
docker_login_ghcr

echo "==> 确保业务数据库存在"
bash "$SCRIPT_DIR/ensure-database.sh"

echo "==> 拉取后端镜像"
compose pull app

echo "==> 拉取前端静态产物镜像"
docker pull "$TGMSG_FRONTEND_IMAGE"

echo "==> 执行数据库迁移"
compose run --rm --no-deps app python -m backend.database.runtime.migration_cli apply

publish_static_from_image \
  "$TGMSG_FRONTEND_IMAGE" \
  "${TGMSG_FRONTEND_STATIC_BASE_DIR:-/data/infra/www/msg.telema.cn}" \
  "${STATIC_RELEASE_ID:-$(basename "$APP_DIR")}" \
  "${STATIC_KEEP_RELEASES:-5}"

wait_for_container_health() {
  local container_name="$1"
  local timeout_seconds="${2:-360}"
  local started_at
  started_at="$(date +%s)"

  while true; do
    local now elapsed status health
    now="$(date +%s)"
    elapsed=$((now - started_at))
    status="$(docker inspect "$container_name" --format '{{.State.Status}}' 2>/dev/null || true)"
    health="$(docker inspect "$container_name" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"

    if [[ "$status" == "running" && ( -z "$health" || "$health" == "healthy" ) ]]; then
      echo "✅ ${container_name} 已就绪: status=$status health=${health:-none}"
      return 0
    fi

    if [[ "$status" == "exited" || "$health" == "unhealthy" ]]; then
      echo "❌ ${container_name} 启动失败: status=${status:-unknown} health=${health:-none}" >&2
      echo "==> 最近 200 行 ${container_name} 日志" >&2
      docker logs --tail 200 "$container_name" >&2 || true
      return 1
    fi

    if (( elapsed >= timeout_seconds )); then
      echo "❌ 等待 ${container_name} 超时: status=${status:-unknown} health=${health:-none}" >&2
      echo "==> 最近 200 行 ${container_name} 日志" >&2
      docker logs --tail 200 "$container_name" >&2 || true
      return 1
    fi

    echo "⏳ 等待 ${container_name} 就绪 (${elapsed}s/${timeout_seconds}s): status=${status:-unknown} health=${health:-none}"
    sleep 5
  done
}

echo "==> 启动后端服务（app）"
compose up -d --no-build --remove-orphans app
wait_for_container_health tgmsg-app 420

echo "==> 检查容器状态"
compose ps

services=(
  tgmsg-app
)

for service in "${services[@]}"; do
  status="$(docker inspect "$service" --format '{{.State.Status}}' 2>/dev/null || true)"
  health="$(docker inspect "$service" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"

  if [[ "$status" != "running" ]]; then
    echo "❌ 服务未运行: $service (status=${status:-missing})" >&2
    exit 1
  fi
  if [[ -n "$health" && "$health" != "healthy" && "$health" != "starting" ]]; then
    echo "❌ 服务健康检查失败: $service (health=$health)" >&2
    exit 1
  fi
  echo "✅ $service status=$status health=${health:-none}"
done

echo "✅ 完整部署检查完成"
